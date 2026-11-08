"""Tests for api/routes/files.py: path safety, root whitelist, read-only roots, confirmation gates,
busy refusal, unsupported endpoints, 502, and the simulator tree."""
import io
import json
import zipfile
from unittest import mock

import pytest
import requests

from api.routes import files as F


from mr_fakes import FakeMR, Resp, err, ok


@pytest.fixture
def client():
    from api.server import app
    from api import rate_limiter as rl
    rl._requests.clear(); rl._bans.clear(); rl._violations.clear()      # one process, one client IP: start each test fresh
    F.reset_cache()
    F._sim.reset()
    return app.test_client()


@pytest.fixture
def mr():
    fake = FakeMR()
    with mock.patch("api.mr_client.requests.request", side_effect=fake), \
            mock.patch.object(F, "_is_simulator", return_value=False), \
            mock.patch.object(F, "active_print", return_value=(False, "")):
        yield fake


def listing(dirs=(), files=()):
    return ok({"dirs": [{"dirname": d, "modified": 1, "size": 4096, "permissions": "rw"} for d in dirs],
               "files": [dict({"filename": f, "modified": 2, "size": 10, "permissions": "rw"}) for f in files],
               "disk_usage": {"total": 1000, "used": 250, "free": 750}, "root_info": {"name": "gcodes", "permissions": "rw"}})


# ── path helpers ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["../x", "a/../b", "..", "/etc/passwd", "a\\b", "a\x00b", "C:/x", "a/\x07b", "x" * 300, 5, None])
def test_clean_rel_rejects(bad):
    with pytest.raises(F.PathError):
        F.clean_rel(bad)


def test_clean_rel_normalises():
    assert F.clean_rel("a//b/./c/") == "a/b/c"
    assert F.clean_rel("") == ""
    assert F.clean_rel("...") == "..."          # a legal (odd) name, not a traversal
    with pytest.raises(F.PathError):
        F.clean_rel("", allow_empty=False)


@pytest.mark.parametrize("bad", ["", " a", "a ", "a/b", ".", "..", "a\\b", None])
def test_clean_name_rejects(bad):
    with pytest.raises(F.PathError):
        F.clean_name(bad)


def test_is_within():
    assert F.is_within("a/b", "a") and F.is_within("a", "a") and F.is_within("x", "")
    assert not F.is_within("ab", "a")


def test_mr_file_path_encodes_segments():
    assert F.mr_file_path("gcodes", "my dir/a#b.gcode") == "/server/files/gcodes/my%20dir/a%23b.gcode"


# ── roots ─────────────────────────────────────────────────────────────────────
def test_roots_whitelist_and_permissions(client, mr):
    r = client.get("/api/v1/files/roots").get_json()
    names = [x["name"] for x in r["roots"]]
    assert names == ["gcodes", "config", "config_examples", "logs", "shared"]
    by = {x["name"]: x for x in r["roots"]}
    assert by["config_examples"]["writable"] is False and by["logs"]["writable"] is False
    assert by["shared"]["custom"] is True and by["gcodes"]["writable"] is True


def test_unknown_root_is_rejected(client, mr):
    assert client.get("/api/v1/files/list?root=database").status_code == 400
    assert client.get("/api/v1/files/list?root=..").status_code == 400
    assert client.get("/api/v1/files/list?root=docs").status_code == 400     # whitelisted but Moonraker lacks it


