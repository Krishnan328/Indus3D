"""
api/routes/files.py
--------------------
Typed file-manager API on top of Moonraker's file endpoints (blueprint under /api/v1/files).

The browser never names a Moonraker URL or a filesystem path. It names a *root* (gcodes, config, ...) and a
path *inside* that root; both are validated here, and every operation is a fixed Moonraker call built
from the validated parts.

  GET  /roots                          roots Moonraker reports, restricted to the whitelist (+ custom roots it lists)
  GET  /list?root=&path=&extended=1    one directory: dirs, files (+ slicer metadata), disk usage, print state
  GET  /tree?root=                     flat recursive listing (for the go-to-file finder)
  GET  /download?root=&path=[&inline=1]   streamed file (Range supported); inline only for safe preview types
  GET  /text?root=&path=               a text file for the editor (JSON, with its modified time)
  PUT  /text                           save a text file {root, path, content, expected_modified?}
  POST /mkdir      {root, path}
  POST /rename     {root, path, new_name}
  POST /move       {root, items[], dest_dir, dest_root?, overwrite?}
  POST /copy       {root, items[], dest_dir, dest_root?, overwrite?}
  POST /delete     {root, items[], confirmed?}          non-empty folders need confirmed: true
  POST /zip        {root, items[]}                      streams a ZIP, the temporary archive is removed afterwards
  POST /upload     multipart: file, root, path          streamed to Moonraker, size-limited
  POST /thumbs     {root, items:[{path, v}]}            batched thumbnails as data URIs (one request, not N)
  GET  /metadata?path=                 slicer metadata of a gcode file
  POST /metascan   {path}              ask Moonraker to re-read a file's metadata

Safety rules (tests in tests/test_files_routes.py):
  * paths: relative, no "..", no absolute paths, no backslashes, no NUL/control characters
  * roots: whitelist; roots Moonraker reports read-only stay read-only (403 on every write)
  * while a print is running the file being printed (and folders containing it) can not be deleted,
    renamed, moved or overwritten, and nothing in the "config" root can be changed
  * Moonraker unreachable -> 502; endpoint missing on that Moonraker -> 501 {"unsupported": true}
  * with the simulator running the same API is served from an in-memory tree
"""

import base64
import io
import logging
import mimetypes
import posixpath
import re
import threading
import time
import uuid
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request, stream_with_context

from api import mr_client
from api.moonraker_util import MoonrakerError
from api.mr_client import MoonrakerHTTPError, Unsupported, error_response

files_bp = Blueprint("files", __name__)

BUILTIN_ROOTS = ("gcodes", "config", "config_examples", "docs", "logs", "timelapse")
_RESERVED_ROOTS = {"database", "secrets", "gcode_metadata"}
_CUSTOM_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
ROOTS_TTL_S = 30.0

MAX_PATH_LEN = 1024
MAX_SEGMENT_LEN = 255
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 ** 3
MAX_BATCH_ITEMS = 500
MAX_THUMB_BATCH = 40
THUMB_MAX_BYTES = 256 * 1024

META_KEYS = (
    "slicer", "slicer_version", "filament_type", "filament_name", "filament_total", "filament_weight_total",
    "first_layer_extr_temp", "first_layer_bed_temp", "chamber_temp", "layer_height", "first_layer_height",
    "nozzle_diameter", "estimated_time", "object_height", "print_start_time", "job_id",
    "layer_count", "analysis",
)


# ── Path handling ─────────────────────────────────────────────────────────────

class PathError(ValueError):
    """The client sent a root or path that is not acceptable."""


