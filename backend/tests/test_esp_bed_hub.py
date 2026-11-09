"""esp_bed_hub: daemon polling, telemetry_samples storage, crash handling, command hold, actions, routes."""
import sqlite3
import time

import pytest

from plugins import esp_bed_hub as eh


def sample(update=1000.0, **over):
    d = {"bed_accel": {"x_mg": -300, "y_mg": -400, "z_mg": -850, "jerk_mg": 7},
         "chamber": {"temp_c": 26.5, "humidity_pct": 44.0, "pressure_hpa": 1007.0},
         "crash_detected": False, "crash_threshold_mg": 2000, "uptime_sec": 5,
         "connected": True, "age_s": 0.3, "last_update": update, "daemon": {"last_error": None, "last_crash": None}}
    d.update(over)
    return d


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    return lambda: sqlite3.connect(path)


def make(db, payload=None, **kw):
    payload = payload if payload is not None else sample()
    notes, audits = [], []
    h = eh.EspHub(url="http://hub", fetch=lambda u: payload() if callable(payload) else dict(payload),
                  notify=notes.append, store=eh.TelemetryStore(connect=db, retention_days=7),
                  audit=lambda *a: audits.append(a), **kw)
    h.notes, h.audits = notes, audits
    return h


def rows(db):
    c = db()
    try:
        return c.execute("SELECT * FROM telemetry_samples ORDER BY id").fetchall()
    finally:
        c.close()


# ── storage ──────────────────────────────────────────────────────────────────
def test_samples_are_batched_then_written_with_the_specified_columns(db):
    st = eh.TelemetryStore(connect=db)
    t0 = time.time()
    for i in range(eh.FLUSH_EVERY_N - 1):
        st.add(t0 + i, sample())
    with pytest.raises(sqlite3.OperationalError):
        rows(db)                                                     # nothing written yet: no table either
    st.add(t0 + 40, sample())                                        # the 30th row triggers the flush
    got = rows(db)
    assert len(got) == eh.FLUSH_EVERY_N
    c = db()
    cols = [r[1] for r in c.execute("PRAGMA table_info(telemetry_samples)")]
    c.close()
    assert cols == ["id", *eh.COLUMNS]
    first = dict(zip(cols, got[0]))
    assert first["chamber_temp_c"] == 26.5 and first["bed_accel_y_mg"] == -400 and first["bed_jerk_mg"] == 7
    assert first["crash_detected"] == 0 and first["timestamp_utc"].endswith("+00:00")


def test_missing_chamber_is_stored_as_null_not_zero(db):
    st = eh.TelemetryStore(connect=db)
    st.add(time.time(), sample(chamber=None), force_flush=True)
    r = rows(db)[0]
    assert r[2] is None and r[3] is None and r[4] is None


def test_retention_prunes_old_rows_and_flush_errors_keep_the_buffer(db):
    st = eh.TelemetryStore(connect=db, retention_days=1)
    now = time.time()
    st.add(now - 3 * 86400, sample(), force_flush=True)
    st.add(now, sample(), force_flush=True)
    assert len(rows(db)) == 1                                        # the 3-day-old row is gone

    def boom():
        raise sqlite3.OperationalError("disk full")
    bad = eh.TelemetryStore(connect=boom)
    bad.add(now, sample(), force_flush=True)
    assert len(bad.buffer) == 1 and "disk full" in bad.last_error


def test_disabled_store_writes_nothing(db):
    st = eh.TelemetryStore(connect=db, enabled=False)
    st.add(time.time(), sample(), force_flush=True)
    with pytest.raises(sqlite3.OperationalError):
        rows(db)


def test_recent_thins_to_the_limit(db):
    st = eh.TelemetryStore(connect=db)
    now = time.time()
    for i in range(300):
        st.add(now - 300 + i, sample(), force_flush=(i == 299))
    got = st.recent(minutes=10, limit=50)
    assert 40 <= len(got) <= 50 and got == sorted(got, key=lambda r: r["timestamp_utc"])


# ── polling ──────────────────────────────────────────────────────────────────
def test_each_new_daemon_sample_is_stored_once(db):
    p = {"d": sample(update=1.0)}
    h = make(db, lambda: dict(p["d"]))
    t0 = time.time()
    h.poll_once(now=t0)
    h.poll_once(now=t0 + 0.5)                                        # same last_update: not a new sample
    p["d"] = sample(update=2.0)
    h.poll_once(now=t0 + 1)
    h.store.flush()
    assert len(rows(db)) == 2


def test_daemon_up_but_hub_unplugged_is_not_served_as_data(db):
    h = make(db, sample(connected=False, daemon={"last_error": "no serial device", "last_crash": None}))
    h.poll_once(now=100.0)
    assert h.connected and not h.hub_ok
    assert h.chamber(now=100.5) is None and h.status()["bed_accel"] is None
    assert h.status()["last_error"] == "no serial device"
    h.store.flush()
    with pytest.raises(sqlite3.OperationalError):
        rows(db)