@pytest.mark.parametrize("method,url,body", [
    ("get", "/api/v1/files/list?root=gcodes&path=../config", None),
    ("get", "/api/v1/files/list?root=gcodes&path=/etc", None),
    ("get", "/api/v1/files/list?root=gcodes&path=a%5Cb", None),
    ("get", "/api/v1/files/download?root=gcodes&path=../../etc/passwd", None),
    ("get", "/api/v1/files/text?root=config&path=a/../../x", None),
    ("get", "/api/v1/files/metadata?path=..%2Fx", None),
    ("put", "/api/v1/files/text", {"root": "config", "path": "../x", "content": "a"}),
    ("post", "/api/v1/files/mkdir", {"root": "gcodes", "path": "../x"}),
    ("post", "/api/v1/files/rename", {"root": "gcodes", "path": "a", "new_name": "../b"}),
    ("post", "/api/v1/files/rename", {"root": "gcodes", "path": "a", "new_name": "b/c"}),
    ("post", "/api/v1/files/move", {"root": "gcodes", "items": ["a"], "dest_dir": "../.."}),
    ("post", "/api/v1/files/move", {"root": "gcodes", "items": ["../a"], "dest_dir": ""}),
    ("post", "/api/v1/files/copy", {"root": "gcodes", "items": ["a"], "dest_dir": "/abs"}),
    ("post", "/api/v1/files/delete", {"root": "gcodes", "items": ["x/../../y"]}),
    ("post", "/api/v1/files/zip", {"root": "gcodes", "items": ["..\\x"]}),
    ("post", "/api/v1/files/thumbs", {"root": "gcodes", "items": [{"path": "../x.png"}]}),
])
def test_traversal_is_400_and_never_reaches_moonraker(client, mr, method, url, body):
    r = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert r.status_code == 400, r.get_data(as_text=True)
    assert r.get_json()["code"] in ("bad_path", "bad_root") or "error" in r.get_json()
    assert mr.writes() == []
    assert all(c[1] in ("/server/files/roots",) for c in mr.calls)


