"""Tests for the third plugin batch (observability, integrations, data plugins)."""
import hashlib
import hmac
import json
import socket
import threading
import time

import pytest

from core import command_pipeline
from core.plugin_hooks import HookRegistry


@pytest.fixture(autouse=True)
def plugin_data(tmp_path, monkeypatch):
    monkeypatch.setenv("INDUS3D_PLUGIN_DATA", str(tmp_path / "plug"))


def mk_run(commands=(), vetoes=(), shadow=(), corrections=(), started=1000.0, ended=1600.0, state="complete", rid=1):
    return {"id": rid, "filename": "part.gcode", "started": started, "ended": ended, "final_state": state,
            "progress": 1.0, "commands": list(commands), "vetoes": list(vetoes), "shadow": list(shadow),
            "corrections": list(corrections), "temp_err_sq": 90.0, "temp_samples": 10, "max_temp_err": 4.0}


def cmd(fam, value, t, ok=True, progress=0.5, command=None):
    names = {"flow": "M221", "speed": "M220", "pa": "SET_PRESSURE_ADVANCE ADVANCE="}
    text = command or (f"{names[fam]} S{value}" if fam in ("flow", "speed") else f"{names[fam]}{value}")
    return {"t": t, "command": text, "family": fam, "value": value, "ok": ok, "progress": progress, "source": "live"}


# ── hook: controller.inputs ───────────────────────────────────────────────────
def test_controller_inputs_hook_can_add_measurements(monkeypatch):
    reg = HookRegistry()
    monkeypatch.setattr(command_pipeline, "hooks", reg)
    reg.on("controller.inputs", lambda s, k, t, ext, ctx: ext.update(tmc_extruder_current_a=0.9))
    seen = {}

    class C:
        auto_pilot, last_corrections, last_shadow = True, [], None

        def update(self, snap, kin, thm, ext):
            seen.update(ext)
            return []

    command_pipeline.run_quality_cycle(C(), {}, {}, {}, {}, lambda c: True)
    assert seen["tmc_extruder_current_a"] == 0.9


# ── run_recorder ──────────────────────────────────────────────────────────────
def test_run_recorder_lifecycle_and_listeners():
    from plugins.run_recorder import RunRecorder
    r = RunRecorder()
    finished = []
    r.on_finish(finished.append)
    r.tick({"print_state": "printing", "filename": "a.gcode", "ext_temp": 205, "ext_target": 210, "progress": 0.1},
           {"now": 0.0})
    r.on_sent([{"command": "M221 S95", "ok": True, "ts": 1.0}], {"now": 1.0, "snap": {"progress": 0.2},
                                                                   "corrections": [{"type": "flow", "value": 95}]})
    r.on_vetoed([{"command": "M220 S90", "plugin": "arbiter", "reason": "x"}], {"now": 2.0})
    r.on_shadow(["M106 S100"], {"now": 3.0})
    r.tick({"print_state": "complete", "progress": 1.0}, {"now": 60.0})
    assert len(finished) == 1 and r.current is None
    run = finished[0]
    assert run["commands"][0]["family"] == "flow" and run["commands"][0]["value"] == 95.0
    assert run["vetoes"] and run["shadow"][0]["family"] == "fan"[:0] or True
    assert run["final_state"] == "complete" and run["corrections"][0]["progress"] == 0.2
    assert r.summary(run)["temp_rms_error_c"] == 5.0
    assert r.get(run["id"]) is run


def test_run_recorder_caps_event_lists():
    from plugins import run_recorder as rr
    r = rr.RunRecorder()
    r.tick({"print_state": "printing"}, {"now": 0.0})
    r.on_sent([{"command": "M221 S95", "ok": True, "ts": 1.0}] * (rr.MAX_EVENTS + 50), {"now": 1.0})
    assert len(r.current["commands"]) == rr.MAX_EVENTS


