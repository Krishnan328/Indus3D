"""Tests for approval, first_layer_guard, thermal_sanity, filament_sensor,
health_score and prometheus_exporter, plus the veto -> controller feedback."""
import re
import sqlite3
import time

import pytest

from core import command_pipeline
from core.plugin_hooks import HookRegistry
from digital_twin.quality_controller import QualityController
from plugins import approval as approval_mod
from plugins import filament_sensor as fs_mod
from plugins import first_layer_guard as guard_mod
from plugins import health_score as hs_mod
from plugins import prometheus_exporter as prom
from plugins import thermal_sanity as ts_mod


# ── veto feedback to the controller ───────────────────────────────────────────
def test_vetoed_flow_command_is_forgotten_so_it_is_proposed_again():
    qc = QualityController()
    qc._auto_pilot = True
    qc._shaper_loaded = True
    ext = {"is_extruding": True, "expected_flow_mm3_s": 5.0, "flow_ratio": 0.9}
    qc._last_flow_t = 0
    first = [c for c in qc.update({"print_state": "printing"}, {}, {}, ext) if c.startswith("M221")]
    assert first
    qc.notify_vetoed(first[0])                       # a plugin dropped it
    assert qc._flow_cmd == 100.0
    qc._last_flow_t = 0
    again = [c for c in qc.update({"print_state": "printing"}, {}, {}, ext) if c.startswith("M221")]
    assert again == first                            # recomputed from the clean state


def test_notify_vetoed_resets_other_families():
    qc = QualityController()
    qc._pa_cmd, qc._fan_cmd, qc._temp_cmd, qc._retract_cmd = 0.05, 100, 215.0, 1.2
    qc._velocity_cmd = qc._scv_cmd = qc._accel_cmd = 1
    for c in ("SET_PRESSURE_ADVANCE ADVANCE=0.05", "M106 S100", "M104 S215",
              "SET_RETRACTION RETRACT_LENGTH=1.2", "SET_VELOCITY_LIMIT VELOCITY=50"):
        qc.notify_vetoed(c)
    assert (qc._pa_cmd, qc._fan_cmd, qc._temp_cmd, qc._retract_cmd, qc._velocity_cmd) == (None,) * 5


def test_pipeline_tells_controller_about_vetoes(monkeypatch):
    reg = HookRegistry()
    monkeypatch.setattr(command_pipeline, "hooks", reg)
    reg.on("commands.filter", lambda cmds, ctx: (ctx.setdefault("vetoes", []).append(
        {"command": cmds[0], "plugin": "t", "reason": "r"}), [])[1])
    seen = []

    class C:
        auto_pilot, last_corrections, last_shadow = True, [], None
        update = lambda self, *a: ["M221 S95"]
        notify_vetoed = lambda self, cmd: seen.append(cmd)

    command_pipeline.run_quality_cycle(C(), {}, {}, {}, {}, lambda c: True)
    assert seen == ["M221 S95"]


# ── approval ──────────────────────────────────────────────────────────────────
def test_approval_off_is_passthrough():
    a = approval_mod.Approval(enabled=False)
    assert a.filter(["M221 S95"], {"now": 1.0}) == ["M221 S95"]


def test_approval_holds_supersedes_and_passes_safety():
    a = approval_mod.Approval(enabled=True, ttl_s=30)
    t0 = time.time()                      # status() expires against the wall clock
    ctx = {"now": t0, "send": lambda c: True}
    assert a.filter(["M221 S95", "PAUSE"], ctx) == ["PAUSE"]
    a.filter(["M221 S97"], {"now": t0 + 1})
    pend = a.status()["pending"]
    assert [p["command"] for p in pend] == ["M221 S97"]            # newer replaced older
    assert any(h["outcome"] == "superseded" for h in a.status()["history"])


