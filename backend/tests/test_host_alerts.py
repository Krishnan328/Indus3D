"""host_alerts plugin: edge-triggered notifications that re-arm when a condition clears, persistence across
restarts, quiet while Moonraker is unreachable or simulated, kill switch."""
import pytest

from api import system_host as sh
from plugins import host_alerts as ha


def alert(aid, source="host", severity="warning", notify=True):
    return {"id": aid, "severity": severity, "title": f"T {aid}", "detail": "d", "source": source, "notify": notify}


@pytest.fixture(autouse=True)
def not_sim(monkeypatch):
    import workers
    monkeypatch.setattr(workers, "_active_worker", None)


class Feed:
    """Scriptable alert source for HostAlerts."""
    def __init__(self):
        self.alerts, self.failed, self.error = [], set(), None

    def __call__(self):
        if self.error:
            raise self.error
        return self.alerts, self.failed


def make(tmp_path, feed=None):
    notes = []
    feed = feed or Feed()
    return ha.HostAlerts(notify=notes.append, state_path=tmp_path / "s.json", fetch=feed), notes, feed


def test_a_condition_notifies_once_while_it_lasts(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("throttle:undervoltage", severity="critical")]
    h.check()
    h.check()
    h.check()
    assert len(notes) == 1 and "T throttle:undervoltage" in notes[0] and notes[0].startswith("🛑")


def test_it_rearms_when_the_condition_clears(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("a")]
    h.check()
    feed.alerts = []
    h.check()
    assert h.status()["active"] == []
    feed.alerts = [alert("a")]
    h.check()
    assert len(notes) == 2


def test_each_new_condition_notifies_independently(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("a")]
    h.check()
    feed.alerts = [alert("a"), alert("b")]
    h.check()
    assert len(notes) == 2 and "T b" in notes[1]
    feed.alerts = [alert("b")]
    h.check()
    feed.alerts = [alert("a"), alert("b")]
    h.check()
    assert len(notes) == 3 and "T a" in notes[2]


def test_a_new_update_version_notifies_again_because_it_is_a_new_id(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("update:klipper:v1", "updates", "info")]
    h.check()
    feed.alerts = [alert("update:klipper:v2", "updates", "info")]
    h.check()
    assert len(notes) == 2


def test_alerts_without_notify_are_tracked_but_silent(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("throttle:history", severity="info", notify=False)]
    h.check()
    assert notes == [] and h.status()["active"] == ["throttle:history"]


def test_a_burst_of_new_alerts_is_summarised(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert(f"x{i}") for i in range(7)]
    h.check()
    assert len(notes) == ha.MAX_NOTES_PER_CHECK + 1 and "3 more alert(s)" in notes[-1]
    h.check()
    assert len(notes) == ha.MAX_NOTES_PER_CHECK + 1


def test_the_active_set_survives_a_restart(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("a")]
    h.check()
    h2, notes2, feed2 = make(tmp_path)
    feed2.alerts = [alert("a")]
    h2.check()
    assert notes2 == []                                  # no repeat after the backend restarts
    feed2.alerts = []
    h2.check()
    feed2.alerts = [alert("a")]
    h2.check()
    assert len(notes2) == 1


def test_unreachable_moonraker_is_not_an_alert_and_keeps_state(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("a")]
    h.check()
    feed.error = sh.Unreachable("Moonraker unreachable: refused")
    assert h.check() == [] and len(notes) == 1 and "unreachable" in h.status()["last_error"]
    assert h.status()["active"] == ["a"]
    feed.error = None
    h.check()
    assert len(notes) == 1                               # nothing re-announced when it comes back


def test_a_failed_section_does_not_make_its_alerts_look_cleared(tmp_path):
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("update:klipper:v2", "updates", "info"), alert("throttle:undervoltage", "host")]
    h.check()
    feed.alerts = [alert("throttle:undervoltage", "host")]          # updates section errored this time
    feed.failed = {"updates"}
    h.check()
    assert "update:klipper:v2" in h.status()["active"]
    feed.alerts, feed.failed = [alert("update:klipper:v2", "updates", "info"), alert("throttle:undervoltage", "host")], set()
    h.check()
    assert len(notes) == 2                                          # still just the two originals


def test_simulator_mode_never_notifies(tmp_path, monkeypatch):
    import workers

    class Sim:
        def inject_gcode(self, g):
            pass
    monkeypatch.setattr(workers, "_active_worker", Sim())
    h, notes, feed = make(tmp_path)
    feed.alerts = [alert("a")]
    assert h.check() == [] and notes == []


def test_end_to_end_with_a_faked_moonraker(tmp_path, monkeypatch):
    """The real fetch path: raw Moonraker sections -> compute_alerts -> notification."""
    raw = {
        "proc_stats": {"ok": True, "unsupported": False, "error": None, "data": {"throttled_state": {"bits": 1, "flags": []}}},
        "server_info": {"ok": True, "unsupported": False, "error": None,
                        "data": {"moonraker_version": "v0.9.3", "failed_components": ["x"]}},
        "updates": {"ok": False, "unsupported": True, "error": "n/a", "data": None},
        "announcements": {"ok": False, "unsupported": False, "error": "503", "data": None},
    }
    monkeypatch.setattr(sh, "fetch_sections", lambda names, use_cache=True: raw)
    notes = []
    h = ha.HostAlerts(notify=notes.append, state_path=tmp_path / "s.json")
    fresh = h.check()
    assert {a["id"] for a in fresh} == {"throttle:undervoltage", "component:x"}
    assert len(notes) == 2 and any("Under-voltage" in n for n in notes)
    h.check()
    assert len(notes) == 2
    assert h._fetch_alerts()[1] == {"announcements"}                # only the errored section counts as failed


def test_interval_and_kill_switch_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("INDUS3D_HOST_ALERTS_INTERVAL_S", "5")
    assert ha.interval_s() == ha.MIN_INTERVAL_S
    monkeypatch.setenv("INDUS3D_HOST_ALERTS_INTERVAL_S", "900")
    assert ha.interval_s() == 900
    monkeypatch.setenv("INDUS3D_HOST_ALERTS_INTERVAL_S", "soon")
    assert ha.interval_s() == ha.DEFAULT_INTERVAL_S
    monkeypatch.setenv("INDUS3D_HOST_ALERTS", "0")
    assert ha.enabled() is False


def test_the_poller_is_not_started_when_disabled(monkeypatch):
    started = []
    monkeypatch.setattr(ha._poller, "start", lambda: started.append(1))
    monkeypatch.setenv("INDUS3D_HOST_ALERTS", "0")
    ha._tick({}, None)
    assert started == []
    monkeypatch.setenv("INDUS3D_HOST_ALERTS", "1")
    ha._tick({}, None)
    assert started == [1]


def test_the_plugin_loads_and_exposes_its_status():
    from flask import Flask
    import plugins
    app = Flask(__name__)
    ha.register_routes(app)
    r = app.test_client().get("/api/v1/plugins/host_alerts")
    assert r.status_code == 200 and "active" in r.get_json()
    assert "host_alerts" in plugins.load_plugins(Flask(__name__)) or "host_alerts" in plugins._loaded