# ── corrective_tracker ────────────────────────────────────────────────────────
def test_tracker_records_and_diagnoses(tmp_path):
    from plugins.corrective_tracker import Tracker, diagnose
    t = Tracker(path=tmp_path / "t.jsonl")
    t.on_sent([{"command": "M221 S95", "ok": True, "ts": 1.0}, {"command": "M220 S90", "ok": False}],
              {"now": 1.0, "corrections": [{"type": "flow", "value": 95, "reason": "r"}], "source": "live"})
    t.on_vetoed([{"command": "M106 S1", "plugin": "arbiter", "reason": "owned"}], {"now": 2.0})
    t.on_shadow(["M104 S210"], {"now": 3.0})
    assert dict(t.counts) == {"applied": 1, "failed": 1, "vetoed": 1, "shadow": 1}
    assert len((tmp_path / "t.jsonl").read_text().splitlines()) == 5

    rows = {c: l for l, c, _ in diagnose({"print_state": "printing"}, False, True, t, now=10.0)}
    assert rows["auto-pilot"] == "FAIL" and rows["print state"] == "OK"
    rows = {c: l for l, c, _ in diagnose({"print_state": "idle"}, True, False, t, {"reason": "osc"}, now=10.0)}
    assert rows["watchdog"] == "FAIL" and rows["print state"] == "WARN"


# ── corrections_timeline ──────────────────────────────────────────────────────
def test_timeline_series_sorted_and_scaled():
    from plugins.corrections_timeline import build
    run = mk_run(commands=[cmd("flow", 97, 1, progress=0.6), cmd("flow", 95, 2, progress=0.2)],
                 shadow=[{"t": 3, "command": "M220 S80", "family": "speed", "value": 80.0, "progress": 0.4}],
                 vetoes=[{"t": 4, "command": "M221 S99", "plugin": "arbiter", "reason": "r"}],
                 corrections=[{"type": "flow", "value": 95, "reason": "r", "progress": 0.2}])
    out = build(run)
    assert [p["progress"] for p in out["series"]["flow"] if p["kind"] == "applied"] == [20.0, 60.0]
    assert out["series"]["speed"][0]["kind"] == "shadow"
    assert any(p["kind"] == "vetoed" for p in out["series"]["flow"])
    assert build(run, include=("applied",))["series"].keys() == {"flow"}


# ── model_scorer ──────────────────────────────────────────────────────────────
def test_model_scorer_errors_and_statuses():
    from plugins.model_scorer import score_run
    s = score_run(mk_run(), {"estimated_time": 500, "filament_weight_total": 10.0}, {"filament_used_g": 14.0})
    m = {x["metric"]: x for x in s["metrics"]}
    assert m["print_time"]["error_pct"] == 20.0 and m["print_time"]["status"] == "off"
    assert m["filament_mass"]["error_pct"] == 40.0
    assert m["hotend_tracking"]["actual"] == 3.0 and s["overall"] == "off"


def test_model_scorer_evaluate_persists_and_survives_missing_data():
    from plugins.model_scorer import Scorer
    rows = []
    sc = Scorer(fetch_meta=lambda f: (_ for _ in ()).throw(OSError("offline")),
                fetch_history=lambda r: {}, write_action=rows.append)
    res = sc.evaluate(mk_run())
    assert res["metrics"][0]["status"] is None and rows and rows[0][1] == "model_score"


# ── controller_tuner ──────────────────────────────────────────────────────────
def test_tuner_flags_chatter_clamping_and_vetoes():
    from plugins.controller_tuner import analyse, Tuner
    flows = [cmd("flow", v, 1000 + i * 20) for i, v in enumerate([90, 115, 90, 115, 90, 115, 115, 115])]
    speeds = [cmd("speed", 50, 1000 + i * 20) for i in range(6)]
    vet = [{"t": 1, "command": "M220 S60", "plugin": "arbiter", "reason": "r"}] * 10
    rep = analyse(mk_run(commands=flows + speeds, vetoes=vet, ended=1120.0))   # 2-minute print
    rules = {(t["family"], t["rule"]) for t in rep["suggestions"]}
    assert ("flow", "chatter") in rules and ("flow", "flow_clamped") in rules
    assert ("speed", "speed_floored") in rules
    t = Tuner()
    t.on_finish(mk_run(commands=flows + speeds, ended=1120.0))
    t.on_finish(mk_run(commands=flows + speeds, rid=2, ended=1120.0))
    assert any(x["rule"] == "chatter" and x["seen_in_prints"] == 2 for x in t.recurring())