def clean_rel(path, *, allow_empty: bool = True) -> str:
    """Normalise a path *inside a root*. Raises PathError for anything that could leave it.

    Rejected: non-strings, NUL / control characters, backslashes, absolute paths (leading '/' or a drive
    letter), any '..' segment, over-long paths. Empty and '.' segments are dropped.
    """
    if not isinstance(path, str):
        raise PathError("path must be a string")
    if len(path) > MAX_PATH_LEN:
        raise PathError("path too long")
    if "\x00" in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise PathError("invalid character in path")
    if "\\" in path:
        raise PathError("backslashes are not allowed in paths")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise PathError("absolute paths are not allowed")
    parts: List[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise PathError("'..' is not allowed in paths")
        if len(seg) > MAX_SEGMENT_LEN:
            raise PathError("path segment too long")
        parts.append(seg)
    rel = "/".join(parts)
    if not rel and not allow_empty:
        raise PathError("path required")
    return rel


def clean_name(name) -> str:
    """A single file/folder name (no separators), for rename and new-folder."""
    if not isinstance(name, str) or name != name.strip() or not name:
        raise PathError("invalid name")
    rel = clean_rel(name, allow_empty=False)
    if "/" in rel or rel != name or name in (".", ".."):
        raise PathError("a name can not contain '/'")
    return name


def join_rel(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def parent_of(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def base_of(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]


def is_within(rel: str, folder: str) -> bool:
    """True if ``rel`` equals ``folder`` or lies below it ('' is the root, everything is within it)."""
    return folder == "" or rel == folder or rel.startswith(folder + "/")


def mr_file_path(root: str, rel: str = "") -> str:
    """``/server/files/<root>/<rel>`` with every segment percent-encoded."""
    return "/server/files/" + "/".join(quote(p, safe="") for p in [root] + ([s for s in rel.split("/") if s] if rel else []))


def mr_item(root: str, rel: str) -> str:
    """Moonraker's ``root/rel`` item notation (move/copy/zip bodies), unencoded."""
    return f"{root}/{rel}" if rel else root


# ── Print state ───────────────────────────────────────────────────────────────

def active_print() -> Tuple[bool, str]:
    """``(a print is running or paused, its file relative to gcodes)``."""
    import workers
    w = workers._active_worker
    latest = (getattr(w, "latest", None) or {}) if w else {}
    busy = latest.get("print_state") in ("printing", "paused")
    name = latest.get("filename") or ""
    try:
        name = clean_rel(name) if name else ""
    except PathError:
        name = ""
    return busy, name


def _is_simulator() -> bool:
    import workers
    w = workers._active_worker
    return w is not None and hasattr(w, "gcode_str")


# ── Backends ──────────────────────────────────────────────────────────────────

class MoonrakerBackend:
    """Everything the routes need from Moonraker, one fixed call per method."""
    simulator = False

    def roots(self) -> List[dict]:
        res = mr_client.call("GET", "/server/files/roots", what="file roots")
        return res if isinstance(res, list) else res.get("roots", [])

    def listdir(self, root: str, rel: str, extended: bool) -> dict:
        params = {"path": join_rel(root, rel)}
        if extended:
            params["extended"] = "true"
        return mr_client.call("GET", "/server/files/directory", params=params, what="directory listing")

    def tree(self, root: str) -> List[dict]:
        res = mr_client.call("GET", "/server/files/list", params={"root": root}, timeout=20, what="file list")
        return res if isinstance(res, list) else []

    def mkdir(self, root: str, rel: str) -> None:
        mr_client.call("POST", "/server/files/directory", json={"path": join_rel(root, rel)}, what="create directory")

    def rmdir(self, root: str, rel: str, force: bool) -> None:
        mr_client.call("DELETE", "/server/files/directory",
                       params={"path": join_rel(root, rel), "force": "true" if force else "false"}, what="delete directory")

    def rmfile(self, root: str, rel: str) -> None:
        mr_client.call("DELETE", mr_file_path(root, rel), what="delete file")

    def move(self, src: Tuple[str, str], dst: Tuple[str, str]) -> None:
        mr_client.call("POST", "/server/files/move",
                       json={"source": mr_item(*src), "dest": mr_item(*dst)}, what="move")

    def copy(self, src: Tuple[str, str], dst: Tuple[str, str]) -> None:
        mr_client.call("POST", "/server/files/copy",
                       json={"source": mr_item(*src), "dest": mr_item(*dst)}, what="copy")

    def open(self, root: str, rel: str, range_header: Optional[str] = None, timeout: float = 30):
        """A streamed ``requests.Response`` for the file body."""
        headers = {"Range": range_header} if range_header else None
        return mr_client.raw("GET", mr_file_path(root, rel), stream=True, headers=headers, timeout=timeout,
                             what="download")

    def read_bytes(self, root: str, rel: str, limit: int) -> Tuple[bytes, bool]:
        res = self.open(root, rel)
        try:
            buf = bytearray()
            for chunk in res.iter_content(65536):
                buf.extend(chunk)
                if len(buf) > limit:
                    return bytes(buf[:limit]), True
            return bytes(buf), False
        finally:
            res.close()

    def write(self, root: str, rel: str, fileobj, size: int) -> None:
        fields = {"root": root}
        folder = parent_of(rel)
        if folder:
            fields["path"] = folder
        body, headers = multipart_stream(fields, base_of(rel), fileobj, size)
        mr_client.call("POST", "/server/files/upload", data=body, headers=headers, timeout=300, what="upload")

    def zip(self, root: str, rels: List[str], dest: Tuple[str, str]):
        """Create the archive in Moonraker; returns ``(iterator over bytes, cleanup)``."""
        mr_client.call("POST", "/server/files/zip", timeout=120, what="zip",
                       json={"items": [mr_item(root, r) for r in rels], "dest": mr_item(*dest), "store_only": False})
        res = self.open(dest[0], dest[1], timeout=120)

        def cleanup():
            try:
                res.close()
            finally:
                try:
                    self.rmfile(*dest)
                except Exception as e:  # noqa: BLE001
                    logging.info(f"files: could not remove temporary archive {dest}: {e}")
        return res.iter_content(65536), cleanup

    def metadata(self, rel: str) -> dict:
        return mr_client.call("GET", "/server/files/metadata", params={"filename": rel}, what="metadata")

    def metascan(self, rel: str) -> dict:
        return mr_client.call("POST", "/server/files/metascan", json={"filename": rel}, timeout=30, what="metascan")


class SimBackend:
    """In-memory file trees so the UI works with the simulator and no printer."""
    simulator = True

    def __init__(self):
        self._lock = threading.RLock()
        self.reset()

    def reset(self):
        now = time.time()
        gcode = b"; simulated\nG28\nG1 X10 Y10 F3000\n"
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        self._perm = {"gcodes": "rw", "config": "rw", "config_examples": "r", "docs": "r", "logs": "r", "timelapse": "rw"}
        self.fs: Dict[str, Dict[str, dict]] = {r: {} for r in self._perm}
        meta = {"slicer": "PrusaSlicer", "slicer_version": "2.7.0", "filament_type": "PLA", "filament_name": "Generic PLA",
                "filament_total": 5400.0, "filament_weight_total": 16.2, "first_layer_extr_temp": 215.0,
                "first_layer_bed_temp": 60.0, "layer_height": 0.2, "estimated_time": 3720.0, "object_height": 48.0,
                "thumbnails": [{"width": 1, "height": 1, "size": len(png), "relative_path": ".thumbs/benchy-1x1.png"}]}
        self._put("gcodes", "benchy.gcode", gcode, now - 86400, meta)
        self._put("gcodes", ".thumbs/benchy-1x1.png", png, now - 86400)
        self._put("gcodes", "calibration/pa_test.gcode", gcode, now - 7200,
                  {"slicer": "Indus3D", "filament_type": "PLA", "layer_height": 0.2, "estimated_time": 900.0,
                   "filament_total": 1200.0, "filament_weight_total": 3.6})
        self._put("gcodes", "calibration/flow_cube.gcode", gcode, now - 7000)
        self._mkdir("gcodes", "archive")
        self._put("config", "printer.cfg", b"[printer]\nkinematics: corexy\nmax_velocity: 300\n\n[gcode_macro START]\ngcode:\n    G28\n", now - 3600)
        self._put("config", "moonraker.conf", b"[server]\nhost: 0.0.0.0\nport: 7125\n\n[job_queue]\n", now - 3600)
        self._put("config", "macros.cfg", b"[gcode_macro PARK]\ngcode:\n    G1 X0 Y0 F6000\n", now - 3000)
        self._put("config_examples", "example.cfg", b"# example\n", now - 9e6)
        self._put("docs", "README.md", b"# Docs\nHello\n", now - 9e6)
        self._put("logs", "klippy.log", b"Start printer\n", now - 600)
        self._mkdir("timelapse", "")

    # internal node helpers
    def _put(self, root, rel, data: bytes, modified=None, meta=None):
        with self._lock:
            parent = parent_of(rel)
            if parent:
                self._mkdir(root, parent)
            self.fs[root][rel] = {"type": "file", "data": data, "modified": modified or time.time(), "meta": meta or {}}

    def _mkdir(self, root, rel):
        with self._lock:
            parts = [p for p in rel.split("/") if p]
            for i in range(1, len(parts) + 1):
                sub = "/".join(parts[:i])
                self.fs[root].setdefault(sub, {"type": "dir", "modified": time.time()})

    def _err(self, status, msg):
        raise MoonrakerHTTPError(status, msg)

    def _node(self, root, rel):
        n = self.fs.get(root, {}).get(rel)
        if n is None:
            self._err(404, f"{rel or root} does not exist")
        return n

    def _children(self, root, rel):
        prefix = rel + "/" if rel else ""
        return {k: v for k, v in self.fs[root].items()
                if k.startswith(prefix) and "/" not in k[len(prefix):]}

    # backend API
    def roots(self):
        return [{"name": n, "path": f"/sim/{n}", "permissions": p} for n, p in self._perm.items()]

    def listdir(self, root, rel, extended):
        with self._lock:
            if rel:
                if self._node(root, rel)["type"] != "dir":
                    self._err(400, "not a directory")
            dirs, files = [], []
            for path, n in sorted(self._children(root, rel).items()):
                name = base_of(path)
                if name.startswith("."):
                    continue
                if n["type"] == "dir":
                    dirs.append({"dirname": name, "modified": n["modified"], "size": 4096, "permissions": self._perm[root]})
                else:
                    f = {"filename": name, "modified": n["modified"], "size": len(n["data"]), "permissions": self._perm[root]}
                    if extended:
                        f.update(n.get("meta") or {})
                    files.append(f)
            total = 8 * 1024 ** 3
            return {"dirs": dirs, "files": files, "disk_usage": {"total": total, "used": 2 * 1024 ** 3, "free": total - 2 * 1024 ** 3},
                    "root_info": {"name": root, "permissions": self._perm[root]}}

    def tree(self, root):
        with self._lock:
            return [{"path": k, "modified": v["modified"], "size": len(v["data"]), "permissions": self._perm[root]}
                    for k, v in sorted(self.fs[root].items()) if v["type"] == "file" and not base_of(k).startswith(".")]

    def mkdir(self, root, rel):
        with self._lock:
            if rel in self.fs[root]:
                self._err(409, f"{rel} already exists")
            self._mkdir(root, rel)

    def rmdir(self, root, rel, force):
        with self._lock:
            if self._node(root, rel)["type"] != "dir":
                self._err(400, "not a directory")
            if self._children(root, rel) and not force:
                self._err(403, "directory is not empty")
            for k in [k for k in self.fs[root] if is_within(k, rel)]:
                del self.fs[root][k]

    def rmfile(self, root, rel):
        with self._lock:
            if self._node(root, rel)["type"] != "file":
                self._err(400, "not a file")
            del self.fs[root][rel]

    def _transfer(self, src, dst, move):
        sroot, srel = src
        droot, drel = dst
        with self._lock:
            self._node(sroot, srel)
            items = {k: v for k, v in self.fs[sroot].items() if is_within(k, srel)}
            if move:
                for k in items:
                    del self.fs[sroot][k]
            self._mkdir(droot, parent_of(drel))
            for k, v in items.items():
                nk = drel + k[len(srel):]
                self.fs[droot][nk] = dict(v, modified=time.time()) if not move else v

    def move(self, src, dst):
        self._transfer(src, dst, True)

    def copy(self, src, dst):
        self._transfer(src, dst, False)

    def open(self, root, rel, range_header=None, timeout=30):
        with self._lock:
            n = self._node(root, rel)
            if n["type"] != "file":
                self._err(400, "not a file")
            data = n["data"]
        return _SimResponse(data)

    def read_bytes(self, root, rel, limit):
        data = self.open(root, rel).content
        return data[:limit], len(data) > limit

    def write(self, root, rel, fileobj, size):
        data = fileobj.read()
        with self._lock:
            old = self.fs[root].get(rel)
            self._put(root, rel, data, None, (old or {}).get("meta"))

    def zip(self, root, rels, dest):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z, self._lock:
            for rel in rels:
                for k, v in self.fs[root].items():
                    if is_within(k, rel) and v["type"] == "file":
                        z.writestr(k, v["data"])
        data = buf.getvalue()
        return iter([data]), (lambda: None)

    def metadata(self, rel):
        with self._lock:
            n = self._node("gcodes", rel)
            return dict(n.get("meta") or {}, filename=rel, size=len(n["data"]), modified=n["modified"])

    def metascan(self, rel):
        return self.metadata(rel)


class _SimResponse:
    def __init__(self, data: bytes):
        self.content = data
        self.status_code = 200
        self.headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(data))}

    def iter_content(self, n=65536):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass


_sim = SimBackend()
_moonraker = MoonrakerBackend()


def backend():
    return _sim if _is_simulator() else _moonraker


# ── Multipart streaming (uploads never sit in memory) ─────────────────────────

def multipart_stream(fields: Dict[str, str], filename: str, fileobj, size: int):
    boundary = uuid.uuid4().hex
    pre = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
        for k, v in fields.items())
    safe = filename.replace('"', "%22")
    pre += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8")
    post = f"\r\n--{boundary}--\r\n".encode()

    def gen():
        yield pre
        while True:
            chunk = fileobj.read(65536)
            if not chunk:
                break
            yield chunk
        yield post

    return gen(), {"Content-Type": f"multipart/form-data; boundary={boundary}",
                   "Content-Length": str(len(pre) + size + len(post))}


