"""
api/routes/queue.py
--------------------
Print queue on top of Moonraker's ``[job_queue]`` component (blueprint under /api/v1/queue).

  GET  /status    queue state, jobs with slicer metadata, totals and an ETA that accounts for the running print
  POST /add       {filenames[], repeat?, position?: "end"|"front"}    "multiply" = repeat each file `repeat` times
  POST /remove    {ids[]} or {all: true}
  POST /pause     stop Moonraker from loading the next job
  POST /start     load and start the first queued job (when no print is running)
  POST /jump      {id}      move one job to the front (Moonraker's only native reorder)
  POST /reorder   {ids[]}   the full desired order; see ``plan_reorder`` for how it is carried out

Moonraker only knows "jump to front". Any other order is made by keeping the longest unchanged prefix,
adding the remaining files again in the wanted order and removing their old entries. The re-added jobs get
new ids and the queue is momentarily longer rather than shorter, so a failure half way never loses a job.

Starting stays manual by default: Moonraker only loads the next job automatically when ``[job_queue]``
sets ``automatic_transition: True``. Indus3D has no bed-clear detection, so it never turns that on; the status
tells the UI which mode is configured so it can say so. With ``[job_queue]`` missing the status answers
``available: false`` with the snippet to add, and the write routes answer 501 with the same snippet.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from api import mr_client
from api.mr_client import MoonrakerHTTPError, Unsupported, error_response
from api.routes import files as files_api
from api.routes.files import PathError, clean_rel

queue_bp = Blueprint("queue", __name__)

MAX_QUEUE = 200
MAX_REPEAT = 50
META_TTL_S = 300.0
META_MISS_TTL_S = 30.0
CONFIG_TTL_S = 60.0

SETUP_SNIPPET = """[job_queue]
# Added for the Indus3D print queue. Restart Moonraker afterwards.
# Start the next queued job by hand (recommended: nothing detects that the bed is clear).
#automatic_transition: False
# Optional: load the first queued job when Moonraker starts.
#load_on_startup: False
# Optional: G-code run between two queued jobs.
#job_transition_gcode:
"""


class QueueUnavailable(Exception):
    """``[job_queue]`` is not configured in this Moonraker."""


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def summarize(jobs: List[dict], remaining_current_s: Optional[float], now: float) -> dict:
    """Totals and ETAs. Mutates each job with ``eta_ts`` (None once an unknown duration precedes it).

    ``finish_ts`` is None when nothing is queued or any job lacks an estimate, in which case
    ``finish_is_lower_bound`` says the time shown for the known jobs is a minimum.
    """
    total_s = total_mm = total_g = 0.0
    missing = 0
    cursor: Optional[float] = now + max(0.0, remaining_current_s or 0.0)
    for job in jobs:
        meta = job.get("meta") or {}
        est = meta.get("estimated_time")
        if isinstance(est, (int, float)) and est > 0:
            total_s += est
            cursor = cursor + est if cursor is not None else None
        else:
            missing += 1
            cursor = None
        job["eta_ts"] = cursor
        if isinstance(meta.get("filament_total"), (int, float)):
            total_mm += meta["filament_total"]
        if isinstance(meta.get("filament_weight_total"), (int, float)):
            total_g += meta["filament_weight_total"]
    return {
        "count": len(jobs), "time_s": round(total_s), "filament_mm": round(total_mm, 1), "filament_g": round(total_g, 1),
        "missing_meta": missing,
        "finish_ts": cursor if jobs and cursor is not None else None,
        "finish_is_lower_bound": bool(jobs) and missing > 0,
        "remaining_current_s": max(0.0, remaining_current_s or 0.0),
    }


def expand_filenames(filenames: List[str], repeat: int, interleave: bool = False) -> List[str]:
    """``[a, b]`` x3 -> ``a a a b b b`` (default) or ``a b a b a b`` (interleave)."""
    if interleave:
        return list(filenames) * repeat
    return [f for f in filenames for _ in range(repeat)]


def plan_reorder(current: List[dict], desired_ids: List[str]) -> dict:
    """How to turn the queue ``current`` ([{id, filename}]) into the order ``desired_ids``.

    Returns ``{"noop": True}``, ``{"jump": id}`` (one job moved to the front, ids preserved) or
    ``{"readd": [filenames], "remove": [ids]}``: everything after the longest unchanged prefix is added
    again in the wanted order and the old entries are removed.
    Raises ValueError when ``desired_ids`` is not a permutation of the current ids.
    """
    cur_ids = [j["id"] for j in current]
    if len(desired_ids) != len(cur_ids) or set(desired_ids) != set(cur_ids):
        raise ValueError("order does not match the queue")
    if desired_ids == cur_ids:
        return {"noop": True}
    if desired_ids[1:] == [i for i in cur_ids if i != desired_ids[0]]:
        return {"jump": desired_ids[0]}
    k = 0
    while k < len(cur_ids) and cur_ids[k] == desired_ids[k]:
        k += 1
    by_id = {j["id"]: j for j in current}
    return {"readd": [by_id[i]["filename"] for i in desired_ids[k:]], "remove": cur_ids[k:]}


# ── Simulator queue ───────────────────────────────────────────────────────────

class SimQueue:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.jobs: List[dict] = []
        self.state = "paused"

    def _view(self):
        now = time.time()
        return {"queue_state": self.state, "queued_jobs": [
            {"filename": j["filename"], "job_id": j["job_id"], "time_added": j["t"], "time_in_queue": now - j["t"]}
            for j in self.jobs]}

    def status(self):
        with self._lock:
            return self._view()

    def add(self, filenames):
        with self._lock:
            for f in filenames:
                self.jobs.append({"filename": f, "job_id": uuid.uuid4().hex[:8].upper(), "t": time.time()})
            return self._view()

    def remove(self, ids=None, all_=False):
        with self._lock:
            self.jobs = [] if all_ else [j for j in self.jobs if j["job_id"] not in set(ids or [])]
            return self._view()

    def pause(self):
        with self._lock:
            self.state = "paused"
            return self._view()

    def start(self):
        with self._lock:
            self.state = "ready"
            if self.jobs:
                self.jobs.pop(0)
            return self._view()

    def jump(self, job_id):
        with self._lock:
            hit = [j for j in self.jobs if j["job_id"] == job_id]
            if not hit:
                raise MoonrakerHTTPError(404, f"Job {job_id} not found")
            self.jobs.remove(hit[0])
            self.jobs.insert(0, hit[0])
            return self._view()


_sim = SimQueue()


# ── Moonraker access ──────────────────────────────────────────────────────────

class _Mr:
    def status(self):
        return mr_client.call("GET", "/server/job_queue/status", what="job queue")

    def add(self, filenames):
        return mr_client.call("POST", "/server/job_queue/job", json={"filenames": filenames, "reset": False}, what="job queue")

    def remove(self, ids=None, all_=False):
        params = {"all": "true"} if all_ else {"job_ids": ",".join(ids or [])}
        return mr_client.call("DELETE", "/server/job_queue/job", params=params, what="job queue")

    def pause(self):
        return mr_client.call("POST", "/server/job_queue/pause", what="job queue")

    def start(self):
        return mr_client.call("POST", "/server/job_queue/start", what="job queue")

    def jump(self, job_id):
        return mr_client.call("POST", "/server/job_queue/jump", params={"job_id": job_id}, what="job queue")


_mr = _Mr()


def _api():
    return _sim if files_api._is_simulator() else _mr


_cache_lock = threading.Lock()
_meta_cache: Dict[str, Tuple[float, dict]] = {}
_config_cache: dict = {"t": 0.0, "v": None}


def reset_cache() -> None:
    with _cache_lock:
        _meta_cache.clear()
        _config_cache.update(t=0.0, v=None)
    _sim.reset()


def _job_meta(filename: str) -> dict:
    now = time.monotonic()
    with _cache_lock:
        hit = _meta_cache.get(filename)
        if hit and now < hit[0]:
            return hit[1]
    try:
        raw = files_api.backend().metadata(filename)
        meta = files_api._meta_of(raw, files_api.parent_of(filename))
        ttl = META_TTL_S
    except (MoonrakerHTTPError, Unsupported):
        meta, ttl = {}, META_MISS_TTL_S
    # a transport failure (MoonrakerError) propagates: the status then reports 502 instead of caching blanks
    with _cache_lock:
        _meta_cache[filename] = (now + ttl, meta)
    return meta


def _transition_config() -> dict:
    """``{"automatic_transition": bool|None}`` from Moonraker's parsed config (best effort, cached)."""
    now = time.monotonic()
    with _cache_lock:
        if _config_cache["v"] is not None and now - _config_cache["t"] < CONFIG_TTL_S:
            return _config_cache["v"]
    value: dict = {"automatic_transition": None}
    if not files_api._is_simulator():
        try:
            cfg = mr_client.call("GET", "/server/config", what="config").get("config", {}).get("job_queue", {})
            auto = cfg.get("automatic_transition")
            value["automatic_transition"] = (str(auto).lower() == "true") if auto is not None else False
            value["load_on_startup"] = str(cfg.get("load_on_startup", "false")).lower() == "true"
        except (MoonrakerHTTPError, Unsupported):
            pass
    else:
        value["automatic_transition"] = False
    with _cache_lock:
        _config_cache.update(t=now, v=value)
    return value