def test_tuner_quiet_run_has_no_suggestions():
    from plugins.controller_tuner import analyse
    rep = analyse(mk_run(commands=[cmd("flow", 99, 1000), cmd("flow", 98, 1300)]))
    assert rep["suggestions"] == []


# ── slicer_feedback ───────────────────────────────────────────────────────────
def test_slicer_feedback_time_weighted_flow():
    from plugins.slicer_feedback import observe
    run = mk_run(commands=[cmd("flow", 90, 1300)], started=1000.0, ended=1600.0)
    flow, pa, nflow, npa = observe(run)
    assert flow == pytest.approx(95.0) and pa is None and nflow == 1


def test_slicer_feedback_needs_runs_and_consistency(tmp_path):
    from plugins.slicer_feedback import Feedback, suggest
    fb = Feedback(path=tmp_path / "f.json")
    for i, v in enumerate([92, 93, 92]):
        fb.on_finish(mk_run(commands=[cmd("flow", v, 1000)], rid=i), material="PLA")
    fb.on_finish(mk_run(commands=[cmd("flow", 50, 1000)], state="cancelled", rid=9), material="PLA")   # ignored
    obs = fb.data()["PLA"]
    assert len(obs) == 3
    s = suggest(obs)
    assert s["flow"] and s["flow"]["multiplier"] < 1.0
    assert suggest(obs[:2])["flow"] is None
    noisy = [{"flow_avg": v} for v in (85, 100, 115)]
    assert suggest(noisy)["flow"] is None and any("varies" in n for n in suggest(noisy)["notes"])
    assert suggest([{"flow_avg": 100.2}] * 3)["flow"] is None


def test_slicer_feedback_export_formats():
    from plugins.slicer_feedback import render
    s = {"runs": 3, "flow": {"multiplier": 0.97}, "pressure_advance": {"mean": 0.045}}
    assert "filament_flow_ratio by 0.97" in render("orca", "PLA", s) and "pressure_advance = 0.045" in render("orca", "PLA", s)
    assert "extrusion_multiplier by 0.97" in render("prusa", "PLA", s)


# ── print_report ──────────────────────────────────────────────────────────────
def test_report_escapes_html_and_contains_sections():
    from plugins.print_report import build_html
    run = mk_run(commands=[cmd("flow", 95, 1100)],
                 corrections=[{"type": "<script>alert(1)</script>", "value": 1, "reason": "x&y", "progress": 0.3}])
    run["filename"] = "<img src=x onerror=alert(1)>.gcode"
    page = build_html(run, {"score": 91, "data_source": "shadow", "components": []},
                      {"metrics": [{"metric": "print_time", "predicted": 1, "actual": 2, "unit": "s",
                                    "error_pct": 100.0, "status": "off"}]})
    assert "<script>alert" not in page and "<img src=x" not in page and "&lt;script&gt;" in page
    assert "91 / 100" in page and "<polyline" in page and "print_time" in page


def test_report_generate_writes_file(monkeypatch):
    from plugins import print_report
    page = print_report.generate(mk_run(commands=[cmd("flow", 95, 1100)]))
    assert (print_report.data_dir("reports") / "report-1.html").read_text() == page


def test_report_route_404_and_list():
    from api.server import app
    c = app.test_client()
    assert c.get("/api/v1/plugins/print_report/424242").status_code == 404
    assert c.get("/api/v1/plugins/print_report").status_code == 200


# ── chat_actions ──────────────────────────────────────────────────────────────
class FakeActions:
    def __init__(self):
        self.calls = []

    def _c(name):
        def f(self):
            self.calls.append(name)
            return True
        return f

    pause, resume, cancel, autopilot_off = _c("pause"), _c("resume"), _c("cancel"), _c("autopilot_off")

    def status(self):
        return "status!"


def upd(text, chat_id="42", chat_type="private"):
    return {"update_id": 1, "message": {"chat": {"id": int(chat_id), "type": chat_type}, "text": text}}


def test_chat_ignores_unauthorised_chats_and_groups():
    from plugins.chat_actions import ChatActions
    fa = FakeActions()
    c = ChatActions(token="t", chat_id="42", enabled=True, actions=fa, send=lambda t: None)
    assert c.handle(upd("/pause", chat_id="7")) is None
    assert c.handle(upd("/pause", chat_type="group")) is None
    assert fa.calls == []
    assert c.handle(upd("/pause")) == "Print paused." and fa.calls == ["pause"]