def test_unreachable_daemon(db):
    def boom():
        raise OSError("refused")
    h = make(db, boom)
    assert h.poll_once() is None and not h.connected and h.status()["enabled"]


def test_default_url_and_alias(monkeypatch):
    monkeypatch.delenv("INDUS3D_BED_HUB_URL", raising=False)
    monkeypatch.delenv("INDUS3D_ESP_HUB_URL", raising=False)
    assert eh._env_url() == "http://127.0.0.1:7127"
    monkeypatch.setenv("INDUS3D_ESP_HUB_URL", "http://old:1")
    assert eh._env_url() == "http://old:1"
    monkeypatch.setenv("INDUS3D_BED_HUB_URL", "")
    assert eh._env_url() == "" and eh.EspHub(url=None).enabled is False


# ── crash handling ─────────────────────────────────────────────────────────────
def crash_payload(result="paused", ts=500.0):
    return sample(update=2000.0, crash_detected=True, crash_info={"peak_jerk_mg": 2450},
                  daemon={"last_error": None, "last_crash": {"ts": ts, "jerk_mg": 2450, "source": "alert",
                                                             "action": {"result": result, "print_state": "printing"}}})


def test_crash_notifies_once_audits_and_flushes(db):
    p = {"d": sample()}
    h = make(db, lambda: dict(p["d"]))
    h.poll_once(now=1.0)
    p["d"] = crash_payload()
    h.poll_once(now=2.0)
    h.poll_once(now=3.0)                                             # still latched, same crash
    assert len(h.notes) == 1 and "2450" in h.notes[0] and "paused" in h.notes[0] and "YOURSELF" not in h.notes[0]
    assert len(h.audits) == 1 and h.audits[0][1:] == (2450, "paused")
    assert h.events[0]["kind"] == "crash" and h.events[0]["peak_jerk_mg"] == 2450
    assert any(r[-1] == 1 for r in rows(db))                         # the crash sample is on disk immediately


def test_failed_pause_is_shouted(db):
    h = make(db, crash_payload(result="FAILED to pause"))
    h.poll_once(now=1.0)
    assert "PAUSE THE PRINT YOURSELF" in h.notes[0]


def test_a_second_crash_after_reset_notifies_again(db):
    p = {"d": crash_payload(ts=500.0)}
    h = make(db, lambda: dict(p["d"]))
    h.poll_once(now=1.0)
    p["d"] = sample(update=3.0)                                      # latch reset
    h.poll_once(now=2.0)
    p["d"] = crash_payload(ts=900.0)
    h.poll_once(now=3.0)
    assert len(h.notes) == 2


def test_corrections_are_held_while_latched(db):
    h = make(db, crash_payload())
    ctx = {}
    assert h.filter_commands(["M104 S215"], ctx) == ["M104 S215"]    # not polled yet: nothing latched
    h.poll_once(now=1.0)
    assert h.filter_commands(["M104 S215", "M221 S95"], ctx) == []
    assert [v["command"] for v in ctx["vetoes"]] == ["M104 S215", "M221 S95"]
    assert all(v["plugin"] == "esp_bed_hub" and "crash" in v["reason"] for v in ctx["vetoes"])
    h.hold = False
    assert h.filter_commands(["M104 S215"], {}) == ["M104 S215"]


def test_hold_ends_only_when_a_connected_hub_clears_the_latch(db):
    p = {"d": crash_payload()}
    h = make(db, lambda: dict(p["d"]))
    h.poll_once(now=1.0)
    assert h.hold_active()
    p["d"] = sample(update=9.0)
    h.poll_once(now=2.0)
    assert not h.hold_active() and h.filter_commands(["M106 S100"], {}) == ["M106 S100"]
    p["d"] = crash_payload(ts=700.0)
    h.poll_once(now=3.0)
    p["d"] = sample(connected=False)
    h.poll_once(now=4.0)
    assert h.crash_latched and h.hold_active()
    assert h.filter_commands(["M104 S210"], {}) == []
    h._fetch = lambda _: (_ for _ in ()).throw(OSError("disconnected"))
    h.poll_once(now=5.0)
    assert h.hold_active()


