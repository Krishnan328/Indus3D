"""Tests for the plugin framework and the audit/shadow/arbiter/watchdog plugins."""
import os
import sqlite3
import time

import pytest

import plugins
from core import command_pipeline
from core.plugin_hooks import HookRegistry, ctx_veto
from digital_twin.quality_controller import QualityController
from plugins import arbiter as arbiter_mod
from plugins import audit_trail, watchdog as watchdog_mod


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    import db.models as models
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "t.db"))
    models.init_db()
    return str(tmp_path / "t.db")


@pytest.fixture
def reg(monkeypatch):
    r = HookRegistry()
    monkeypatch.setattr(command_pipeline, "hooks", r)
    return r


class FakeController:
    def __init__(self, commands, autopilot=True, corrections=None, shadow=None):
        self._c, self.auto_pilot = commands, autopilot
        self.last_corrections = corrections or []
        self.last_shadow = shadow

    def update(self, *a):
        return list(self._c)


def cycle(ctrl, send, reg_=None):
    return command_pipeline.run_quality_cycle(ctrl, {"print_state": "printing"}, {}, {}, {}, send, "test")


# ── Hook registry ─────────────────────────────────────────────────────────────
def test_priority_order_and_isolation():
    r, seen = HookRegistry(), []
    r.on("tick", lambda s, c: seen.append("late"), priority=90)
    r.on("tick", lambda s, c: (_ for _ in ()).throw(RuntimeError("boom")), priority=10)
    r.on("tick", lambda s, c: seen.append("early"), priority=20)
    r.emit("tick", {}, {})
    assert seen == ["early", "late"]          # the raising hook did not stop the others


def test_filter_failure_blocks_corrections():
    r = HookRegistry()
    r.on("commands.filter", lambda cmds, ctx: 1 / 0)
    r.on("commands.filter", lambda cmds, ctx: [c for c in cmds if c != "M220 S90"])
    assert r.apply("commands.filter", ["M221 S95", "M220 S90"], {}) == []


@pytest.mark.parametrize("failure", ["raises", "invalid_return"])
def test_filter_failure_keeps_emergency_commands_and_records_vetoes(failure):
    r = HookRegistry()
    def broken(commands, ctx):
        if failure == "raises":
            raise RuntimeError("failed safety filter")
        return None
    r.on("commands.filter", broken)
    ctx = {}
    assert r.apply("commands.filter", ["M104 S210", "PAUSE", "M112"], ctx) == ["PAUSE", "M112"]
    assert ctx["vetoes"][0]["command"] == "M104 S210"


def test_unknown_hook_rejected():
    with pytest.raises(ValueError):
        HookRegistry().on("nope", lambda: None)


# ── Pipeline ──────────────────────────────────────────────────────────────────
def test_pipeline_without_plugins_is_update_then_send(reg):
    sent = []
    res = cycle(FakeController(["M221 S95", "M220 S90"]), lambda c: sent.append(c) or True)
    assert sent == ["M221 S95", "M220 S90"] and all(r["ok"] for r in res)


def test_pipeline_vetoes_are_reported_and_not_sent(reg):
    def drop_flow(cmds, ctx):
        for c in cmds:
            if c.startswith("M221"):
                ctx_veto(ctx, c, "test", "nope")
        return [c for c in cmds if not c.startswith("M221")]

    vetoed = []
    reg.on("commands.filter", drop_flow)
    reg.on("commands.vetoed", lambda v, ctx: vetoed.extend(v))
    sent = []
    cycle(FakeController(["M221 S95", "M220 S90"]), lambda c: sent.append(c) or True)
    assert sent == ["M220 S90"] and vetoed[0]["command"] == "M221 S95"


def test_pipeline_send_error_and_none_result(reg):
    def send(c):
        if c.startswith("M221"):
            raise OSError("down")
        return None                      # simulator-style send

    res = cycle(FakeController(["M221 S95", "M220 S90"]), send)
    assert [r["ok"] for r in res] == [False, True]


# ── Shadow mode ───────────────────────────────────────────────────────────────
def _printing_inputs():
    snap = {"print_state": "printing", "ext_temp": 210.0, "ext_target": 210.0}
    ext = {"is_extruding": True, "expected_flow_mm3_s": 5.0, "flow_ratio": 0.8, "avg_flow_mm3_s": 8.0}
    return snap, ext


def test_shadow_computes_but_real_controller_stays_silent():
    qc = QualityController()
    qc._auto_pilot = False
    qc._shaper_loaded = True
    qc.enable_shadow()
    qc._last_flow_t = 0
    snap, ext = _printing_inputs()
    assert qc.update(snap, {}, {}, ext) == []                      # nothing is ever sent
    assert qc.last_shadow and any(c.startswith("M221") for c in qc.last_shadow["commands"])
    assert qc.corrections == [] and qc._flow_cmd == 100.0           # real state untouched
    assert qc.last_shadow["corrections"]