# ── Roots ─────────────────────────────────────────────────────────────────────

_roots_lock = threading.Lock()
_roots_cache: dict = {"t": 0.0, "key": None, "roots": None}


def reset_cache() -> None:
    with _roots_lock:
        _roots_cache.update(t=0.0, key=None, roots=None)
    _tree_cache.clear()
    _thumb_cache.clear()


def filter_roots(reported: Iterable[dict]) -> List[dict]:
    """Whitelist + custom roots Moonraker itself lists. 'r' or unknown permissions stay read-only."""
    out: Dict[str, dict] = {}
    for r in reported or []:
        name = r.get("name") if isinstance(r, dict) else None
        if not isinstance(name, str) or name in _RESERVED_ROOTS:
            continue
        builtin = name in BUILTIN_ROOTS
        if not builtin and not _CUSTOM_ROOT.match(name):
            continue
        perms = str(r.get("permissions", "r"))
        out[name] = {"name": name, "permissions": perms, "writable": "w" in perms, "custom": not builtin}
    ordered = [out[n] for n in BUILTIN_ROOTS if n in out]
    ordered += [out[n] for n in sorted(out) if out[n]["custom"]]
    return ordered


def get_roots() -> List[dict]:
    be = backend()
    key = "sim" if be.simulator else "mr"
    now = time.monotonic()
    with _roots_lock:
        if _roots_cache["roots"] is not None and _roots_cache["key"] == key and now - _roots_cache["t"] < ROOTS_TTL_S:
            return _roots_cache["roots"]
    roots = filter_roots(be.roots())
    with _roots_lock:
        _roots_cache.update(t=time.monotonic(), key=key, roots=roots)
    return roots