# ── EXCLUDE_OBJECT (opt-in) ───────────────────────────────────────────────────────
def moonraker(status, calls):
    def mr(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return {"result": {"status": status}}
        return {}
    return mr


def test_exclude_object_is_off_by_default(db):
    calls = []
    h = make(db, crash_payload(), moonraker=moonraker({}, calls))
    h.poll_once(now=1.0)
    assert calls == [] and "excluded_object" not in h.events[0]


def test_exclude_object_when_paused(db):
    calls = []
    st = {"print_stats": {"state": "paused"}, "exclude_object": {"current_object": "cube_1"}}
    h = make(db, crash_payload(), moonraker=moonraker(st, calls), exclude_object=True)
    h.poll_once(now=1.0)
    assert h.events[0]["excluded_object"] == "cube_1"
    assert calls[-1] == ("POST", "/printer/gcode/script", {"script": "EXCLUDE_OBJECT NAME=cube_1"})


@pytest.mark.parametrize("status,expect", [
    ({"print_stats": {"state": "printing"}, "exclude_object": {"current_object": "a"}}, "not paused"),
    ({"print_stats": {"state": "paused"}, "exclude_object": {"current_object": None}}, "no usable"),
    ({"print_stats": {"state": "paused"}, "exclude_object": {"current_object": "a b;M112"}}, "no usable"),
])
def test_exclude_object_refuses_unsafe_situations(db, status, expect):
    calls = []
    h = make(db, crash_payload(), moonraker=moonraker(status, calls), exclude_object=True)
    h.poll_once(now=1.0)
    assert expect in h.events[0]["excluded_object"] and all(c[0] == "GET" for c in calls)


def test_exclude_object_failure_does_not_break_the_crash_path(db):
    def boom(*a, **k):
        raise OSError("moonraker down")
    h = make(db, crash_payload(), moonraker=boom, exclude_object=True)
    h.poll_once(now=1.0)
    assert h.events[0]["excluded_object"].startswith("failed") and len(h.notes) == 1


# ── actions and routes ───────────────────────────────────────────────────────────────
def test_actions_validate_and_proxy(db):
    sent = []
    h = make(db)
    h._post = lambda path, body: (sent.append((path, body)), {"ok": True})[1]
    assert h.run_action("reset_crash", confirmed=False)[0] == 400
    assert h.run_action("reset_crash", confirmed=True) == (200, {"ok": True, "message": "crash latch cleared"})
    assert sent[-1] == ("/reset_crash", {})
    for bad in (499, 8001, "2500", True, None, 2500.5):
        assert h.run_action("set_threshold", bad, True)[0] == 400
    assert h.run_action("set_threshold", 2500, True)[0] == 200 and sent[-1] == ("/threshold", {"mg": 2500})
    assert h.run_action("format_disk", None, True)[0] == 400
    h._post = lambda path, body: {"ok": False, "response": "// ERROR"}
    assert h.run_action("reset_crash", confirmed=True)[0] == 502

    def boom(path, body):
        raise OSError("down")
    h._post = boom
    assert h.run_action("reset_crash", confirmed=True)[0] == 502
    assert eh.EspHub(url="").run_action("reset_crash", confirmed=True)[0] == 503


def test_routes(db, monkeypatch):
    from flask import Flask
    h = make(db)
    h.poll_once(now=time.time())
    monkeypatch.setattr(eh, "hub", h)
    app = Flask(__name__)
    eh.register_routes(app)
    c = app.test_client()
    st = c.get("/api/v1/plugins/esp_bed_hub").get_json()
    assert st["connected"] and st["hub_connected"] and st["chamber"]["temp_c"] == 26.5 and st["crash_threshold_mg"] == 2000
    h.store.flush()
    out = c.get("/api/v1/plugins/esp_bed_hub/samples?minutes=5&limit=10").get_json()
    assert len(out["samples"]) == 1 and out["samples"][0]["chamber_humidity_pct"] == 44.0
    assert c.get("/api/v1/plugins/esp_bed_hub/samples?minutes=abc").status_code == 400
    h._post = lambda path, body: {"ok": True}
    assert c.post("/api/v1/plugins/esp_bed_hub/action", json={"action": "reset_crash", "confirmed": True}).status_code == 200
    assert c.post("/api/v1/plugins/esp_bed_hub/action", json={"action": "reset_crash"}).status_code == 400


def test_hooks_are_registered_with_the_filter_first():
    from core.plugin_hooks import HookRegistry
    reg = HookRegistry()
    eh.register_hooks(reg)
    assert [fn.__self__ for fn in reg._callbacks("commands.filter")] == [eh.hub]


# ── consumers: /api/v1/environment and /metrics ───────────────────────────────────────────
def test_environment_route_uses_the_hub_chamber_and_marks_missing_data(db, monkeypatch):
    from api import server
    h = make(db)
    h.poll_once(now=time.time())
    monkeypatch.setattr(eh, "hub", h)
    monkeypatch.setattr(server, "_worker", lambda: None)
    client = server.app.test_client()
    got = client.get("/api/v1/environment", environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert got == {"temperature": 26.5, "humidity": 44.0, "pressure": 1007.0, "source": "esp_bed_hub", "available": True}
    h.connected = False                                                # hub gone: no stale numbers
    got = client.get("/api/v1/environment", environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert got == {"temperature": 0.0, "humidity": 0.0, "available": False}


def test_prometheus_exports_hub_state(db, monkeypatch):
    from plugins import prometheus_exporter as prom
    h = make(db)
    h.poll_once(now=time.time())
    monkeypatch.setattr(eh, "hub", h)
    metrics = {n: v for n, v, _ in prom._plugin_state() if n.startswith("indus3d_bed_hub")}
    assert metrics["indus3d_bed_hub_connected"] == 1.0 and metrics["indus3d_bed_hub_crash_latched"] == 0.0
    assert metrics["indus3d_bed_hub_chamber_temp_c"] == 26.5 and metrics["indus3d_bed_hub_bed_jerk_mg"] == 7.0