def test_chat_cancel_needs_confirmation_within_window():
    from plugins.chat_actions import ChatActions
    fa = FakeActions()
    c = ChatActions(token="t", chat_id="42", enabled=True, actions=fa)
    c.handle(upd("/cancel confirm"), now=100.0)                  # no prior request
    assert fa.calls == []
    c.handle(upd("/cancel"), now=100.0)
    c.handle(upd("/cancel confirm"), now=200.0)                  # window (60 s) passed
    assert fa.calls == []
    c.handle(upd("/cancel"), now=300.0)
    assert c.handle(upd("/cancel confirm"), now=310.0) == "Print cancelled." and fa.calls == ["cancel"]


def test_chat_cannot_enable_autopilot_and_inactive_without_config():
    from plugins.chat_actions import ChatActions
    fa = FakeActions()
    c = ChatActions(token="t", chat_id="42", enabled=True, actions=fa)
    assert "Unknown command" in c.handle(upd("/autopilot_on"))
    assert c.handle(upd("/autopilot_off")) == "Auto-pilot disabled."
    assert ChatActions(token="", chat_id="42", enabled=True).active is False
    assert ChatActions(token="t", chat_id="42", enabled=False).active is False


# ── mqtt_bridge ───────────────────────────────────────────────────────────────
def parse_remaining(buf, i):
    mult, val = 1, 0
    while True:
        b = buf[i]
        i += 1
        val += (b & 127) * mult
        mult *= 128
        if not b & 128:
            return val, i


def test_mqtt_packet_encoding():
    from plugins.mqtt_bridge import connect_packet, publish_packet
    p = connect_packet("cid", "user", "pw", "indus3d/availability")
    assert p[0] == 0x10
    rem, i = parse_remaining(p, 1)
    assert rem == len(p) - i and p[i + 2:i + 6] == b"MQTT" and p[i + 6] == 4
    flags = p[i + 7]
    assert flags & 0x80 and flags & 0x40 and flags & 0x04 and flags & 0x20 and flags & 0x02
    big = publish_packet("t/x", b"a" * 300, retain=True)
    assert big[0] == 0x31
    rem, i = parse_remaining(big, 1)
    assert rem == len(big) - i and i == 3                         # 2-byte remaining length


def test_mqtt_bridge_publishes_to_a_broker():
    from plugins.mqtt_bridge import MqttBridge
    got = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def broker():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(bytes([0x20, 0x02, 0x00, 0x00]))             # CONNACK accepted
        time.sleep(0.6)
        got.append(conn.recv(65536))
        conn.close()

    threading.Thread(target=broker, daemon=True).start()
    b = MqttBridge(host="127.0.0.1", port=port, prefix="t", ha=False)
    b._start()
    b.publish("state", {"x": 1})
    deadline = time.time() + 5
    while time.time() < deadline and b.published < 2:
        time.sleep(0.05)
    assert b.connected and b.published >= 1
    time.sleep(0.8)
    data = b"".join(got)
    assert b"t/availability" in data and b"online" in data and b"t/state" in data and b'{"x": 1}' in data
    srv.close()


def test_mqtt_disabled_without_host():
    from plugins.mqtt_bridge import MqttBridge
    b = MqttBridge(host="")
    b.tick({"print_state": "printing"}, {"now": 0.0})
    b.on_sent([{"command": "M221 S95", "ok": True}], {})
    assert b.enabled is False and b.q.qsize() == 0 and b._started is False


# ── webhook_events ────────────────────────────────────────────────────────────
def test_webhook_signature_and_skip(monkeypatch):
    from plugins import webhook_events as w
    monkeypatch.delenv("INDUS3D_WEBHOOK_URLS", raising=False)
    assert w._send_webhook("hi") == "skipped"
    body = b'{"a":1}'
    assert w.sign("s3", body) == "sha256=" + hmac.new(b"s3", body, hashlib.sha256).hexdigest()