def resolve_root(name) -> dict:
    if not isinstance(name, str) or not name:
        raise PathError("root required")
    for r in get_roots():
        if r["name"] == name:
            return r
    raise PathError(f"unknown or unavailable root: {name}")


# ── Response helpers ──────────────────────────────────────────────────────────

class Refused(Exception):
    def __init__(self, status: int, message: str, code: str, **extra):
        super().__init__(message)
        self.status, self.message, self.code, self.extra = status, message, code, extra


def _fail(e: Exception):
    if isinstance(e, PathError):
        return jsonify({"error": str(e), "code": "bad_path"}), 400
    if isinstance(e, Refused):
        return jsonify({"error": e.message, "code": e.code, **e.extra}), e.status
    return error_response(e)


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise Refused(400, "JSON object body required", "bad_request")
    return data


def _items(data: dict, key: str = "items") -> List[str]:
    items = data.get(key)
    if not isinstance(items, list) or not items:
        raise Refused(400, f"{key} must be a non-empty list", "bad_request")
    if len(items) > MAX_BATCH_ITEMS:
        raise Refused(400, f"too many items (max {MAX_BATCH_ITEMS})", "bad_request")
    out, seen = [], set()
    for it in items:
        rel = clean_rel(it, allow_empty=False)
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _require_writable(root: dict) -> None:
    if not root["writable"]:
        raise Refused(403, f"'{root['name']}' is read-only", "read_only")


