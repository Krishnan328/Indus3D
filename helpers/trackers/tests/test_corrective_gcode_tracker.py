import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corrective_gcode_tracker as t  # noqa: E402


class Stub:
    """Tiny Indus3D stand-in; `routes` maps path -> (status, json)."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                status, body = outer.routes.get(self.path, (404, {}))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_POST(self):  # the tracker must never POST
                outer.requests.append(("POST", self.path, None))
                self.send_response(500)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def stub():
    made = []

    def make(routes):
        s = Stub(routes)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def routes(autopilot, state, log=None):
    return {
        t.HEALTH_PATH: (200, {"status": "ok"}),
        t.AUTOPILOT_PATH: (200, {"auto_pilot_enabled": autopilot}),
        t.STATE_PATH: (200, state),
        t.ACTION_LOG_PATH: (200, log if log is not None else []),
    }


def levels(rows):
    return {check: lvl for lvl, check, _ in rows}


def test_diagnose_flags_autopilot_off_while_printing(stub):
    s = stub(routes(False, {"print_state": "printing"}))
    rows = t.diagnose(t.make_getter(s.url, None), None, None)
    lv = levels(rows)
    assert lv["auto-pilot"] == t.FAIL
    assert lv["diagnosis"] == t.FAIL
    assert all(r[0] != "POST" for r in s.requests)


def test_diagnose_healthy(stub):
    state = {"print_state": "printing", "live_commands": [{"ts": 1, "text": "[QC] M221 S95"}],
             "quality": {"active": {"flow_pct": 95}, "corrections": [{"ts": 1, "type": "flow", "value": 95}]}}
    s = stub(routes(True, state, log=[{"id": 1}]))
    rows = t.diagnose(t.make_getter(s.url, None), None, None)
    assert t.FAIL not in {r[0] for r in rows}


def test_diagnose_backend_down():
    rows = t.diagnose(t.make_getter("http://127.0.0.1:1", None, 0.3), None, None)
    assert rows[0][0] == t.FAIL


def test_m221_contention_detected(stub, tmp_path):
    ini = tmp_path / "s.ini"
    ini.write_text("[features]\nenable_auto_flow = true\n")
    s = stub(routes(True, {"print_state": "printing"}))
    rows = t.diagnose(t.make_getter(s.url, None), None, ini)
    assert levels(rows)["M221 contention"] == t.WARN


def test_password_sent_as_bearer_only(stub, tmp_path):
    pw = tmp_path / "env"
    pw.write_text("OTHER=x\nINDUS3D_PASSWORD='s3cret'\n")
    s = stub(routes(True, {"print_state": "idle"}))
    get = t.make_getter(s.url, t.password_from_file(pw))
    get(t.AUTOPILOT_PATH)
    assert s.requests[-1][2] == "Bearer s3cret"


def test_follow_records_new_commands_once_and_never_the_password(stub, tmp_path):
    state = {"print_state": "printing",
             "live_commands": [{"ts": 5.0, "text": "[QC] M221 S97"}, {"ts": 6.0, "text": "[QC FAIL] M220 S80"}],
             "quality": {"corrections": [{"ts": 5.0, "type": "flow", "value": 97, "reason": "r"}]}}
    s = stub(routes(True, state))
    trail = t.Trail(tmp_path / "trail.jsonl")
    f = t.Follower(t.make_getter(s.url, "topsecret"), trail)
    f.poll_once()
    f.poll_once()  # same data again: no duplicates
    events = [json.loads(l) for l in (tmp_path / "trail.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in events]
    assert kinds.count("command") == 2 and kinds.count("correction") == 1
    assert [e for e in events if e["kind"] == "command"][1]["ok"] is False
    assert "topsecret" not in (tmp_path / "trail.jsonl").read_text()


def test_silence_warning_when_printing_with_autopilot_but_no_output(stub, tmp_path):
    s = stub(routes(True, {"print_state": "printing"}))
    clock = [1000.0]
    f = t.Follower(t.make_getter(s.url, None), t.Trail(tmp_path / "t.jsonl"), now=lambda: clock[0])
    f.poll_once()
    clock[0] += t.SILENCE_WARN_SECONDS + 5
    f.poll_once()
    f.poll_once()  # reported only once
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert kinds.count("silence") == 1


def test_summary(stub, tmp_path):
    p = tmp_path / "t.jsonl"
    tr = t.Trail(p)
    tr.write("command", text="[QC] M221 S97", ok=True)
    tr.write("command", text="[QC FAIL] M220 S80", ok=False)
    out = t.summarize(p)
    assert out["commands_by_type"] == {"M221": 1, "M220": 1}
    assert out["failed_commands"] == 1