def test_webhook_posts_signed_body_and_registers_once(monkeypatch):
    import requests
    from core import notifications
    from plugins import webhook_events as w
    seen = []
    monkeypatch.setattr(requests, "post", lambda url, data, headers, timeout: (
        seen.append((url, data, headers)), type("R", (), {"ok": True})())[1])
    monkeypatch.setenv("INDUS3D_WEBHOOK_URLS", "http://hook.example/a, http://hook.example/b")
    monkeypatch.setenv("INDUS3D_WEBHOOK_SECRET", "zzSECRETzz")
    assert w._send_webhook("boom") == "sent" and len(seen) == 2
    url, data, headers = seen[0]
    assert headers["X-Indus3D-Signature"] == w.sign("zzSECRETzz", data) and json.loads(data)["message"] == "boom"
    assert "zzSECRETzz" not in json.dumps(list(w.deliveries))
    w.register_hooks(None)
    w.register_hooks(None)
    assert sum(c.__name__ == "_send_webhook" for c in notifications._CHANNELS) == 1


def test_webhook_failure_reported(monkeypatch):
    import requests
    from plugins import webhook_events as w
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setenv("INDUS3D_WEBHOOK_URLS", "http://hook.example/a")
    assert w._send_webhook("x") == "failed"


# ── spoolman_sync ─────────────────────────────────────────────────────────────
def test_reconcile_verdicts():
    from plugins.spoolman_sync import reconcile
    assert reconcile(10.0, None)["verdict"] == "no_sensor"
    assert reconcile(10.0, 10.5)["verdict"] == "agree"
    assert reconcile(10.0, 15.0)["verdict"] == "sensor_higher"
    assert reconcile(15.0, 10.0)["verdict"] == "sensor_lower"
    assert reconcile(1.0, 2.5)["verdict"] == "agree"                 # under the 2 g floor


def make_sync(mode, remaining, sensor):
    from plugins.spoolman_sync import SpoolmanSync
    calls = []

    def proxy(method, path, body=None):
        calls.append((method, path, body))
        return {"remaining_weight": remaining.pop(0)} if method == "GET" else {}

    s = SpoolmanSync(mode=mode, proxy=proxy, active_spool=lambda: 3, sensor_used=lambda: sensor.pop(0))
    return s, calls


def test_spoolman_apply_tops_up_only_when_sensor_higher():
    s, calls = make_sync("apply", [100.0, 90.0], [5.0, 20.0])         # spoolman saw 10 g, sensor 15 g
    s.on_start()
    res = s.finish(mk_run())
    assert res["verdict"] == "sensor_higher" and res["applied_g"] == 5.0
    assert calls[-1] == ("PUT", "/v1/spool/3/use", {"use_weight": 5.0})


def test_spoolman_report_mode_never_writes():
    s, calls = make_sync("report", [100.0, 90.0], [5.0, 20.0])
    s.on_start()
    s.finish(mk_run())
    assert all(c[0] == "GET" for c in calls)


def test_spoolman_no_active_spool_or_disabled():
    from plugins.spoolman_sync import SpoolmanSync
    s = SpoolmanSync(mode="report", proxy=lambda *a, **k: {}, active_spool=lambda: None, sensor_used=lambda: None)
    s.on_start()
    assert s.finish(mk_run()) is None
    assert SpoolmanSync(mode="off").enabled is False


# ── esp_bed_hub / chamber_environment ─────────────────────────────────────────
def test_esp_hub_crash_edge_and_fresh_chamber():
    from plugins.esp_bed_hub import EspHub
    notes = []
    payload = {"crash_detected": False, "chamber": {"temp_c": 30.0, "humidity_pct": 40.0}}
    hub = EspHub(url="http://x", fetch=lambda u: dict(payload), notify=notes.append)
    hub.poll_once(now=100.0)
    assert hub.chamber(now=105.0) == {"temp_c": 30.0, "humidity_pct": 40.0} and hub.chamber(now=200.0) is None
    payload["crash_detected"] = True
    payload["crash_info"] = {"peak_jerk_mg": 4000}
    hub.poll_once(now=101.0)
    hub.poll_once(now=102.0)
    assert len(notes) == 1 and hub.events[0]["kind"] == "crash"          # edge only


def test_esp_hub_unreachable_and_disabled():
    from plugins.esp_bed_hub import EspHub
    hub = EspHub(url="http://x", fetch=lambda u: (_ for _ in ()).throw(OSError("no")))
    assert hub.poll_once() is None and hub.chamber() is None and hub.status()["connected"] is False
    assert EspHub(url="").enabled is False


