"""Filament-sensor integration: contract with the daemon, controller inputs, spool sync,
events/audit and the control-action proxy."""
import ast
import sqlite3
from pathlib import Path

import pytest

from plugins import filament_sensor as fs

DAEMON = Path(__file__).resolve().parents[2] / "helpers" / "filament_sensor" / "indus3d_sensor_daemon.py"


# ── contract with the daemon source ───────────────────────────────────────────
def daemon_status_keys():
    tree = ast.parse(DAEMON.read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Attribute) and t.attr == "telemetry" for t in node.targets)):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError("daemon telemetry dict not found")


def test_every_status_key_the_plugin_uses_exists_in_the_daemon():
    missing = set(fs.STATUS_KEYS_USED) - daemon_status_keys()
    assert not missing, f"daemon no longer provides: {sorted(missing)}"


def test_every_control_endpoint_the_plugin_calls_exists_in_the_daemon():
    src = DAEMON.read_text()
    for path in fs.ACTIONS.values():
        assert f'"{path}"' in src, f"daemon has no {path}"
    assert 'X-Indus3D-Action' in src            # the header run_action sends is the one the daemon demands


# ── fixtures ──────────────────────────────────────────────────────────────────
class Audit:
    def __init__(self):
        self.rows = []

    def __call__(self, alert_id, description, status="observed", now=None):
        self.rows.append((alert_id, description, status))


def status(**kw):
    base = {"connected": True, "faults": "NORMAL", "filament_present": True, "diameter_mm": 1.80,
            "velocity_mm_s": 4.0, "nozzle_diameter_mm": 1.80, "volumetric_flow_mm3_s": 10.2,
            "auto_flow_percent": 100.0, "runout_countdown_mm": 0.0, "spool_used_g": 10.0,
            "spool_remaining_g": 990.0, "bed_jerk_mg": 5}
    return {**base, **kw}


def bridge(**kw):
    audit = Audit()
    notes = []
    b = fs.SensorBridge(url="http://x", ini_path="", notify=notes.append, arbiter_external=set(), audit=audit,
                        spool=kw.pop("spool", None) or fs.SpoolSync(enabled=False), **kw)
    return b, audit, notes


def live(b, st=None, now=100.0):
    b.poll_once(fetch=lambda u: st or status(), now=now)
    return b


# ── controller inputs ─────────────────────────────────────────────────────────
def test_nozzle_flow_uses_the_delayed_diameter_not_the_current_one():
    f = fs.nozzle_flow_mm3_s(status(velocity_mm_s=4.0, diameter_mm=1.60, nozzle_diameter_mm=1.80))
    assert f == pytest.approx(4.0 * 3.14159265 * 0.9 ** 2, rel=1e-4)
    assert fs.nozzle_flow_mm3_s(status(nozzle_diameter_mm=0.0)) is None
    assert fs.nozzle_flow_mm3_s(status(velocity_mm_s=-3.0)) == 0.0          # retraction is not flow


def test_inputs_add_measurements_without_changing_the_controller_by_default():
    b = live(bridge()[0])
    ext = {"expected_flow_mm3_s": 8.0, "is_extruding": True, "flow_ratio": 1.0}
    b.inputs({}, {}, {}, ext, {"now": 101.0})
    assert ext["sensor_flow_ratio"] == pytest.approx(10.18 / 8.0, abs=0.01)
    assert ext["flow_ratio"] == 1.0 and "flow_ratio_source" not in ext      # opt-in only


def test_flow_input_opt_in_replaces_the_estimate():
    b = live(bridge(flow_input=True)[0])
    ext = {"expected_flow_mm3_s": 8.0, "is_extruding": True, "flow_ratio": 1.0}
    b.inputs({}, {}, {}, ext, {"now": 101.0})
    assert ext["flow_ratio"] == ext["sensor_flow_ratio"] and ext["flow_ratio_estimated"] == 1.0
    assert ext["flow_ratio_source"] == "sensor" and b.flow_input_state == "active"


def test_flow_input_yields_while_the_daemon_owns_flow():
    b = live(bridge(flow_input=True)[0], status(auto_flow_percent=94.0))
    ext = {"expected_flow_mm3_s": 8.0, "is_extruding": True, "flow_ratio": 1.0}
    b.inputs({}, {}, {}, ext, {"now": 101.0})
    assert ext["flow_ratio"] == 1.0 and "skipped" in b.flow_input_state