def test_shadow_disabled_by_default():
    qc = QualityController()
    qc._auto_pilot = False
    qc._shaper_loaded = True
    snap, ext = _printing_inputs()
    qc.update(snap, {}, {}, ext)
    assert qc.last_shadow is None


def test_shadow_off_when_autopilot_on():
    qc = QualityController()
    qc._auto_pilot = True
    qc._shaper_loaded = True
    qc.enable_shadow()
    qc._last_flow_t = 0
    snap, ext = _printing_inputs()
    assert qc.update(snap, {}, {}, ext)         # real commands
    assert qc.last_shadow is None


def test_shadow_never_pauses_the_printer(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("shadow run touched the printer")))
    sh = QualityController(shadow=True)
    sh._shaper_loaded = True
    snap, ext = _printing_inputs()
    ext["tmc_extruder_current_a"] = 50.0         # absurd current -> clog verdict
    cmds = sh.update(snap, {}, {}, ext)
    assert "PAUSE" in cmds


def test_pipeline_emits_shadow_hook(reg):
    got = []
    reg.on("shadow.commands", lambda cmds, ctx: got.append((cmds, ctx["corrections"])))
    ctrl = FakeController([], autopilot=False,
                          shadow={"commands": ["M221 S110"], "corrections": [{"type": "flow", "value": 110}]})
    cycle(ctrl, lambda c: True)
    assert got == [(["M221 S110"], [{"type": "flow", "value": 110}])]


# ── Arbiter ───────────────────────────────────────────────────────────────────
def test_arbiter_declared_ownership_blocks_family():
    a = arbiter_mod.Arbiter(external={"flow"})
    ctx = {"now": 100.0}
    assert a.filter(["M221 S95", "M220 S90"], ctx) == ["M220 S90"]
    assert ctx["vetoes"][0]["plugin"] == "arbiter"


def test_arbiter_detects_external_write_and_yields():
    a = arbiter_mod.Arbiter(yield_s=30)
    a.tick({"flow_factor": 100.0}, {"now": 0.0})
    a.tick({"flow_factor": 92.0}, {"now": 1.0})                 # nobody of ours sent that
    assert a.status()["events"][0]["family"] == "flow"
    ctx = {"now": 2.0}
    assert a.filter(["M221 S97", "M220 S90"], ctx) == ["M220 S90"]
    assert a.filter(["M221 S97"], {"now": 40.0}) == ["M221 S97"]    # yield expired


def test_arbiter_ignores_its_own_writes():
    a = arbiter_mod.Arbiter()
    a.tick({"flow_factor": 100.0, "speed_factor": 100.0}, {"now": 0.0})
    a.on_sent([{"command": "M221 S97", "ok": True, "ts": 1.0}], {"now": 1.0})
    a.tick({"flow_factor": 97.0, "speed_factor": 100.0}, {"now": 1.2})
    assert a.status()["events"] == [] and a.filter(["M221 S96"], {"now": 2.0}) == ["M221 S96"]


def test_arbiter_failed_send_is_not_recorded_as_ours():
    a = arbiter_mod.Arbiter()
    a.tick({"flow_factor": 100.0}, {"now": 0.0})
    a.on_sent([{"command": "M221 S97", "ok": False, "ts": 1.0}], {"now": 1.0})
    a.tick({"flow_factor": 97.0}, {"now": 1.2})
    assert a.status()["events"]


# ── Watchdog ──────────────────────────────────────────────────────────────────
@pytest.fixture
def wd(tmp_db):
    from digital_twin.quality_controller import quality_controller
    quality_controller._auto_pilot = True
    yield watchdog_mod.Watchdog(max_per_min=10, max_reversals=4, max_fails=3)
    quality_controller._auto_pilot = False


def ok(cmd, t):
    return {"command": cmd, "ok": True, "ts": t}


def test_watchdog_trips_on_rate_and_disables_autopilot(wd):
    from digital_twin.quality_controller import quality_controller as qc
    wd.on_sent([ok(f"M104 S{200 + i}", 1.0 + i * 0.1) for i in range(11)], {"now": 3.0})
    assert wd.tripped and "commands in" in wd.tripped["reason"]
    assert qc.auto_pilot is False
    ctx = {"now": 4.0}
    assert wd.filter(["M221 S95"], ctx) == [] and ctx["vetoes"][0]["plugin"] == "watchdog"