def _print_progress() -> dict:
    import workers
    w = workers._active_worker
    latest = (getattr(w, "latest", None) or {}) if w else {}
    state = latest.get("print_state") or "standby"
    busy = state in ("printing", "paused")
    return {"state": state, "busy": busy, "filename": latest.get("filename") or "",
            "remaining_s": latest.get("time_remaining") if busy else 0, "progress": latest.get("progress")}


def _setup_info() -> dict:
    return {"snippet": SETUP_SNIPPET, "file": "moonraker.conf",
            "hint": "Add this section to moonraker.conf and restart Moonraker to enable the queue."}


def _guarded(fn):
    """Run ``fn(api)``; a missing job_queue component becomes QueueUnavailable."""
    try:
        return fn(_api())
    except Unsupported as e:
        raise QueueUnavailable(str(e)) from e


def _jobs_from(raw: dict) -> List[dict]:
    jobs = []
    for j in (raw or {}).get("queued_jobs", []) or []:
        fn = j.get("filename")
        if isinstance(fn, str) and j.get("job_id") is not None:
            jobs.append({"id": str(j["job_id"]), "filename": fn, "added": j.get("time_added"),
                         "in_queue": j.get("time_in_queue")})
    return jobs


def _fail(e: Exception):
    if isinstance(e, PathError):
        return jsonify({"error": str(e), "code": "bad_path"}), 400
    if isinstance(e, QueueUnavailable):
        return jsonify({"error": "The print queue is not enabled in Moonraker", "code": "queue_unavailable",
                        "unsupported": True, "setup": _setup_info()}), 501
    if isinstance(e, files_api.Refused):
        return files_api._fail(e)
    return error_response(e)