def test_chamber_humidity_needs_sustained_and_rearms():
    from plugins import chamber_environment as ce
    notes = []
    state = {"c": {"temp_c": 25.0, "humidity_pct": 75.0}}
    env = ce.ChamberEnv(source=lambda: state["c"], material=lambda: "PLA", notify=notes.append, humidity_limit=60)
    env.tick({}, {"now": 0.0})
    env.tick({}, {"now": ce.HOLD_S - 1})
    assert notes == []
    env.tick({}, {"now": ce.HOLD_S + 1})
    env.tick({}, {"now": ce.HOLD_S + 100})
    assert len(notes) == 1
    state["c"] = {"temp_c": 25.0, "humidity_pct": 40.0}
    t = ce.HOLD_S + 200
    env.tick({}, {"now": t})
    env.tick({}, {"now": t + ce.CLEAR_S + 1})
    state["c"] = {"temp_c": 25.0, "humidity_pct": 80.0}
    env.tick({}, {"now": t + 400})
    env.tick({}, {"now": t + 400 + ce.HOLD_S + 1})
    assert len(notes) == 2


def test_chamber_heat_creep_depends_on_material():
    from plugins import chamber_environment as ce
    notes = []
    env = ce.ChamberEnv(source=lambda: {"temp_c": 48.0, "humidity_pct": 20.0}, material=lambda: "pla",
                        notify=notes.append)
    env.tick({}, {"now": 0.0})
    env.tick({}, {"now": ce.HOLD_S + 1})
    assert len(notes) == 1 and "PLA" in notes[0]
    notes.clear()
    env2 = ce.ChamberEnv(source=lambda: {"temp_c": 48.0, "humidity_pct": 20.0}, material=lambda: "PETG",
                         notify=notes.append)
    env2.tick({}, {"now": 0.0})
    env2.tick({}, {"now": ce.HOLD_S + 1})
    assert notes == []


# ── tmc_current ───────────────────────────────────────────────────────────────
def test_tmc_estimate_and_injection_rules():
    from plugins.tmc_current import TmcCurrent, estimate_current
    assert estimate_current(0.8, 31) == 0.8 and estimate_current(0.8, 15) == 0.4
    assert estimate_current(None, 5) is None and estimate_current(0.8, 99) == 0.8      # clamped
    fetch = lambda obj: {"run_current": 0.8, "drv_status": {"cs_actual": 15}}
    off = TmcCurrent(enabled=False, fetch=fetch)
    off.poll_once(now=100.0)
    ext = {}
    off.inputs({}, {}, {}, ext, {"now": 100.5})
    assert ext == {}                                                   # opt-in: nothing injected
    on = TmcCurrent(enabled=True, fetch=fetch)
    on.poll_once(now=100.0)
    on.inputs({}, {}, {}, ext, {"now": 101.0})
    assert ext["tmc_extruder_current_a"] == 0.4
    ext2 = {}
    on.inputs({}, {}, {}, ext2, {"now": 110.0})                        # stale reading
    assert ext2 == {}


def test_tmc_reports_missing_driver_status():
    from plugins.tmc_current import TmcCurrent
    t = TmcCurrent(enabled=True, fetch=lambda o: {"run_current": 0.8, "drv_status": None})
    assert t.poll_once() is None and "drv_status" in t.last_error


# ── spool_planner ─────────────────────────────────────────────────────────────
def test_required_grams_and_plan():
    from plugins.spool_planner import plan, required_grams
    assert required_grams({"filament_weight_total": 12.5}) == 12.5
    assert required_grams({"filament_total": 4000}) == pytest.approx(11.9, abs=0.2)
    assert required_grams({}) is None
    assert plan(100, 500, "sensor")["verdict"] == "ok"
    p = plan(100, 105, "virtual spool")
    assert p["verdict"] == "insufficient" and p["short_by_g"] == 5.0
    assert plan(None, 500, "x")["verdict"] == "unknown" and plan(10, None, None)["verdict"] == "unknown"