def test_upload_traversal_filename(client, mr):
    r = client.post("/api/v1/files/upload", data={"root": "gcodes", "path": "..", "file": (io.BytesIO(b"x"), "a.gcode")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/api/v1/files/upload", data={"root": "gcodes", "path": "", "file": (io.BytesIO(b"x"), "../a.gcode")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert mr.writes() == []


# ── listing ───────────────────────────────────────────────────────────────────
def test_list_normalises_metadata_thumbnails_and_disk(client, mr):
    mr.routes[("GET", "/server/files/directory")] = ok({
        "dirs": [{"dirname": "cal", "modified": 1, "size": 0, "permissions": "rw"}],
        "files": [{"filename": "a.gcode", "modified": 5, "size": 99, "permissions": "rw", "slicer": "Cura",
                   "estimated_time": 600, "layer_height": 0.2, "ignored_key": 1,
                   "thumbnails": [{"width": 32, "height": 32, "size": 10, "relative_path": ".thumbs/a-32x32.png"}]},
                  {"filename": "b.gcode", "modified": 6, "size": 5, "permissions": "rw"}],
        "disk_usage": {"total": 1000, "used": 950, "free": 50}, "root_info": {"name": "gcodes", "permissions": "rw"}})
    r = client.get("/api/v1/files/list?root=gcodes&path=sub").get_json()
    assert r["dirs"][0]["path"] == "sub/cal"
    a, b = r["files"]
    assert a["path"] == "sub/a.gcode" and a["has_meta"] is True and "ignored_key" not in a["meta"]
    assert a["meta"]["thumbnails"][0]["path"] == "sub/.thumbs/a-32x32.png"
    assert b["has_meta"] is False
    assert r["disk_usage"]["percent"] == 95.0
    call = [c for c in mr.calls if c[1] == "/server/files/directory"][0]
    assert call[2]["params"] == {"path": "gcodes/sub", "extended": "true"}


def test_list_extended_only_for_gcodes(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing(files=["printer.cfg"])
    client.get("/api/v1/files/list?root=config")
    call = [c for c in mr.calls if c[1] == "/server/files/directory"][0]
    assert "extended" not in call[2]["params"]


def test_moonraker_unreachable_is_502(client):
    F.reset_cache()
    with mock.patch("api.mr_client.requests.request", side_effect=requests.ConnectionError("down")), \
            mock.patch.object(F, "_is_simulator", return_value=False):
        r = client.get("/api/v1/files/list?root=gcodes")
    assert r.status_code == 502 and r.get_json()["code"] == "moonraker_unreachable"


def test_missing_endpoint_is_unsupported(client, mr):
    mr.routes[("GET", "/server/files/directory")] = err(404, "Not Found")
    r = client.get("/api/v1/files/list?root=gcodes")
    assert r.status_code == 501 and r.get_json()["unsupported"] is True


def test_missing_file_is_a_normal_404(client, mr):
    mr.routes[("GET", "/server/files/directory")] = err(404, "Directory /x/y does not exist")
    r = client.get("/api/v1/files/list?root=gcodes&path=y")
    assert r.status_code == 404 and "unsupported" not in r.get_json()


def test_405_is_unsupported(client, mr):
    mr.routes[("POST", "/server/files/zip")] = err(405, "Method Not Allowed")
    r = client.post("/api/v1/files/zip", json={"root": "gcodes", "items": ["a.gcode"]})
    assert r.status_code == 501 and r.get_json()["code"] == "unsupported"
    assert [c for c in mr.writes() if c[1] != "/server/files/zip"] == []


# ── read-only roots ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("method,url,body", [
    ("post", "/api/v1/files/mkdir", {"root": "config_examples", "path": "x"}),
    ("post", "/api/v1/files/rename", {"root": "logs", "path": "a.log", "new_name": "b.log"}),
    ("post", "/api/v1/files/move", {"root": "logs", "items": ["a.log"], "dest_dir": ""}),
    ("post", "/api/v1/files/copy", {"root": "gcodes", "items": ["a.gcode"], "dest_root": "config_examples", "dest_dir": ""}),
    ("post", "/api/v1/files/delete", {"root": "config_examples", "items": ["a.cfg"]}),
    ("put", "/api/v1/files/text", {"root": "logs", "path": "klippy.log", "content": "x"}),
])
def test_read_only_roots_refuse_writes(client, mr, method, url, body):
    r = getattr(client, method)(url, json=body)
    assert r.status_code == 403 and r.get_json()["code"] == "read_only"
    assert mr.writes() == []


def test_read_only_root_upload(client, mr):
    r = client.post("/api/v1/files/upload", data={"root": "logs", "path": "", "file": (io.BytesIO(b"x"), "a.log")},
                    content_type="multipart/form-data")
    assert r.status_code == 403 and mr.writes() == []


def test_read_only_root_can_still_be_read_and_downloaded(client, mr):
    mr.routes[("GET", "/server/files/logs/klippy.log")] = Resp(200, content=b"hello", headers={"Content-Length": "5"})
    r = client.get("/api/v1/files/download?root=logs&path=klippy.log")
    assert r.status_code == 200 and r.data == b"hello"
    assert "attachment" in r.headers["Content-Disposition"]


# ── delete: confirmation gate, busy refusal ───────────────────────────────────
def _delete_routes(mr, parent_dirs=("proj",), inner=None):
    def directory(kw):
        path = kw["params"]["path"]
        if path == "gcodes":
            return listing(dirs=parent_dirs, files=["a.gcode"])
        if path == "gcodes/proj":
            return inner if inner is not None else listing(files=["x.gcode"])
        return listing()
    mr.routes[("GET", "/server/files/directory")] = directory
    mr.routes[("DELETE", "/server/files/directory")] = ok({"action": "delete_dir"})
    mr.routes[("DELETE", "/server/files/gcodes/a.gcode")] = ok({"action": "delete_file"})


def test_delete_nonempty_folder_needs_confirmation(client, mr):
    _delete_routes(mr)
    r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["a.gcode", "proj"]})
    assert r.status_code == 409 and r.get_json()["code"] == "confirmation_required"
    assert r.get_json()["needs_confirmation"] == ["proj"]
    assert mr.writes() == []                              # nothing was deleted, not even the plain file
    r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["proj"], "confirmed": "yes"})
    assert r.status_code == 409 and mr.writes() == []     # only the boolean true counts


def test_delete_confirmed_forces_folder(client, mr):
    _delete_routes(mr)
    r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["a.gcode", "proj"], "confirmed": True})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    methods = [(c[0], c[1], c[2].get("params")) for c in mr.writes()]
    assert ("DELETE", "/server/files/gcodes/a.gcode", None) in methods
    assert ("DELETE", "/server/files/directory", {"path": "gcodes/proj", "force": "true"}) in methods