def _guard_print(root: str, rels: Iterable[str] = (), *, touches_file: bool = True) -> None:
    """409 when the change would affect a running print."""
    busy, active = active_print()
    if not busy:
        return
    if root == "config":
        raise Refused(409, "Files in 'config' can not be changed while a print is running", "busy")
    if touches_file and root == "gcodes" and active:
        for rel in rels:
            if is_within(active, rel):
                raise Refused(409, f"'{active}' is being printed", "busy", file=active)


def _meta_of(entry: dict, rel_dir: str) -> dict:
    meta = {k: entry[k] for k in META_KEYS if k in entry and entry[k] is not None}
    thumbs = []
    for t in entry.get("thumbnails") or []:
        rp = t.get("relative_path") if isinstance(t, dict) else None
        if not isinstance(rp, str):
            continue
        try:
            thumbs.append({"width": t.get("width"), "height": t.get("height"), "size": t.get("size"),
                           "path": clean_rel(join_rel(rel_dir, rp), allow_empty=False)})
        except PathError:
            continue
    if thumbs:
        meta["thumbnails"] = thumbs
    return meta


def normalise_listing(root: str, rel: str, raw: dict, extended: bool) -> dict:
    dirs = [{"name": d.get("dirname", ""), "path": join_rel(rel, d.get("dirname", "")), "modified": d.get("modified"),
             "permissions": d.get("permissions", "")} for d in raw.get("dirs", []) if d.get("dirname")]
    files = []
    for f in raw.get("files", []):
        name = f.get("filename")
        if not name:
            continue
        item = {"name": name, "path": join_rel(rel, name), "modified": f.get("modified"), "size": f.get("size"),
                "permissions": f.get("permissions", "")}
        if extended:
            meta = _meta_of(f, rel)
            item["meta"] = meta
            item["has_meta"] = bool(meta.get("estimated_time") is not None or meta.get("slicer"))
        files.append(item)
    usage = raw.get("disk_usage") or {}
    total, used = usage.get("total"), usage.get("used")
    disk = None
    if isinstance(total, (int, float)) and total > 0:
        disk = {"total": total, "used": used, "free": usage.get("free"),
                "percent": round(100.0 * used / total, 1) if isinstance(used, (int, float)) else None}
    return {"dirs": dirs, "files": files, "disk_usage": disk}


# ── Read routes ───────────────────────────────────────────────────────────────

@files_bp.route("/roots", methods=["GET"])
def roots():
    try:
        busy, active = active_print()
        return jsonify({"roots": get_roots(), "simulator": backend().simulator,
                        "print": {"busy": busy, "filename": active}})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@files_bp.route("/list", methods=["GET"])
def list_dir():
    try:
        root = resolve_root(request.args.get("root", "gcodes"))
        rel = clean_rel(request.args.get("path", ""))
        extended = request.args.get("extended", "1") != "0" and root["name"] == "gcodes"
        raw = backend().listdir(root["name"], rel, extended)
        busy, active = active_print()
        out = normalise_listing(root["name"], rel, raw, extended)
        return jsonify({"root": root["name"], "path": rel, "writable": root["writable"], **out,
                        "print": {"busy": busy, "filename": active}, "simulator": backend().simulator})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


_tree_cache: Dict[str, Tuple[float, list]] = {}


@files_bp.route("/tree", methods=["GET"])
def tree():
    try:
        root = resolve_root(request.args.get("root", "gcodes"))
        name = root["name"]
        hit = _tree_cache.get(name)
        if hit and time.monotonic() - hit[0] < 10:
            return jsonify({"root": name, "files": hit[1]})
        files = []
        for f in backend().tree(name):
            p = f.get("path")
            if isinstance(p, str):
                try:
                    p = clean_rel(p, allow_empty=False)
                except PathError:
                    continue
                files.append({"path": p, "size": f.get("size"), "modified": f.get("modified")})
        _tree_cache[name] = (time.monotonic(), files)
        return jsonify({"root": name, "files": files})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