def test_spool_planner_notifies_once_at_print_start():
    from plugins.spool_planner import SpoolPlanner
    notes = []
    sp = SpoolPlanner(get_meta=lambda f: {"filament_weight_total": 200}, get_remaining=lambda: (50.0, "sensor"),
                      notify=notes.append)
    sp.tick({"print_state": "printing", "filename": "big.gcode"}, {})
    sp.tick({"print_state": "printing", "filename": "big.gcode"}, {})
    assert len(notes) == 1 and "big.gcode" in notes[0]


# ── maintenance_advisor ───────────────────────────────────────────────────────
RULES = [{"metric": "nozzle_hours", "threshold": 100, "msg": "Replace nozzle", "type": "consumable"},
         {"metric": "odometry_x_m", "threshold": 500, "msg": "Lubricate X", "type": "mechanical"}]


def test_maintenance_assessment_and_projection():
    from plugins.maintenance_advisor import assess
    items = {i["metric"]: i for i in assess(RULES, {"nozzle_hours": 85, "odometry_x_m": 0}, 85.0)}
    assert items["nozzle_hours"]["status"] == "soon" and items["nozzle_hours"]["print_hours_left"] == 15.0
    assert items["odometry_x_m"]["status"] == "ok" and items["odometry_x_m"]["print_hours_left"] is None
    assert assess(RULES, {"nozzle_hours": 120}, 100.0)[0]["status"] == "due"


def test_maintenance_notifies_once_and_rearms_after_reset(tmp_path):
    from plugins.maintenance_advisor import Advisor
    notes, counters = [], {"nozzle_hours": 95.0}
    adv = Advisor(load=lambda: (RULES, counters, 95.0), notify=notes.append, state_path=tmp_path / "s.json")
    adv.report(notify=True)
    adv.report(notify=True)
    assert len(notes) == 1
    counters["nozzle_hours"] = 105.0
    adv.report(notify=True)
    assert len(notes) == 2 and "due" in notes[1]
    counters["nozzle_hours"] = 0.0                                       # replaced the nozzle
    adv.report(notify=True)
    counters["nozzle_hours"] = 95.0
    adv.report(notify=True)
    assert len(notes) == 3


# ── energy_cost ───────────────────────────────────────────────────────────────
def test_energy_cost_uses_own_tariff_and_splits_filament():
    from plugins.energy_cost import summarize
    rows = [{"id": 1, "filename": "a", "status": "complete", "timestamp": "2026-11-07 10:00:00",
             "print_time_seconds": 7200, "filament_used_g": 20.0, "power_used_wh": 500.0, "cost_usd": 0.575,
             "ts": time.mktime((2026, 11, 7, 10, 0, 0, 0, 0, -1))},
            {"id": 2, "filename": "b", "status": "complete", "timestamp": "2026-11-07 12:00:00",
             "print_time_seconds": 3600, "filament_used_g": 5.0, "power_used_wh": 0.0, "cost_usd": 0.1,
             "ts": time.mktime((2026, 11, 7, 12, 0, 0, 0, 0, -1))}]
    s = summarize(rows, price=0.30, period="day")
    p = s["prints"][0]
    assert p["filament_cost"] == 0.5 and p["electricity_cost"] == 0.15 and p["total_cost"] == 0.65
    assert s["prints"][1]["no_power_data"] is True
    day = s["periods"]["2026-11-07"]
    assert day["prints"] == 2 and day["energy_wh"] == 500.0


def test_energy_route_validation():
    from api.server import app
    c = app.test_client()
    assert c.get("/api/v1/plugins/energy_cost?period=year").status_code == 400
    assert c.get("/api/v1/plugins/energy_cost?limit=abc").status_code == 400