def test_delete_empty_folder_needs_no_confirmation(client, mr):
    _delete_routes(mr, inner=listing())
    r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["proj"]})
    assert r.status_code == 200
    assert [c[2]["params"] for c in mr.writes()] == [{"path": "gcodes/proj", "force": "false"}]


def test_delete_active_print_file_refused(client, mr):
    _delete_routes(mr)
    with mock.patch.object(F, "active_print", return_value=(True, "proj/x.gcode")):
        r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["proj"], "confirmed": True})
        assert r.status_code == 409 and r.get_json()["code"] == "busy"
        r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["proj/x.gcode"]})
        assert r.status_code == 409
        r = client.post("/api/v1/files/rename", json={"root": "gcodes", "path": "proj/x.gcode", "new_name": "y.gcode"})
        assert r.status_code == 409
        r = client.post("/api/v1/files/move", json={"root": "gcodes", "items": ["proj"], "dest_dir": ""})
        assert r.status_code == 409
        # unrelated file is fine
        r = client.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["a.gcode"]})
        assert r.status_code == 200


def test_upload_over_active_file_refused(client, mr):
    with mock.patch.object(F, "active_print", return_value=(True, "a.gcode")):
        r = client.post("/api/v1/files/upload", data={"root": "gcodes", "path": "", "overwrite": "1",
                                                      "file": (io.BytesIO(b"x"), "a.gcode")},
                        content_type="multipart/form-data")
    assert r.status_code == 409 and mr.writes() == []


def test_config_changes_blocked_while_printing(client, mr):
    with mock.patch.object(F, "active_print", return_value=(True, "a.gcode")):
        for method, url, body in [
            ("put", "/api/v1/files/text", {"root": "config", "path": "printer.cfg", "content": "x"}),
            ("post", "/api/v1/files/delete", {"root": "config", "items": ["old.cfg"]}),
            ("post", "/api/v1/files/mkdir", {"root": "config", "path": "n"}),
            ("post", "/api/v1/files/rename", {"root": "config", "path": "a.cfg", "new_name": "b.cfg"}),
        ]:
            r = getattr(client, method)(url, json=body)
            assert r.status_code == 409 and r.get_json()["code"] == "busy", url
        # gcodes housekeeping is still allowed
        mr.routes[("POST", "/server/files/directory")] = ok({"action": "create_dir"})
        assert client.post("/api/v1/files/mkdir", json={"root": "gcodes", "path": "n"}).status_code == 200
    assert not [c for c in mr.writes() if "config" in json.dumps(c[2].get("json") or {}) or "config" in c[1]]