def _state_payload(raw: dict) -> dict:
    jobs = _jobs_from(raw)
    if len(jobs) > MAX_QUEUE:
        jobs = jobs[:MAX_QUEUE]
    uniq = sorted({j["filename"] for j in jobs})
    if uniq:
        with ThreadPoolExecutor(max_workers=4) as pool:
            metas = dict(zip(uniq, pool.map(_job_meta, uniq)))
    else:
        metas = {}
    for j in jobs:
        j["meta"] = metas.get(j["filename"], {})
        j["has_meta"] = j["meta"].get("estimated_time") is not None
        thumbs = j["meta"].get("thumbnails") or []
        j["thumb"] = min(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0) or 1e9)["path"] if thumbs else None
    prog = _print_progress()
    totals = summarize(jobs, prog["remaining_s"] if prog["busy"] else 0, time.time())
    cfg = _transition_config()
    auto = cfg.get("automatic_transition")
    return {"available": True, "state": raw.get("queue_state", "ready"), "jobs": jobs, "totals": totals, "print": prog,
            "automatic_transition": auto,
            "manual_start": not auto,
            "note": ("Jobs start automatically when a print finishes. Make sure the bed is cleared first."
                     if auto else
                     "Each job is started by hand: the next job is not loaded until you press Start, because "
                     "Indus3D can not tell whether the bed has been cleared."),
            "simulator": files_api._is_simulator()}


# ── Routes ────────────────────────────────────────────────────────────────────

@queue_bp.route("/status", methods=["GET"])
def status():
    try:
        try:
            raw = _guarded(lambda api: api.status())
        except QueueUnavailable:
            return jsonify({"available": False, "state": None, "jobs": [], "totals": summarize([], 0, time.time()),
                            "setup": _setup_info(), "print": _print_progress()})
        return jsonify(_state_payload(raw))
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise files_api.Refused(400, "JSON object body required", "bad_request")
    return data