@pytest.mark.parametrize("ext,when", [
    ({"expected_flow_mm3_s": 8.0, "is_extruding": True}, 120.0),         # reading is stale (>3 s)
    ({"expected_flow_mm3_s": 0.2, "is_extruding": True}, 101.0),         # nothing meaningful to compare with
    ({"expected_flow_mm3_s": 8.0, "is_extruding": False}, 101.0),        # travel move
])
def test_no_ratio_when_unusable(ext, when):
    b = live(bridge(flow_input=True)[0])
    ext = {**ext, "flow_ratio": 1.0}
    b.inputs({}, {}, {}, ext, {"now": when})
    assert ext["flow_ratio"] == 1.0 and "flow_ratio_source" not in ext


def test_no_inputs_when_filament_absent_or_disconnected():
    b = live(bridge()[0], status(filament_present=False))
    ext = {"expected_flow_mm3_s": 8.0, "is_extruding": True}
    b.inputs({}, {}, {}, ext, {"now": 101.0})
    assert "sensor_flow_mm3_s" not in ext
    b2 = bridge()[0]
    b2.inputs({}, {}, {}, ext, {"now": 101.0})
    assert "sensor_flow_mm3_s" not in ext


def test_ratio_is_clamped():
    b = live(bridge(flow_input=True)[0], status(velocity_mm_s=60.0))
    ext = {"expected_flow_mm3_s": 1.0, "is_extruding": True, "flow_ratio": 1.0}
    b.inputs({}, {}, {}, ext, {"now": 101.0})
    assert ext["sensor_flow_ratio"] == fs.MAX_RATIO


# ── events and audit ──────────────────────────────────────────────────────────
def test_fault_runout_and_countdown_are_audited_once():
    b, audit, notes = bridge()
    b.print_state = "printing"
    for t in (1.0, 2.0):
        b.poll_once(fetch=lambda u: status(faults="SLIP", filament_present=False, runout_countdown_mm=120.0), now=t)
    kinds = [a[0] for a in audit.rows]
    assert kinds.count("filament_sensor:fault") == 1 and kinds.count("filament_sensor:runout") == 1
    assert kinds.count("filament_sensor:runout_countdown") == 1 and len(notes) == 2
    b.poll_once(fetch=lambda u: status(faults="SLIP", filament_present=False, runout_countdown_mm=0.0), now=3.0)
    assert "filament_sensor:runout_pause" in [a[0] for a in audit.rows]


def test_daemon_taking_over_flow_is_recorded():
    b, audit, _ = bridge()
    b.poll_once(fetch=lambda u: status(auto_flow_percent=94.0), now=1.0)
    b.poll_once(fetch=lambda u: status(auto_flow_percent=93.0), now=2.0)
    assert [a[0] for a in audit.rows].count("filament_sensor:auto_flow") == 1 and "flow" in b.external


# ── spool sync ────────────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path, monkeypatch):
    import db.models as models
    path = str(tmp_path / "t.db")
    monkeypatch.setattr(models, "DB_PATH", path)
    models.init_db()
    c = sqlite3.connect(path)
    c.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('virtual_spool_used_g', '50.0')")
    c.commit()
    c.close()
    return path


def add_history(db, filename="part.gcode", grams=12.0, cost=0.50):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO print_history (filename, status, print_time_seconds, filament_used_g, power_used_wh, cost_usd) "
              "VALUES (?, 'complete', 600, ?, 0, ?)", (filename, grams, cost))
    c.commit()
    c.close()