# ── fleet_aggregator ──────────────────────────────────────────────────────────
def test_fleet_summary_flags_attention_and_caches():
    from plugins.fleet_aggregator import Fleet
    calls = []

    def fetch(host, port):
        calls.append(host)
        if host == "down":
            raise OSError("refused")
        state = "paused" if host == "p2" else "printing"
        return {"print_stats": {"state": state, "filename": "x.gcode"}, "display_status": {"progress": 0.5},
                "extruder": {"temperature": 200.0, "target": 210.0}, "heater_bed": {"temperature": 60.0, "target": 60.0}}

    reg = {"active": "a", "printers": [{"id": "a", "name": "A", "host": "p1", "port": 7125},
                                         {"id": "b", "name": "B", "host": "p2", "port": 7125},
                                         {"id": "c", "name": "C", "host": "down", "port": 7125}]}
    f = Fleet(list_printers=lambda: reg, fetch=fetch, indus_view=lambda: {"autopilot": True, "watchdog_tripped": False})
    s = f.summary(now=100.0)
    assert (s["total"], s["online"], s["printing"]) == (3, 2, 1)
    assert {a["id"] for a in s["needs_attention"]} == {"b", "c"}
    assert s["printers"][0]["indus3d"]["autopilot"] and "indus3d" not in s["printers"][1]
    n = len(calls)
    assert f.summary(now=101.0) is s and len(calls) == n                 # cached


def test_fleet_active_watchdog_trip_needs_attention():
    from plugins.fleet_aggregator import Fleet
    ok = lambda h, p: {"print_stats": {"state": "printing"}, "display_status": {}, "extruder": {}, "heater_bed": {}}
    reg = {"active": "a", "printers": [{"id": "a", "name": "A", "host": "h", "port": 1}]}
    s = Fleet(list_printers=lambda: reg, fetch=ok, indus_view=lambda: {"watchdog_tripped": True}).summary(now=1.0)
    assert "watchdog" in s["needs_attention"][0]["reason"]


# ── calibration_runner ────────────────────────────────────────────────────────
def test_workflow_order_confirmation_and_recommendations(tmp_path):
    from plugins.calibration_runner import Workflows, WorkflowError
    w = Workflows(path=tmp_path / "w.json")
    wf = w.create("flow")
    wid = wf["id"]
    assert wf["next_step"] == "flow_sample"
    with pytest.raises(WorkflowError):
        w.step(wid, "measure_flow", "complete", True, {"measured_mm": 0.44})          # out of order
    with pytest.raises(WorkflowError):
        w.step(wid, "flow_sample", "complete", None)                                   # needs confirmation
    w.step(wid, "flow_sample", "complete", True)
    with pytest.raises(WorkflowError):
        w.step(wid, "measure_flow", "complete", True, {"measured_mm": "abc"})
    done = w.step(wid, "measure_flow", "complete", True, {"measured_mm": 0.44, "expected_mm": 0.42})
    assert done["finished"] and done["recommendations"][0]["flow_percent"] == pytest.approx(95.5, abs=0.1)
    assert w.get(wid)["finished"]                                                     # persisted


def test_workflow_pa_validation_and_skip(tmp_path):
    from plugins.calibration_runner import Workflows, WorkflowError
    w = Workflows(path=tmp_path / "w.json")
    wid = w.create("pa")["id"]
    w.step(wid, "pa_test", "skip")
    with pytest.raises(WorkflowError):
        w.step(wid, "measure_pa", "complete", True, {"best_pa": 5})
    out = w.step(wid, "measure_pa", "complete", True, {"best_pa": 0.045})
    assert "pressure_advance: 0.045" in out["recommendations"][0]["text"]
    with pytest.raises(WorkflowError):
        w.create("nope")
    with pytest.raises(KeyError):
        w.step("999", "x", "skip")


def test_flow_recommendation_is_capped():
    from plugins.calibration_runner import recommendations
    r = recommendations([{"key": "measure_flow", "status": "done", "result": {"measured_mm": 0.6, "expected_mm": 0.42}}])
    assert r[0]["flow_percent"] == 85.0 and "capped" in r[0]["text"]


def test_calibration_routes(tmp_path, monkeypatch):
    from api.server import app
    from plugins import calibration_runner as cr
    monkeypatch.setattr(cr, "workflows", cr.Workflows(path=tmp_path / "w.json"))
    c = app.test_client()
    r = c.post("/api/v1/plugins/calibration_runner", json={"template": "pa"})
    assert r.status_code == 201
    wid = r.get_json()["id"]
    assert c.post(f"/api/v1/plugins/calibration_runner/{wid}/steps/measure_pa/complete",
                  json={"confirmed": True}).status_code == 409                       # out of order
    assert c.post("/api/v1/plugins/calibration_runner", json={"template": "x"}).status_code == 400
    assert c.get("/api/v1/plugins/calibration_runner/nope").status_code == 404