@queue_bp.route("/add", methods=["POST"])
def add():
    try:
        data = _json()
        names = data.get("filenames")
        if not isinstance(names, list) or not names:
            raise files_api.Refused(400, "filenames must be a non-empty list", "bad_request")
        names = [clean_rel(n, allow_empty=False) for n in names]
        repeat = data.get("repeat", 1)
        if not isinstance(repeat, int) or isinstance(repeat, bool) or not 1 <= repeat <= MAX_REPEAT:
            raise files_api.Refused(400, f"repeat must be 1..{MAX_REPEAT}", "bad_request")
        position = data.get("position", "end")
        if position not in ("end", "front"):
            raise files_api.Refused(400, "position must be 'end' or 'front'", "bad_request")
        expanded = expand_filenames(names, repeat, bool(data.get("interleave")))
        if len(expanded) > MAX_QUEUE:
            raise files_api.Refused(400, f"At most {MAX_QUEUE} jobs per request", "too_many")
        before = _jobs_from(_guarded(lambda api: api.status()))
        if len(before) + len(expanded) > MAX_QUEUE * 2:
            raise files_api.Refused(409, "The queue is full", "queue_full")
        raw = _guarded(lambda api: api.add(expanded))
        if position == "front":
            new_ids = [j["id"] for j in _jobs_from(raw)][len(before):]
            for job_id in reversed(new_ids):
                raw = _guarded(lambda api, i=job_id: api.jump(i))
        return jsonify({"ok": True, "added": len(expanded), "state": raw.get("queue_state"),
                        "count": len(_jobs_from(raw))})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@queue_bp.route("/remove", methods=["POST"])
def remove():
    try:
        data = _json()
        if data.get("all") is True:
            raw = _guarded(lambda api: api.remove(all_=True))
        else:
            ids = data.get("ids")
            if not isinstance(ids, list) or not ids or not all(isinstance(i, (str, int)) and str(i).replace("-", "").isalnum() for i in ids):
                raise files_api.Refused(400, "ids must be a non-empty list of job ids (or all: true)", "bad_request")
            raw = _guarded(lambda api: api.remove([str(i) for i in ids]))
        return jsonify({"ok": True, "count": len(_jobs_from(raw)), "state": raw.get("queue_state")})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _simple(action: str):
    try:
        raw = _guarded(lambda api: getattr(api, action)())
        return jsonify({"ok": True, "state": raw.get("queue_state"), "count": len(_jobs_from(raw))})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@queue_bp.route("/pause", methods=["POST"])
def pause():
    return _simple("pause")


@queue_bp.route("/start", methods=["POST"])
def start():
    try:
        if _print_progress()["busy"]:
            raise files_api.Refused(409, "A print is already running; the queue continues when it finishes", "busy")
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return _simple("start")


@queue_bp.route("/jump", methods=["POST"])
def jump():
    try:
        job_id = _json().get("id")
        if not isinstance(job_id, (str, int)) or not str(job_id).replace("-", "").isalnum():
            raise files_api.Refused(400, "id required", "bad_request")
        raw = _guarded(lambda api: api.jump(str(job_id)))
        return jsonify({"ok": True, "count": len(_jobs_from(raw))})
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@queue_bp.route("/reorder", methods=["POST"])
def reorder():
    try:
        ids = _json().get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, (str, int)) for i in ids):
            raise files_api.Refused(400, "ids must be the full list of job ids in the wanted order", "bad_request")
        ids = [str(i) for i in ids]
        current = _jobs_from(_guarded(lambda api: api.status()))
        try:
            plan = plan_reorder(current, ids)
        except ValueError:
            raise files_api.Refused(409, "The queue changed; reload it and try again", "queue_changed")
        if plan.get("noop"):
            return jsonify({"ok": True, "method": "none"})
        if "jump" in plan:
            _guarded(lambda api: api.jump(plan["jump"]))
            return jsonify({"ok": True, "method": "jump"})
        _guarded(lambda api: api.add(plan["readd"]))
        try:
            _guarded(lambda api: api.remove(plan["remove"]))
        except MoonrakerHTTPError as e:
            if e.status != 404:                    # a job that already started is gone: fine
                raise
        return jsonify({"ok": True, "method": "readd", "moved": len(plan["readd"])})
    except Exception as e:  # noqa: BLE001
        return _fail(e)