def test_approval_approve_sends_and_emits_sent(monkeypatch):
    reg = HookRegistry()
    monkeypatch.setattr(command_pipeline, "hooks", reg)
    emitted = []
    reg.on("commands.sent", lambda res, ctx: emitted.append((res, ctx["source"])))
    sent = []
    a = approval_mod.Approval(enabled=True, ttl_s=30)
    a.filter(["M221 S95"], {"now": 1.0, "send": lambda c: sent.append(c) or True,
                           "snap": {"print_state": "printing", "filename": "a.gcode"},
                           "autopilot": True})
    item, err = a.decide(1, True, now=2.0)
    assert err is None and sent == ["M221 S95"] and item["ok"]
    assert emitted[0][1] == "approval" and emitted[0][0][0]["command"] == "M221 S95"
    assert a.decide(1, True, now=3.0)[1]                            # cannot be approved twice


def test_approval_reject_and_expiry():
    a = approval_mod.Approval(enabled=True, ttl_s=30)
    a.filter(["M221 S95"], {"now": 1.0, "send": lambda c: True})
    assert a.decide(1, False, now=2.0)[1] is None and a.status()["pending"] == []
    a.filter(["M220 S90"], {"now": 10.0, "send": lambda c: True})
    item, err = a.decide(2, True, now=50.0)                         # stale -> never sent
    assert item is None and "expired" in a.status()["history"][0]["outcome"]


def test_approval_routes(monkeypatch):
    from api.server import app
    monkeypatch.setattr(approval_mod.approval, "enabled", False)
    c = app.test_client()
    assert c.post("/api/v1/plugins/approval/mode", json={"enabled": "yes"}).status_code == 400
    assert c.post("/api/v1/plugins/approval/mode", json={"enabled": True}).get_json()["enabled"] is True
    assert c.post("/api/v1/plugins/approval/99/approve").status_code == 404


# ── first-layer guard ─────────────────────────────────────────────────────────
def test_first_layer_guard_blocks_low_z_but_not_safety():
    g = guard_mod.FirstLayerGuard(z_limit=0.8, block="all")
    ctx = {"snap": {"print_state": "printing", "cmd_z": 0.2}, "now": 1.0}
    assert g.filter(["M221 S95", "PAUSE"], ctx) == ["PAUSE"]
    assert ctx["vetoes"][0]["plugin"] == "first_layer_guard" and g.blocked_total == 1


def test_first_layer_guard_inactive_above_limit_or_not_printing():
    g = guard_mod.FirstLayerGuard(z_limit=0.8)
    assert g.filter(["M221 S95"], {"snap": {"print_state": "printing", "cmd_z": 1.4}}) == ["M221 S95"]
    assert g.filter(["M221 S95"], {"snap": {"print_state": "standby", "cmd_z": 0.2}}) == ["M221 S95"]


def test_first_layer_guard_family_selection():
    g = guard_mod.FirstLayerGuard(z_limit=0.8, block="flow,speed")
    ctx = {"snap": {"print_state": "printing", "cmd_z": 0.2}}
    assert g.filter(["M221 S95", "M106 S100"], ctx) == ["M106 S100"]


# ── thermal sanity ────────────────────────────────────────────────────────────
def snap_t(**kw):
    base = {"print_state": "printing", "ext_temp": 210.0, "ext_target": 210.0, "ext_pwm": 0.3,
            "bed_temp": 60.0, "bed_target": 60.0}
    return {**base, **kw}


def run(ts, seq, start=0.0, dt=0.1):
    t = start
    for s in seq:
        ts.tick(s, {"now": t})
        t += dt
    return t


def test_thermal_spike_detected_once():
    notes = []
    ts = ts_mod.ThermalSanity(notify=notes.append)
    run(ts, [snap_t(ext_temp=210), snap_t(ext_temp=245), snap_t(ext_temp=210)])
    assert [e["kind"] for e in ts.events] == ["sensor_spike"] and len(notes) == 1