def test_watchdog_trips_on_oscillation(wd):
    for i, v in enumerate([90, 110, 90, 110, 90, 110]):    # 4 reversals >= limit
        wd.on_sent([ok(f"M221 S{v}", float(i))], {"now": float(i)})
    assert wd.tripped and "oscillation" in wd.tripped["reason"]


def test_watchdog_ignores_slow_steady_changes(wd):
    for i, v in enumerate([90, 92, 94, 96, 98, 100]):
        wd.on_sent([ok(f"M221 S{v}", float(i))], {"now": float(i)})
    assert wd.tripped is None


def test_watchdog_trips_on_consecutive_send_failures(wd):
    bad = {"command": "M221 S95", "ok": False, "ts": 1.0}
    wd.on_sent([bad, bad, bad], {"now": 2.0})
    assert wd.tripped and "failed sends" in wd.tripped["reason"]


def test_watchdog_rearms_only_when_user_reenables_autopilot(wd):
    from digital_twin.quality_controller import quality_controller as qc
    wd.tick({}, {})                                     # observes autopilot on
    wd.on_sent([ok(f"M104 S{200 + i}", 1.0 + i * 0.1) for i in range(11)], {"now": 3.0})
    assert wd.tripped
    wd.tick({}, {})                                     # autopilot is now off
    assert wd.tripped
    qc._auto_pilot = True                               # human turns it back on
    wd.tick({}, {})
    assert wd.tripped is None


# ── Audit trail ───────────────────────────────────────────────────────────────
def rows(db, sql):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_audit_records_commands_and_reasons(tmp_db):
    corr = [{"ts": 1.0, "type": "flow", "value": 95, "reason": "under-extrusion"}]
    audit_trail.on_sent([{"command": "M221 S95", "ok": True, "ts": 1.0},
                         {"command": "M220 S80", "ok": False, "ts": 1.0}],
                        {"now": 1.0, "corrections": corr})
    assert rows(tmp_db, "select command,source,status from command_log order by id") == [
        ("M221 S95", "qc", "ok"), ("M220 S80", "qc", "failed")]
    assert rows(tmp_db, "select alert_id,description,status from action_log") == [
        ("qc:flow", "under-extrusion", "applied")]


def test_audit_records_vetoes_and_shadow(tmp_db):
    audit_trail.on_vetoed([{"command": "M221 S95", "plugin": "arbiter", "reason": "owned"}], {"now": 2.0})
    audit_trail.on_shadow(["M221 S110"], {"now": 3.0, "corrections": [
        {"ts": 3.0, "type": "flow", "value": 110, "reason": "r"}]})
    got = rows(tmp_db, "select command,source,status from command_log order by id")
    assert got[0] == ("M221 S95", "qc", "vetoed:arbiter: owned")
    assert got[1] == ("M221 S110", "qc-shadow", "shadow")
    assert rows(tmp_db, "select alert_id,status from action_log") == [("qc_shadow:flow", "shadow")]


def test_audit_never_raises_on_db_failure(monkeypatch):
    import db.models as models
    monkeypatch.setattr(models, "get_connection", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    audit_trail.on_sent([{"command": "M221 S95", "ok": True, "ts": 1.0}], {"now": 1.0})


# ── Loader ────────────────────────────────────────────────────────────────────
def test_loader_isolates_a_broken_plugin_and_honours_disable(monkeypatch):
    d = os.path.dirname(plugins.__file__)
    broken, extra = os.path.join(d, "zz_broken_test.py"), os.path.join(d, "zz_ok_test.py")
    open(broken, "w").write("raise RuntimeError('bad plugin')\n")
    open(extra, "w").write("PLUGIN_INFO = {'title': 'ok'}\n")
    try:
        monkeypatch.setenv("INDUS3D_DISABLED_PLUGINS", "zz_ok_test")
        loaded = plugins.load_plugins(None)
        assert "zz_broken_test" not in loaded and "zz_ok_test" not in loaded
        monkeypatch.delenv("INDUS3D_DISABLED_PLUGINS")
        loaded = plugins.load_plugins(None)
        assert "zz_ok_test" in loaded and "zz_broken_test" not in loaded
    finally:
        for p in (broken, extra):
            os.path.exists(p) and os.remove(p)
        plugins._loaded.pop("zz_ok_test", None)


def test_plugin_routes_are_served():
    from api.server import app
    c = app.test_client()
    for path in ("/api/v1/plugins", "/api/v1/plugins/shadow_mode", "/api/v1/plugins/arbiter",
                 "/api/v1/plugins/watchdog"):
        assert c.get(path).status_code == 200
    names = {p["name"] for p in c.get("/api/v1/plugins").get_json()["plugins"]}
    assert {"audit_trail", "shadow_mode", "arbiter", "watchdog"} <= names