_INLINE_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "bmp": "image/bmp", "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
}
_TEXT_EXT = {"txt", "md", "markdown", "cfg", "conf", "ini", "json", "log", "gcode", "g", "gco", "nc", "csv",
             "yaml", "yml", "toml", "py", "sh", "service", "jinja", "j2", "xml", "html", "htm", "svg", "css", "js"}


def _ext(rel: str) -> str:
    base = base_of(rel)
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def content_type_for(rel: str, inline: bool) -> Tuple[str, bool]:
    """``(content type, send inline)``. Active content (html/svg/js) is never rendered by the browser."""
    ext = _ext(rel)
    if inline and ext in _INLINE_TYPES:
        return _INLINE_TYPES[ext], True
    if inline and ext in _TEXT_EXT:
        return "text/plain; charset=utf-8", True
    return (mimetypes.guess_type(rel)[0] or "application/octet-stream") if not inline else "application/octet-stream", False


@files_bp.route("/download", methods=["GET"])
def download():
    try:
        root = resolve_root(request.args.get("root", ""))
        rel = clean_rel(request.args.get("path", ""), allow_empty=False)
        inline = request.args.get("inline") == "1"
        res = backend().open(root["name"], rel, request.headers.get("Range"))
        ctype, as_inline = content_type_for(rel, inline)
        headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
                   "Content-Disposition": ("inline" if as_inline else "attachment") +
                   f"; filename*=UTF-8''{quote(base_of(rel))}"}
        if as_inline:
            headers["Cache-Control"] = "private, max-age=300"
        for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
            if res.headers.get(h):
                headers[h] = res.headers[h]
        return Response(stream_with_context(_close_after(res)), status=res.status_code,
                        content_type=ctype, headers=headers)
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _close_after(res):
    try:
        for chunk in res.iter_content(65536):
            yield chunk
    finally:
        res.close()


@files_bp.route("/text", methods=["GET"])
def read_text():
    try:
        root = resolve_root(request.args.get("root", ""))
        rel = clean_rel(request.args.get("path", ""), allow_empty=False)
        be = backend()
        data, truncated = be.read_bytes(root["name"], rel, MAX_TEXT_BYTES)
        if truncated:
            raise Refused(413, f"File is larger than {MAX_TEXT_BYTES // 1024} KiB; download it instead", "too_large")
        if b"\x00" in data[:8192]:
            raise Refused(415, "Binary file; can not be shown as text", "binary")
        lossy = False
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text, lossy = data.decode("utf-8", errors="replace"), True
        busy, _ = active_print()
        return jsonify({"root": root["name"], "path": rel, "content": text, "size": len(data), "lossy": lossy,
                        "modified": _modified_of(be, root["name"], rel), "writable": root["writable"],
                        "locked": bool(busy and root["name"] == "config")})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _modified_of(be, root: str, rel: str) -> Optional[float]:
    try:
        for f in be.listdir(root, parent_of(rel), False).get("files", []):
            if f.get("filename") == base_of(rel):
                return f.get("modified")
    except Exception:  # noqa: BLE001
        pass
    return None


def _record_config_history(rel: str, old: str, new: str) -> None:
    """Keep the audit trail the legacy /config/<name> route writes (config_history), best effort."""
    import difflib
    import json
    try:
        from db.models import get_connection
        diff = "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                              fromfile=f"old_{rel}", tofile=f"new_{rel}", lineterm=""))
        conn = get_connection()
        conn.execute("INSERT INTO config_history (timestamp, operator_name, config_snapshot_json, diff_summary) "
                     "VALUES (?, ?, ?, ?)", (time.time(), "Unknown (UI)", json.dumps({rel: new}), diff))
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        logging.error(f"files: could not save config_history: {e}")


@files_bp.route("/text", methods=["PUT"])
def write_text():
    try:
        data = _body()
        root = resolve_root(data.get("root"))
        rel = clean_rel(data.get("path"), allow_empty=False)
        content = data.get("content")
        if not isinstance(content, str):
            raise Refused(400, "content must be a string", "bad_request")
        raw = content.encode("utf-8")
        if len(raw) > MAX_TEXT_BYTES:
            raise Refused(413, f"Content is larger than {MAX_TEXT_BYTES // 1024} KiB", "too_large")
        _require_writable(root)
        _guard_print(root["name"], [rel])
        be = backend()
        expected = data.get("expected_modified")
        current = _modified_of(be, root["name"], rel)
        if expected is not None and current is not None and not data.get("force") \
                and abs(float(current) - float(expected)) > 0.01:
            raise Refused(409, "The file changed on the printer since you opened it", "conflict", modified=current)
        old_text = ""
        if root["name"] == "config" and current is not None:
            try:
                old_text = be.read_bytes("config", rel, MAX_TEXT_BYTES)[0].decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                old_text = ""
        be.write(root["name"], rel, io.BytesIO(raw), len(raw))
        if root["name"] == "config":
            _record_config_history(rel, old_text, content)
        _tree_cache.pop(root["name"], None)
        return jsonify({"ok": True, "path": rel, "size": len(raw), "modified": _modified_of(be, root["name"], rel)})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