# ── move / copy / rename ──────────────────────────────────────────────────────
def test_move_conflict_needs_overwrite(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing(files=["a.gcode"], dirs=["arch"])
    mr.routes[("POST", "/server/files/move")] = ok({"action": "move_file"})
    body = {"root": "gcodes", "items": ["sub/a.gcode"], "dest_dir": ""}
    r = client.post("/api/v1/files/move", json=body)
    assert r.status_code == 409 and r.get_json()["code"] == "exists" and r.get_json()["conflicts"] == ["a.gcode"]
    assert mr.writes() == []
    r = client.post("/api/v1/files/move", json=dict(body, overwrite=True))
    assert r.status_code == 200
    assert mr.writes()[0][2]["json"] == {"source": "gcodes/sub/a.gcode", "dest": "gcodes/a.gcode"}


def test_move_and_copy_across_roots_and_into_itself(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing()
    mr.routes[("POST", "/server/files/copy")] = ok({"action": "create_file"})
    mr.routes[("POST", "/server/files/move")] = ok({"action": "move_file"})
    r = client.post("/api/v1/files/copy", json={"root": "gcodes", "items": ["a.gcode", "b.gcode"], "dest_root": "config", "dest_dir": "x"})
    assert r.status_code == 200
    assert [c[2]["json"]["dest"] for c in mr.writes()] == ["config/x/a.gcode", "config/x/b.gcode"]
    r = client.post("/api/v1/files/move", json={"root": "gcodes", "items": ["a"], "dest_dir": "a/b"})
    assert r.status_code == 400 and r.get_json()["code"] == "into_itself"
    r = client.post("/api/v1/files/move", json={"root": "gcodes", "items": ["x/a"], "dest_dir": "x"})
    assert r.status_code == 400 and r.get_json()["code"] == "no_change"


def test_rename_conflict_and_success(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing(files=["a.gcode", "b.gcode"])
    mr.routes[("POST", "/server/files/move")] = ok({"action": "move_file"})
    assert client.post("/api/v1/files/rename", json={"root": "gcodes", "path": "a.gcode", "new_name": "b.gcode"}).status_code == 409
    r = client.post("/api/v1/files/rename", json={"root": "gcodes", "path": "a.gcode", "new_name": "c.gcode"})
    assert r.status_code == 200 and r.get_json()["path"] == "c.gcode"


# ── text editor routes ────────────────────────────────────────────────────────
def test_text_read_and_limits(client, mr):
    mr.routes[("GET", "/server/files/config/printer.cfg")] = Resp(200, content="[printer]\n".encode())
    mr.routes[("GET", "/server/files/directory")] = listing(files=["printer.cfg"])
    r = client.get("/api/v1/files/text?root=config&path=printer.cfg").get_json()
    assert r["content"] == "[printer]\n" and r["writable"] is True and r["modified"] == 2 and r["locked"] is False
    mr.routes[("GET", "/server/files/config/big.cfg")] = Resp(200, content=b"x" * (F.MAX_TEXT_BYTES + 5))
    assert client.get("/api/v1/files/text?root=config&path=big.cfg").status_code == 413
    mr.routes[("GET", "/server/files/config/bin.cfg")] = Resp(200, content=b"ab\x00cd")
    assert client.get("/api/v1/files/text?root=config&path=bin.cfg").status_code == 415


def test_text_write_uploads_via_moonraker_and_records_history(client, mr):
    mr.routes[("GET", "/server/files/config/printer.cfg")] = Resp(200, content=b"a: 1\n")
    mr.routes[("GET", "/server/files/directory")] = listing(files=["printer.cfg"])
    sent = {}

    def upload(kw):
        sent["body"] = b"".join(kw["data"])
        sent["headers"] = kw["headers"]
        return ok({"item": {"path": "printer.cfg", "root": "config"}})
    mr.routes[("POST", "/server/files/upload")] = upload
    with mock.patch("db.models.get_connection") as conn:
        r = client.put("/api/v1/files/text", json={"root": "config", "path": "printer.cfg", "content": "a: 2\n",
                                                   "expected_modified": 2})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert b'name="root"' in sent["body"] and b"config" in sent["body"] and b"a: 2\n" in sent["body"]
    assert b'filename="printer.cfg"' in sent["body"]
    assert int(sent["headers"]["Content-Length"]) == len(sent["body"])
    diff = conn.return_value.execute.call_args[0][1][3]
    assert "-a: 1" in diff and "+a: 2" in diff


def test_text_write_in_subfolder_sends_path_field(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing()
    captured = {}
    mr.routes[("POST", "/server/files/upload")] = lambda kw: captured.update(body=b"".join(kw["data"])) or ok({})
    client.put("/api/v1/files/text", json={"root": "gcodes", "path": "sub/n.txt", "content": "hi"})
    assert b'name="path"\r\n\r\nsub\r\n' in captured["body"]


def test_text_write_conflict_and_size(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing(files=["printer.cfg"])
    mr.routes[("POST", "/server/files/upload")] = ok({})
    r = client.put("/api/v1/files/text", json={"root": "config", "path": "printer.cfg", "content": "x", "expected_modified": 1})
    assert r.status_code == 409 and r.get_json()["code"] == "conflict"
    assert mr.writes() == []
    r = client.put("/api/v1/files/text", json={"root": "config", "path": "printer.cfg", "content": "x" * (F.MAX_TEXT_BYTES + 1)})
    assert r.status_code == 413
    with mock.patch("db.models.get_connection"):
        r = client.put("/api/v1/files/text", json={"root": "config", "path": "printer.cfg", "content": "x", "expected_modified": 1, "force": True})
    assert r.status_code == 200


# ── upload / zip / download ───────────────────────────────────────────────────
def test_upload_streams_to_moonraker(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing()
    got = {}
    mr.routes[("POST", "/server/files/upload")] = lambda kw: got.update(body=b"".join(kw["data"]), h=kw["headers"]) or ok({})
    r = client.post("/api/v1/files/upload", data={"root": "gcodes", "path": "sub", "file": (io.BytesIO(b"G28\n" * 10), "x.gcode")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["path"] == "sub/x.gcode"
    assert got["body"].count(b"G28\n") == 10 and int(got["h"]["Content-Length"]) == len(got["body"])
    assert b'name="path"\r\n\r\nsub\r\n' in got["body"]


def test_upload_existing_file_needs_overwrite_and_size_limit(client, mr):
    mr.routes[("GET", "/server/files/directory")] = listing(files=["x.gcode"])
    mr.routes[("POST", "/server/files/upload")] = ok({})
    data = {"root": "gcodes", "path": "", "file": (io.BytesIO(b"abc"), "x.gcode")}
    r = client.post("/api/v1/files/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 409 and r.get_json()["code"] == "exists"
    with mock.patch.object(F, "MAX_UPLOAD_BYTES", 2):
        r = client.post("/api/v1/files/upload", data={"root": "gcodes", "path": "", "overwrite": "1",
                                                      "file": (io.BytesIO(b"abc"), "x.gcode")},
                        content_type="multipart/form-data")
    assert r.status_code == 413 and mr.writes() == []


def test_zip_builds_streams_and_removes_temp_archive(client, mr):
    mr.routes[("POST", "/server/files/zip")] = ok({"destination": {}})
    mr.routes[("DELETE", "/server/files/gcodes/.indus3d-zip")] = None

    def route(method, path, kw):
        return None
    created = {}

    def zip_(kw):
        created["dest"] = kw["json"]["dest"]
        mr.routes[("GET", "/server/files/" + created["dest"])] = Resp(200, content=b"PK-fake-zip")
        mr.routes[("DELETE", "/server/files/" + created["dest"])] = ok({"action": "delete_file"})
        return ok({"destination": {}})
    mr.routes[("POST", "/server/files/zip")] = zip_
    r = client.post("/api/v1/files/zip", json={"root": "gcodes", "items": ["a.gcode", "sub"]})
    assert r.status_code == 200 and r.data == b"PK-fake-zip" and r.mimetype == "application/zip"
    assert created["dest"].startswith("gcodes/.indus3d-zip-")
    assert mr.calls[-1][0] == "DELETE" and mr.calls[-1][1].endswith(".zip")           # temp archive removed
    assert [c for c in mr.calls if c[1] == "/server/files/zip"][0][2]["json"]["items"] == ["gcodes/a.gcode", "gcodes/sub"]


def test_zip_from_read_only_root_builds_in_writable_root(client, mr):
    dests = []
    mr.routes[("POST", "/server/files/zip")] = lambda kw: dests.append(kw["json"]["dest"]) or ok({})
    client.post("/api/v1/files/zip", json={"root": "logs", "items": ["klippy.log"]})
    assert dests and dests[0].startswith("gcodes/")


def test_download_forces_active_content_to_attachment(client, mr):
    mr.routes[("GET", "/server/files/docs/x.html")] = Resp(200, content=b"<script>1</script>")
    mr.routes[("GET", "/server/files/gcodes/p.png")] = Resp(200, content=b"\x89PNG")
    mr.routes[("GET", "/server/files/gcodes/n.txt")] = Resp(200, content=b"hi")
    mr.routes[("GET", "/server/files/roots")] = ok([{"name": "gcodes", "permissions": "rw"}, {"name": "docs", "permissions": "r"}])
    r = client.get("/api/v1/files/download?root=docs&path=x.html&inline=1")      # shown as inert text, never as HTML
    r.get_data()
    assert r.mimetype == "text/plain" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Content-Security-Policy"] == "sandbox"
    r = client.get("/api/v1/files/download?root=docs&path=x.html")
    r.get_data()
    assert r.headers["Content-Disposition"].startswith("attachment")
    r = client.get("/api/v1/files/download?root=gcodes&path=p.png&inline=1")
    r.get_data()
    assert r.headers["Content-Disposition"].startswith("inline") and r.mimetype == "image/png"
    r = client.get("/api/v1/files/download?root=gcodes&path=n.txt&inline=1")
    r.get_data()
    assert r.mimetype == "text/plain" and r.headers["Content-Disposition"].startswith("inline")


def test_download_passes_range(client, mr):
    seen = {}
    mr.routes[("GET", "/server/files/gcodes/v.mp4")] = lambda kw: seen.update(h=kw.get("headers")) or Resp(
        206, content=b"ab", headers={"Content-Range": "bytes 0-1/10", "Content-Length": "2"})
    r = client.get("/api/v1/files/download?root=gcodes&path=v.mp4&inline=1", headers={"Range": "bytes=0-1"})
    r.get_data()
    assert r.status_code == 206 and seen["h"] == {"Range": "bytes=0-1"} and r.headers["Content-Range"] == "bytes 0-1/10"


def test_thumbs_batch_is_one_request_and_cached(client, mr):
    mr.routes[("GET", "/server/files/gcodes/.thumbs/a.png")] = Resp(200, content=b"\x89PNGdata")
    items = [{"path": ".thumbs/a.png", "v": 1}, {"path": ".thumbs/missing.png", "v": 1}]
    r = client.post("/api/v1/files/thumbs", json={"root": "gcodes", "items": items}).get_json()
    assert r["thumbs"][".thumbs/a.png"].startswith("data:image/png;base64,")
    assert r["thumbs"][".thumbs/missing.png"] is None
    before = len(mr.calls)
    client.post("/api/v1/files/thumbs", json={"root": "gcodes", "items": items})
    assert len(mr.calls) == before + 0 or len([c for c in mr.calls[before:] if "a.png" in c[1]]) == 0
    assert client.post("/api/v1/files/thumbs", json={"root": "gcodes", "items": [{"path": "a.txt"}] * 100}).status_code == 400


def test_tree_flat_listing(client, mr):
    mr.routes[("GET", "/server/files/list")] = ok([{"path": "a.gcode", "size": 1, "modified": 2}, {"path": "../bad", "size": 1}])
    r = client.get("/api/v1/files/tree?root=gcodes").get_json()
    assert [f["path"] for f in r["files"]] == ["a.gcode"]


def test_metadata_and_metascan(client, mr):
    mr.routes[("GET", "/server/files/metadata")] = ok({"filename": "sub/a.gcode", "slicer": "Cura", "estimated_time": 5,
                                                       "thumbnails": [{"relative_path": ".thumbs/a.png", "width": 1, "height": 1, "size": 1}]})
    mr.routes[("POST", "/server/files/metascan")] = ok({"filename": "sub/a.gcode", "slicer": "Cura", "estimated_time": 5})
    m = client.get("/api/v1/files/metadata?path=sub/a.gcode").get_json()
    assert m["meta"]["thumbnails"][0]["path"] == "sub/.thumbs/a.png"
    r = client.post("/api/v1/files/metascan", json={"path": "sub/a.gcode"}).get_json()
    assert r["ok"] and r["meta"]["slicer"] == "Cura"


def test_mkdir_posts_json_path(client, mr):
    mr.routes[("POST", "/server/files/directory")] = ok({"action": "create_dir"})
    assert client.post("/api/v1/files/mkdir", json={"root": "gcodes", "path": "a/b"}).status_code == 200
    assert mr.writes()[0][2]["json"] == {"path": "gcodes/a/b"}


# ── simulator ─────────────────────────────────────────────────────────────────
@pytest.fixture
def sim(client):
    with mock.patch.object(F, "_is_simulator", return_value=True), \
            mock.patch.object(F, "active_print", return_value=(False, "")), \
            mock.patch("api.mr_client.requests.request", side_effect=AssertionError("simulator must not call Moonraker")):
        yield client


def test_sim_roots_and_listing(sim):
    r = sim.get("/api/v1/files/roots").get_json()
    assert r["simulator"] is True and [x["name"] for x in r["roots"]][:2] == ["gcodes", "config"]
    ls = sim.get("/api/v1/files/list?root=gcodes").get_json()
    assert [d["name"] for d in ls["dirs"]] == ["archive", "calibration"]
    benchy = [f for f in ls["files"] if f["name"] == "benchy.gcode"][0]
    assert benchy["has_meta"] and benchy["meta"]["thumbnails"][0]["path"] == ".thumbs/benchy-1x1.png"
    assert ls["disk_usage"]["percent"] == 25.0
    t = sim.post("/api/v1/files/thumbs", json={"root": "gcodes", "items": [{"path": ".thumbs/benchy-1x1.png"}]}).get_json()
    assert t["thumbs"][".thumbs/benchy-1x1.png"].startswith("data:image/png")


def test_sim_crud_roundtrip(sim):
    assert sim.post("/api/v1/files/mkdir", json={"root": "gcodes", "path": "new/deep"}).status_code == 200
    assert sim.post("/api/v1/files/mkdir", json={"root": "gcodes", "path": "new"}).status_code == 409
    up = sim.post("/api/v1/files/upload", data={"root": "gcodes", "path": "new", "file": (io.BytesIO(b"G1 X1\n"), "t.gcode")},
                  content_type="multipart/form-data")
    assert up.status_code == 200
    assert sim.post("/api/v1/files/rename", json={"root": "gcodes", "path": "new/t.gcode", "new_name": "u.gcode"}).status_code == 200
    assert sim.post("/api/v1/files/copy", json={"root": "gcodes", "items": ["new/u.gcode"], "dest_dir": "archive"}).status_code == 200
    assert sim.get("/api/v1/files/download?root=gcodes&path=archive/u.gcode").data == b"G1 X1\n"
    # folder with content needs confirmation, then goes away with everything in it
    r = sim.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["new"]})
    assert r.status_code == 409 and r.get_json()["code"] == "confirmation_required"
    assert sim.post("/api/v1/files/delete", json={"root": "gcodes", "items": ["new"], "confirmed": True}).status_code == 200
    assert sim.get("/api/v1/files/list?root=gcodes&path=new").status_code == 404
    flat = [f["path"] for f in sim.get("/api/v1/files/tree?root=gcodes").get_json()["files"]]
    assert "archive/u.gcode" in flat and not any(p.startswith("new/") for p in flat)


def test_sim_text_and_read_only(sim):
    r = sim.get("/api/v1/files/text?root=config&path=printer.cfg").get_json()
    assert "[printer]" in r["content"]
    with mock.patch("db.models.get_connection"):
        w = sim.put("/api/v1/files/text", json={"root": "config", "path": "printer.cfg", "content": "[printer]\nx: 1\n",
                                                "expected_modified": r["modified"]})
    assert w.status_code == 200
    assert "x: 1" in sim.get("/api/v1/files/text?root=config&path=printer.cfg").get_json()["content"]
    assert sim.put("/api/v1/files/text", json={"root": "docs", "path": "README.md", "content": "x"}).status_code == 403
    assert sim.post("/api/v1/files/delete", json={"root": "logs", "items": ["klippy.log"]}).status_code == 403


def test_sim_zip(sim):
    r = sim.post("/api/v1/files/zip", json={"root": "gcodes", "items": ["calibration"]})
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ["calibration/flow_cube.gcode", "calibration/pa_test.gcode"]


def test_legacy_routes_still_registered(client):
    rules = {r.rule for r in client.application.url_map.iter_rules()}
    assert {"/api/v1/printer/files/list", "/api/v1/printer/files/gcodes/<path:filename>",
            "/api/v1/printer/config/<path:filename>", "/api/v1/print/upload"} <= rules