def test_thermal_off_target_needs_sustained_deviation():
    ts = ts_mod.ThermalSanity()
    run(ts, [snap_t(ext_temp=190)] * 5, dt=1.0)
    assert ts.total == 0                                            # not long enough
    run(ts, [snap_t(ext_temp=190)] * 100, start=10.0, dt=1.0)
    assert any(e["kind"] == "off_target" for e in ts.events)


def test_heater_not_heating_fires_and_rearms():
    ts = ts_mod.ThermalSanity()
    bad = snap_t(ext_temp=150.0, ext_pwm=1.0)
    t = run(ts, [bad] * 25, dt=1.0)
    assert any(e["kind"] == "heater_not_heating" for e in ts.events)
    n = ts.total
    t = run(ts, [bad] * 10, start=t, dt=1.0)
    assert sum(e["kind"] == "heater_not_heating" for e in ts.events) == 1   # still raised: no duplicate
    t = run(ts, [snap_t(ext_temp=151.0)] * 40, start=t, dt=1.0)    # PWM drops, clear for > 30 s
    run(ts, [bad] * 25, start=t, dt=1.0)
    assert sum(e["kind"] == "heater_not_heating" for e in ts.events) == 2   # re-armed


def test_healthy_heating_ramp_is_not_flagged():
    ts = ts_mod.ThermalSanity()
    run(ts, [snap_t(ext_temp=150 + i * 2.0, ext_pwm=1.0) for i in range(30)], dt=1.0)
    assert ts.total == 0


# ── filament sensor bridge ────────────────────────────────────────────────────
def make_bridge(ini=""):
    ext = set()
    notes = []
    b = fs_mod.SensorBridge(url="http://x", ini_path=ini, notify=notes.append, arbiter_external=ext,
                            audit=lambda *a, **k: None)
    return b, ext, notes


def test_sensor_unreachable_is_quiet_and_not_connected():
    b, ext, _ = make_bridge()
    b.poll_once(fetch=lambda u: (_ for _ in ()).throw(OSError("refused")), now=1.0)
    assert b.summary()["connected"] is False and ext == set()


def test_sensor_auto_flow_makes_arbiter_yield_flow_then_releases():
    b, ext, _ = make_bridge()
    b.poll_once(fetch=lambda u: {"auto_flow_percent": 93.5, "faults": "NORMAL"}, now=0.0)
    assert "flow" in ext and b.summary()["flow_owned_by_sensor"]
    b.poll_once(fetch=lambda u: {"auto_flow_percent": 100.0, "faults": "NORMAL"}, now=fs_mod.AUTO_FLOW_HOLD_S + 5)
    assert "flow" not in ext


def test_sensor_ini_declares_flow_ownership(tmp_path):
    ini = tmp_path / "s.ini"
    ini.write_text("[features]\nenable_auto_flow = true\n")
    b, ext, _ = make_bridge(str(ini))
    b.poll_once(fetch=lambda u: {"auto_flow_percent": 100.0}, now=0.0)
    assert "flow" in ext


def test_sensor_fault_and_runout_alert_once():
    b, _, notes = make_bridge()
    b.print_state = "printing"
    for _ in range(3):
        b.poll_once(fetch=lambda u: {"faults": "SLIP", "filament_present": False}, now=1.0)
    assert len(notes) == 2                                          # fault + runout, once each


# ── health score ──────────────────────────────────────────────────────────────
def hs(active, source="auto-pilot", thermal=0, trips=0):
    rows = []
    state = {"thermal": thermal, "trips": trips}
    h = hs_mod.HealthScore(controller=lambda: (source, active), thermal=lambda: state["thermal"],
                           watchdog=lambda: state["trips"], write_log=rows.append)
    return h, rows, state