# ── Write routes ──────────────────────────────────────────────────────────────

@files_bp.route("/mkdir", methods=["POST"])
def mkdir():
    try:
        data = _body()
        root = resolve_root(data.get("root"))
        rel = clean_rel(data.get("path"), allow_empty=False)
        _require_writable(root)
        _guard_print(root["name"], touches_file=False)
        backend().mkdir(root["name"], rel)
        _tree_cache.pop(root["name"], None)
        return jsonify({"ok": True, "path": rel})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _names_in(be, root: str, folder: str) -> set:
    try:
        raw = be.listdir(root, folder, False)
    except MoonrakerHTTPError as e:
        if e.status == 404:
            return set()
        raise
    return {d.get("dirname") for d in raw.get("dirs", [])} | {f.get("filename") for f in raw.get("files", [])}


@files_bp.route("/rename", methods=["POST"])
def rename():
    try:
        data = _body()
        root = resolve_root(data.get("root"))
        rel = clean_rel(data.get("path"), allow_empty=False)
        new_name = clean_name(data.get("new_name"))
        _require_writable(root)
        _guard_print(root["name"], [rel])
        target = join_rel(parent_of(rel), new_name)
        if target == rel:
            raise Refused(400, "The name did not change", "no_change")
        be = backend()
        if new_name in _names_in(be, root["name"], parent_of(rel)):
            raise Refused(409, f"'{new_name}' already exists", "exists", conflicts=[target])
        be.move((root["name"], rel), (root["name"], target))
        _tree_cache.pop(root["name"], None)
        return jsonify({"ok": True, "path": target})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _transfer(kind: str):
    data = _body()
    root = resolve_root(data.get("root"))
    droot = resolve_root(data.get("dest_root") or root["name"])
    items = _items(data)
    dest_dir = clean_rel(data.get("dest_dir", ""))
    overwrite = bool(data.get("overwrite"))
    _require_writable(droot)
    if kind == "move":
        _require_writable(root)
        _guard_print(root["name"], items)
    _guard_print(droot["name"], [join_rel(dest_dir, base_of(i)) for i in items])
    be = backend()
    plan = []
    for rel in items:
        target = join_rel(dest_dir, base_of(rel))
        if root["name"] == droot["name"] and is_within(dest_dir, rel):
            raise Refused(400, f"Can not {kind} '{rel}' into itself", "into_itself")
        if root["name"] == droot["name"] and target == rel:
            raise Refused(400, f"'{rel}' is already in that folder", "no_change")
        plan.append((rel, target))
    existing = _names_in(be, droot["name"], dest_dir)
    conflicts = [t for _, t in plan if base_of(t) in existing]
    if conflicts and not overwrite:
        raise Refused(409, "Some items already exist in the destination", "exists", conflicts=conflicts)
    results = []
    for rel, target in plan:
        try:
            getattr(be, kind)((root["name"], rel), (droot["name"], target))
            results.append({"path": rel, "ok": True, "dest": target})
        except (MoonrakerHTTPError, Unsupported, MoonrakerError) as e:
            results.append({"path": rel, "ok": False, "error": str(e)})
            if isinstance(e, (Unsupported, MoonrakerError)):
                raise
    _tree_cache.pop(root["name"], None)
    _tree_cache.pop(droot["name"], None)
    return jsonify({"ok": all(r["ok"] for r in results), "results": results})


@files_bp.route("/move", methods=["POST"])
def move():
    try:
        return _transfer("move")
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@files_bp.route("/copy", methods=["POST"])
def copy():
    try:
        return _transfer("copy")
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@files_bp.route("/delete", methods=["POST"])
def delete():
    try:
        data = _body()
        root = resolve_root(data.get("root"))
        items = _items(data)
        confirmed = data.get("confirmed") is True
        _require_writable(root)
        _guard_print(root["name"], items)
        be = backend()
        kinds: Dict[str, str] = {}
        need_confirm: List[str] = []
        for rel in items:
            parent = parent_of(rel)
            raw = be.listdir(root["name"], parent, False)
            if any(d.get("dirname") == base_of(rel) for d in raw.get("dirs", [])):
                kinds[rel] = "dir"
                try:
                    inner = be.listdir(root["name"], rel, False)
                    if inner.get("dirs") or inner.get("files"):
                        need_confirm.append(rel)
                except MoonrakerHTTPError:
                    pass
            else:
                kinds[rel] = "file"
        if need_confirm and not confirmed:
            raise Refused(409, "Deleting non-empty folders needs confirmation", "confirmation_required",
                          needs_confirmation=need_confirm)
        results = []
        for rel in items:
            try:
                if kinds[rel] == "dir":
                    be.rmdir(root["name"], rel, force=rel in need_confirm)
                else:
                    be.rmfile(root["name"], rel)
                results.append({"path": rel, "ok": True})
            except MoonrakerHTTPError as e:
                results.append({"path": rel, "ok": False, "error": e.message})
        _tree_cache.pop(root["name"], None)
        ok = all(r["ok"] for r in results)
        status = 200 if (ok or any(r["ok"] for r in results)) else 409
        return jsonify({"ok": ok, "results": results}), status
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@files_bp.route("/zip", methods=["POST"])
def zip_items():
    try:
        data = _body()
        root = resolve_root(data.get("root"))
        items = _items(data)
        be = backend()
        dest_root = root["name"] if root["writable"] else next(
            (r["name"] for r in get_roots() if r["writable"] and r["name"] in ("gcodes", "config", "timelapse")), None)
        if dest_root is None:
            raise Refused(403, "No writable root to build the archive in", "read_only")
        _guard_print(dest_root, touches_file=False)
        dest = (dest_root, f".indus3d-zip-{int(time.time())}-{uuid.uuid4().hex[:6]}.zip")
        chunks, cleanup = be.zip(root["name"], items, dest)
        name = (base_of(items[0]) if len(items) == 1 else root["name"]) + ".zip"

        def stream():
            try:
                for c in chunks:
                    yield c
            finally:
                cleanup()
        return Response(stream_with_context(stream()), mimetype="application/zip", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "X-Content-Type-Options": "nosniff"})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@files_bp.route("/upload", methods=["POST"])