def row(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT filament_used_g, cost_usd FROM print_history ORDER BY id DESC LIMIT 1").fetchone(), \
               float(c.execute("SELECT value FROM printer_config WHERE key='virtual_spool_used_g'").fetchone()[0])
    finally:
        c.close()


RUN = {"id": 7, "filename": "part.gcode"}


def sync(price=0.02):
    audit = Audit()
    return fs.SpoolSync(enabled=True, price=lambda: price, audit=audit), audit


def test_spool_sync_replaces_estimate_with_measurement(db):
    s, audit = sync()
    s.begin(10.0)
    add_history(db, grams=12.0, cost=0.50)
    res = s.finish(RUN, 20.0)                                  # sensor measured 10 g
    assert res["applied"] and res["measured_g"] == 10.0 and res["estimated_g"] == 12.0
    (grams, cost), virtual = row(db)
    assert grams == 10.0 and cost == pytest.approx(0.50 - 2.0 * 0.02) and virtual == pytest.approx(48.0)
    assert audit.rows[0][0] == "sensor_spool_sync" and "12.0 g (estimate) -> 10.0 g" in audit.rows[0][1]


def test_spool_sync_applies_once(db):
    s, _ = sync()
    s.begin(10.0)
    add_history(db)
    s.finish(RUN, 20.0)
    s.begin(20.0)
    assert s.finish(RUN, 30.0)["reason"] == "already applied"
    assert row(db)[0][0] == 10.0


@pytest.mark.parametrize("start,end,why", [
    (None, 20.0, "not observed"), (10.0, None, "not observed"),
    (10.0, 10.0, "no measurable"), (10.0, 5.0, "no measurable"),     # counter reset mid-print
    (10.0, 90.0, "implausible"),                                      # 80 g vs a 12 g estimate
])
def test_spool_sync_skips_unreliable_data(db, start, end, why):
    s, audit = sync()
    s.begin(start)
    add_history(db, grams=12.0)
    res = s.finish(RUN, end)
    assert not res["applied"] and why in res["reason"] and row(db)[0][0] == 12.0 and audit.rows == []


def test_spool_sync_ignores_other_prints_rows(db):
    add_history(db, filename="old.gcode", grams=99.0)                 # existed before the print started
    s, _ = sync()
    s.begin(10.0)
    res = s.finish(RUN, 20.0)
    assert "no print_history row" in res["reason"] and row(db)[0][0] == 99.0


def test_spool_sync_disabled_is_a_noop(db):
    s = fs.SpoolSync(enabled=False)
    s.begin(10.0)
    add_history(db)
    assert s.finish(RUN, 20.0)["reason"] == "disabled" and row(db)[0][0] == 12.0


def test_tick_begins_sync_when_a_print_starts(db):
    s, _ = sync()
    b, _, _ = bridge(spool=s)
    b._started = True                                                 # do not spawn the poll thread
    live(b)
    b.tick({"print_state": "printing"}, {"now": 100.0})
    assert s.start and s.start["used"] == 10.0


# ── actions ───────────────────────────────────────────────────────────────────
def test_actions_are_validated_and_gated():
    b, audit, _ = bridge()
    assert b.run_action("explode", confirmed=True)[0] == 400
    assert b.run_action("tare_empty")[0] == 412
    b.print_state = "printing"
    assert b.run_action("tare_empty", confirmed=True)[0] == 409
    b.print_state = "standby"
    assert b.run_action("calibrate_span", target=9.0, confirmed=True)[0] == 400
    assert b.run_action("calibrate_span", target="x", confirmed=True)[0] == 400
    assert audit.rows == []


def test_action_sends_the_guard_header_target_and_is_audited():
    b, audit, _ = bridge()
    seen = []
    code, body = b.run_action("calibrate_span", target=1.8, confirmed=True,
                              fetch=lambda url: seen.append(url) or {"status": "ok"})
    assert code == 200 and seen == ["http://x/calibrate_span?target=1.800"]
    assert audit.rows == [("sensor_action", "filament sensor action: calibrate_span (target 1.800 mm)", "executed")]


def test_action_reports_unreachable_daemon_and_disabled_integration():
    b, _, _ = bridge()
    assert b.run_action("reset_spool", confirmed=True, fetch=lambda u: (_ for _ in ()).throw(OSError("x")))[0] == 502
    off = fs.SensorBridge(url="", ini_path="", arbiter_external=set(), audit=Audit(), spool=fs.SpoolSync(enabled=False))
    assert off.run_action("reset_spool", confirmed=True)[0] == 503


def test_action_route_requires_confirmation():
    from api.server import app
    c = app.test_client()
    assert c.post("/api/v1/plugins/filament_sensor/action", json={"action": "tare_empty"}).status_code == 412
    assert c.post("/api/v1/plugins/filament_sensor/action", json={"action": "nope", "confirmed": True}).status_code == 400
    assert c.get("/api/v1/plugins/filament_sensor").get_json()["spool_sync"]["enabled"] in (True, False)
