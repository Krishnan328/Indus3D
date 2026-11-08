"""POST /api/v1/twin/exclude_object: validation, failure handling, notification only on success."""
import pytest

import workers
from api import moonraker_util as mu
from api.server import app
import core.notifications as notifications


class Resp:
    def __init__(self, ok=True, text=""):
        self.ok, self.text = ok, text


@pytest.fixture
def env(monkeypatch):
    state = {
        "scripts": [], "notes": [], "run": Resp(),
        "status": {
            "print_stats": {"state": "printing"},
            "exclude_object": {"objects": [{"name": "cube_1"}, {"name": "Part(2)"}], "excluded_objects": ["old_1"]},
        },
    }
    monkeypatch.setattr(workers, "_active_worker", None)

    def query(names):
        if isinstance(state["status"], Exception):
            raise state["status"]
        return state["status"]

    def run(script, timeout=10):
        state["scripts"].append(script)
        if isinstance(state["run"], Exception):
            raise state["run"]
        return state["run"]

    monkeypatch.setattr(mu, "query_objects", query)
    monkeypatch.setattr(mu, "run_script", run)
    monkeypatch.setattr(notifications, "notify_object_excluded",
                        lambda name, reason=None: state["notes"].append((name, reason)))
    state["client"] = app.test_client()
    state["post"] = lambda body: state["client"].post("/api/v1/twin/exclude_object", json=body)
    return state


def test_success_sends_one_command_and_one_notification(env):
    r = env["post"]({"name": "cube_1", "reason": "stringing"})
    assert r.status_code == 200 and r.get_json()["success"] is True
    assert env["scripts"] == ["EXCLUDE_OBJECT NAME=cube_1"]
    assert env["notes"] == [("cube_1", "stringing")]


def test_canonical_name_is_used(env):
    assert env["post"]({"name": "CUBE_1"}).status_code == 200
    assert env["scripts"] == ["EXCLUDE_OBJECT NAME=cube_1"]


@pytest.mark.parametrize("name", [
    "cube_1\nM112", "cube_1;M112", "cube_1\r\nG28", "a" * 129, "", "  ", "cube_1\n", "x#y", 'a"b',
    123, None, ["cube_1"], {"a": 1},
])
def test_injection_and_garbage_names_rejected(env, name):
    r = env["post"]({"name": name})
    assert r.status_code == 400
    assert env["scripts"] == [] and env["notes"] == []


def test_non_object_body_rejected(env):
    for body in (["cube_1"], "cube_1", 5):
        assert env["client"].post("/api/v1/twin/exclude_object", json=body).status_code == 400
    assert env["client"].post("/api/v1/twin/exclude_object", data="nope").status_code == 400
    assert env["scripts"] == []


def test_unknown_name_is_404_and_sends_nothing(env):
    r = env["post"]({"name": "ghost"})
    assert r.status_code == 404
    assert env["scripts"] == [] and env["notes"] == []


def test_already_excluded_is_idempotent(env):
    r = env["post"]({"name": "old_1"})
    assert r.status_code == 200 and r.get_json()["already_excluded"] is True
    env["status"]["exclude_object"]["objects"].append({"name": "old_1"})
    assert env["post"]({"name": "old_1"}).get_json()["already_excluded"] is True
    assert env["scripts"] == [] and env["notes"] == []


def test_no_active_print_is_refused(env):
    env["status"]["print_stats"]["state"] = "standby"
    assert env["post"]({"name": "cube_1"}).status_code == 409
    assert env["scripts"] == []


def test_klipper_refusal_is_an_error_and_not_notified(env):
    env["run"] = Resp(ok=False, text='{"error": "Unknown command"}')
    r = env["post"]({"name": "cube_1"})
    assert r.status_code == 422 and "refused" in r.get_json()["error"]
    assert env["notes"] == []


def test_moonraker_down_on_query_and_on_run(env):
    env["status"] = mu.MoonrakerError("Moonraker unreachable")
    assert env["post"]({"name": "cube_1"}).status_code == 502
    env["status"] = {"print_stats": {"state": "printing"},
                     "exclude_object": {"objects": [{"name": "cube_1"}], "excluded_objects": []}}
    env["run"] = mu.MoonrakerError("Moonraker unreachable")
    assert env["post"]({"name": "cube_1"}).status_code == 502
    assert env["notes"] == []


def test_reason_is_bounded_and_cleaned(env):
    env["post"]({"name": "cube_1", "reason": "bad\nline\x00" + "x" * 500})
    reason = env["notes"][0][1]
    assert len(reason) <= 200 and "\n" not in reason and "\x00" not in reason
    env["post"]({"name": "Part(2)", "reason": 42})
    assert env["notes"][1][1] == "Operator exclusion via Digital Twin"
    assert env["scripts"][1] == 'EXCLUDE_OBJECT NAME=Part(2)'


# ── simulator branch ───────────────────────────────────────────────────────────
class FakeSim:
    def __init__(self, state="printing", objects=("cube_1",)):
        self.latest = {"print_state": state}
        self.excluded_objects = set()
        self.gcodes = []
        self._objs = [{"name": n} for n in objects]

    def inject_gcode(self, g):
        self.gcodes.append(g)

    def _get_exclude_payload(self):
        return {"objects": self._objs, "excluded_objects": list(self.excluded_objects)}


def test_simulator_branch_validates_and_toggles(env, monkeypatch):
    sim = FakeSim()
    monkeypatch.setattr(workers, "_active_worker", sim)
    r = env["post"]({"name": "cube_1"})
    assert r.status_code == 200 and r.get_json()["sim"] is True
    assert sim.gcodes == ["TOGGLE_EXCLUDE_OBJECT NAME=cube_1"] and "cube_1" in sim.excluded_objects
    assert len(env["notes"]) == 1
    assert env["post"]({"name": "cube_1\nM112"}).status_code == 400
    assert env["post"]({"name": "ghost"}).status_code == 404
    assert len(sim.gcodes) == 1 and env["scripts"] == []


def test_simulator_refuses_when_idle(env, monkeypatch):
    sim = FakeSim(state="standby")
    monkeypatch.setattr(workers, "_active_worker", sim)
    assert env["post"]({"name": "cube_1"}).status_code == 409
    assert sim.gcodes == [] and env["notes"] == []