def upload():
    try:
        if "file" not in request.files:
            raise Refused(400, "file required", "bad_request")
        root = resolve_root(request.form.get("root"))
        folder = clean_rel(request.form.get("path", ""))
        f = request.files["file"]
        name = clean_name(f.filename or "")
        rel = join_rel(folder, name)
        _require_writable(root)
        _guard_print(root["name"], [rel])
        if request.content_length is not None and request.content_length > MAX_UPLOAD_BYTES:
            raise Refused(413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 ** 2} MiB", "too_large")
        stream = f.stream
        stream.seek(0, io.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size > MAX_UPLOAD_BYTES:
            raise Refused(413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 ** 2} MiB", "too_large")
        be = backend()
        if request.form.get("overwrite") != "1" and name in _names_in(be, root["name"], folder):
            raise Refused(409, f"'{name}' already exists", "exists", conflicts=[rel])
        be.write(root["name"], rel, stream, size)
        _tree_cache.pop(root["name"], None)
        return jsonify({"ok": True, "path": rel, "size": size})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


# ── Metadata and thumbnails ───────────────────────────────────────────────────

@files_bp.route("/metadata", methods=["GET"])
def metadata():
    try:
        rel = clean_rel(request.args.get("path", ""), allow_empty=False)
        raw = backend().metadata(rel)
        meta = _meta_of(raw, parent_of(rel))
        return jsonify({"path": rel, "meta": meta, "has_meta": bool(meta.get("estimated_time") is not None or meta.get("slicer"))})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@files_bp.route("/metascan", methods=["POST"])
def metascan():
    try:
        rel = clean_rel(_body().get("path"), allow_empty=False)
        raw = backend().metascan(rel)
        meta = _meta_of(raw, parent_of(rel))
        return jsonify({"ok": True, "path": rel, "meta": meta})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


_thumb_cache: "OrderedDict[tuple, Optional[str]]" = OrderedDict()
_THUMB_CACHE_MAX = 400
_thumb_lock = threading.Lock()


def _fetch_thumb(be, root: str, rel: str, v) -> Optional[str]:
    key = (root, rel, v)
    with _thumb_lock:
        if key in _thumb_cache:
            _thumb_cache.move_to_end(key)
            return _thumb_cache[key]
    data = None
    try:
        raw, truncated = be.read_bytes(root, rel, THUMB_MAX_BYTES)
        if not truncated:
            mime = _INLINE_TYPES.get(_ext(rel), "")
            if mime.startswith("image/"):
                data = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    except (MoonrakerHTTPError, Unsupported):
        data = None
    with _thumb_lock:
        _thumb_cache[key] = data
        while len(_thumb_cache) > _THUMB_CACHE_MAX:
            _thumb_cache.popitem(last=False)
    return data


@files_bp.route("/thumbs", methods=["POST"])
def thumbs():
    try:
        data = _body()
        root = resolve_root(data.get("root"))
        items = data.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_THUMB_BATCH:
            raise Refused(400, f"items must be a list of 1..{MAX_THUMB_BATCH}", "bad_request")
        wanted = []
        for it in items:
            if isinstance(it, dict):
                wanted.append((clean_rel(it.get("path"), allow_empty=False), it.get("v")))
        be = backend()
        out: Dict[str, Optional[str]] = {}
        if be.simulator:
            for rel, v in wanted:
                out[rel] = _fetch_thumb(be, root["name"], rel, v)
        else:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for (rel, _), val in zip(wanted, pool.map(lambda a: _fetch_thumb(be, root["name"], a[0], a[1]), wanted)):
                    out[rel] = val
        return jsonify({"thumbs": out})
    except Exception as e:  # noqa: BLE001
        return _fail(e)