def test_clean_print_scores_100():
    h, rows, _ = hs({"adhesion_score": 1.0, "warpage_mm": 0.1, "ra_predicted_um": 10.0, "nozzle_status": "NORMAL"})
    h.tick({"print_state": "printing"}, {"now": 0.0})
    h.tick({"print_state": "printing"}, {"now": 2.0})
    h.tick({"print_state": "complete"}, {"now": 10.0})
    assert h.last_final["score"] == 100.0 and rows and rows[0][1] == "print_health"


def test_penalties_and_components():
    h, rows, state = hs({"adhesion_score": 0.5, "warpage_mm": 0.7, "ra_predicted_um": 24.0, "nozzle_status": "CLOG_WARNING"},
                        thermal=0, trips=0)
    h.tick({"print_state": "printing"}, {"now": 0.0})
    h.tick({"print_state": "printing"}, {"now": 2.0})
    state["thermal"], state["trips"] = 2, 1                          # events during the print
    h.tick({"print_state": "complete"}, {"now": 10.0})
    names = {c["name"] for c in h.last_final["components"]}
    assert {"adhesion", "warpage", "nozzle", "roughness", "thermal", "watchdog"} <= names
    assert 0 <= h.last_final["score"] < 50


def test_baselines_reset_each_print():
    h, _, state = hs({"adhesion_score": 1.0})
    state["thermal"] = 5                                             # events from a previous print
    h.tick({"print_state": "printing"}, {"now": 0.0})
    assert h.score(5.0)["score"] == 100.0


def test_reports_data_source_for_shadow_runs():
    h, _, _ = hs({"adhesion_score": 1.0}, source="shadow")
    h.tick({"print_state": "printing"}, {"now": 0.0})
    assert h.score(1.0)["data_source"] == "shadow"


# ── prometheus ────────────────────────────────────────────────────────────────
def test_render_is_valid_exposition_text():
    text = prom.render(
        {"online": True, "print_state": "printing", "ext_temp": 210.5, "kinematics": {"lag": 0.2, "stress": {"X": 0.1}},
         "live_commands": [{"text": "ignored"}]},
        autopilot=True, quality={"flow_pct": 95, "nozzle_status": "NORMAL"},
        plugin_state=[("indus3d_watchdog_tripped", 0.0, None), ("indus3d_arbiter_yield_seconds", 12.0, {"family": "flow"})])
    assert "indus3d_up 1" in text and 'indus3d_print_state{state="printing"} 1' in text
    assert "indus3d_ext_temp 210.5" in text and "indus3d_kinematics_stress_X" .lower() in text
    assert 'indus3d_arbiter_yield_seconds{family="flow"} 12' in text
    series = [l.split(" ")[0] for l in text.splitlines() if l and not l.startswith("#")]
    assert len(series) == len(set(series))                           # no duplicate series
    for l in text.splitlines():
        assert l.startswith("#") or re.match(r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{.*\})? [-+0-9.eE]+$', l), l


def test_label_escaping_and_nan_skipped():
    text = prom.render({"print_state": 'we"ird\nstate', "bad": float("nan")})
    assert 'we\\"ird\\nstate' in text and "indus3d_bad" not in text


def test_counters_follow_hooks():
    prom._commands.clear(); prom._vetoes.clear(); prom._shadow.clear()
    prom.on_sent([{"command": "M221 S95", "ok": True}, {"command": "M220 S90", "ok": False}], {})
    prom.on_vetoed([{"command": "M106 S1", "plugin": "arbiter", "reason": "r"}], {})
    prom.on_shadow(["M221 S110"], {})
    text = prom.render({})
    assert 'indus3d_commands_total{family="flow",result="ok"} 1' in text
    assert 'indus3d_commands_total{family="speed",result="failed"} 1' in text
    assert 'indus3d_vetoes_total{plugin="arbiter"} 1' in text
    assert 'indus3d_shadow_commands_total{family="flow"} 1' in text


def test_metrics_route_serves_text():
    from api.server import app
    r = app.test_client().get("/metrics")
    assert r.status_code == 200 and r.mimetype == "text/plain" and b"indus3d_up" in r.data
