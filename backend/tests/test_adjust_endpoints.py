"""Typed toolhead/thermal control endpoints (api/routes/adjust.py): validation, bounds, 502, simulator
branch, busy refusal and the arbiter hand-off."""
import pytest
from flask import Flask

from api import moonraker_util as mu
from api import printer_status as ps
from api.routes import adjust, printer

OBJECTS = ["extruder", "extruder1", "heater_bed", "heater_generic chamber", "fan", "fan_generic exhaust",
           "heater_fan hotend_fan", "output_pin beeper", "probe", "z_tilt", "firmware_retraction",
           "manual_probe", "gcode_move", "toolhead", "configfile"]
LIMITS = {"extruder": {"min_temp": 0, "max_temp": 285}, "extruder1": {"min_temp": 0, "max_temp": 260},
          "heater_bed": {"min_temp": 0, "max_temp": 120}, "heater_generic chamber": {"min_temp": 0, "max_temp": 70}}
URL = "/api/v1/printer/adjust"


class Sim:
    def __init__(self):
        self.injected = []

    def inject_gcode(self, s):
        self.injected.append(s)


@pytest.fixture
def client(monkeypatch):
    import workers
    mu.reset_cache()
    ps.reset()
    monkeypatch.setattr(workers, "_active_worker", None)
    monkeypatch.setattr(mu, "list_objects", lambda: list(OBJECTS))
    monkeypatch.setattr(mu, "heater_limits", lambda: dict(LIMITS))
    monkeypatch.setattr(mu, "query_objects", lambda names: {"extruder": {"can_extrude": True}})
    monkeypatch.setattr(printer, "_printer_is_busy", lambda: False)
    sent, noted = [], []

    class R:
        ok = True
        text = ""
    monkeypatch.setattr(mu, "run_script", lambda script, timeout=10: (sent.append(script), R())[1])
    import plugins.arbiter as arb
    monkeypatch.setattr(arb, "note_manual_change", lambda family, seconds=None, detail="": noted.append(family))
    app = Flask(__name__)
    app.register_blueprint(adjust.adjust_bp, url_prefix=URL)
    c = app.test_client()
    c.sent, c.noted, c.R, c.workers, c.mp = sent, noted, R, workers, monkeypatch
    return c


def post(c, path, body=None):
    return c.post(f"{URL}/{path}", json=body if body is not None else {})


def go_busy(c):
    c.mp.setattr(printer, "_printer_is_busy", lambda: True)


def go_sim(c):
    sim = Sim()
    c.mp.setattr(c.workers, "_active_worker", sim)
    return sim


def moonraker_down(c):
    def boom(*a, **k):
        raise mu.MoonrakerError("Moonraker unreachable: down")
    c.mp.setattr(mu, "run_script", boom)


# ── heater ───────────────────────────────────────────────────────────────────
def test_heater_builds_script_and_notes_arbiter_family(client):
    r = post(client, "heater", {"heater": "extruder", "target": 215})
    assert r.status_code == 200 and r.get_json()["status"] == "ok"
    assert client.sent == ["SET_HEATER_TEMPERATURE HEATER=extruder TARGET=215"] and client.noted == ["nozzle_temp"]
    post(client, "heater", {"heater": "heater_bed", "target": 60.5})
    assert client.sent[-1] == "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=60.5" and client.noted[-1] == "bed_temp"
    post(client, "heater", {"heater": "heater_generic chamber", "target": 40})
    assert client.sent[-1] == "SET_HEATER_TEMPERATURE HEATER=chamber TARGET=40" and len(client.noted) == 2  # no family
    post(client, "heater", {"heater": "extruder1", "target": 0})
    assert client.sent[-1] == "SET_HEATER_TEMPERATURE HEATER=extruder1 TARGET=0"


def test_heater_target_bounded_by_configured_max_minus_margin(client):
    assert post(client, "heater", {"heater": "extruder", "target": 285 - adjust.TEMP_MARGIN_C}).status_code == 200
    r = post(client, "heater", {"heater": "extruder", "target": 285})
    assert r.status_code == 400 and "between" in r.get_json()["error"]
    assert post(client, "heater", {"heater": "heater_generic chamber", "target": 66}).status_code == 400   # limit 70
    assert post(client, "heater", {"heater": "extruder", "target": -1}).status_code == 400
    assert len(client.sent) == 1 and client.noted == ["nozzle_temp"]


@pytest.mark.parametrize("body", [
    {"heater": "extruder", "target": "200"}, {"heater": "extruder", "target": True},
    {"heater": "extruder", "target": float("nan")}, {"heater": "extruder", "target": float("inf")},
    {"heater": "extruder"}, {"target": 100}, {"heater": "extruder\nM112", "target": 100},
    {"heater": "heater_generic chamber;M112", "target": 100}, {"heater": "mcu", "target": 100},
    {"heater": "fan", "target": 100}, {"heater": ["extruder"], "target": 100},
])
def test_heater_rejects_bad_input(client, body):
    assert post(client, "heater", body).status_code == 400 and client.sent == []


def test_heater_unknown_object_and_unknown_limit(client):
    assert post(client, "heater", {"heater": "extruder2", "target": 100}).status_code == 404
    assert post(client, "heater", {"heater": "heater_generic ghost", "target": 10}).status_code == 404
    client.mp.setattr(mu, "heater_limits", lambda: {})
    r = post(client, "heater", {"heater": "extruder", "target": 100})
    assert r.status_code == 409 and client.sent == []


def test_non_json_body_is_a_400(client):
    r = client.post(f"{URL}/heater", data="not json", content_type="text/plain")
    assert r.status_code == 400
    assert client.post(f"{URL}/speed", json=[1]).status_code == 400


# ── fans and outputs ─────────────────────────────────────────────────────────
def test_part_fan_uses_m106_m107(client):
    post(client, "fan", {"fan": "fan", "speed": 0.5})
    post(client, "fan", {"speed": 1})
    post(client, "fan", {"fan": "fan", "speed": 0})
    assert client.sent == ["M106 S128", "M106 S255", "M107"] and client.noted == ["fan"] * 3


def test_generic_fan_and_output_pin(client):
    r = post(client, "fan", {"fan": "fan_generic Exhaust", "speed": 0.25})
    assert r.status_code == 200 and client.sent == ["SET_FAN_SPEED FAN=exhaust SPEED=0.25"]
    r = post(client, "output_pin", {"pin": "output_pin beeper", "value": 1})
    assert r.status_code == 200 and client.sent[-1] == "SET_PIN PIN=beeper VALUE=1"


@pytest.mark.parametrize("path,body,status", [
    ("fan", {"fan": "heater_fan hotend_fan", "speed": 1}, 400),       # not controllable
    ("fan", {"fan": "fan_generic nope", "speed": 1}, 404),
    ("fan", {"fan": "fan", "speed": 1.01}, 400), ("fan", {"fan": "fan", "speed": -0.1}, 400),
    ("fan", {"fan": "fan"}, 400), ("fan", {"fan": "fan_generic exhaust x", "speed": 1}, 400),
    ("output_pin", {"pin": "output_pin missing", "value": 1}, 404),
    ("output_pin", {"pin": "output_pin beeper", "value": 2}, 400),
    ("output_pin", {"pin": "beeper", "value": 1}, 400),               # must name the family
    ("output_pin", {"pin": "output_pin beeper\nM112", "value": 1}, 400),
])
def test_fan_and_pin_validation(client, path, body, status):
    assert post(client, path, body).status_code == status and client.sent == []


# ── speed / flow / PA / retraction ───────────────────────────────────────────
def test_speed_and_flow_bounds(client):
    assert post(client, "speed", {"factor": 120}).status_code == 200
    assert post(client, "flow", {"factor": 95.4}).status_code == 200
    assert client.sent == ["M220 S120", "M221 S95"] and client.noted == ["speed", "flow"]
    for path in ("speed", "flow"):
        for bad in (9, 301, 0, -50, "100", None):
            assert post(client, path, {"factor": bad}).status_code == 400
    assert post(client, "speed", {"factor": 10}).status_code == 200 and post(client, "flow", {"factor": 300}).status_code == 200
    assert len(client.sent) == 4


def test_pressure_advance(client):
    assert post(client, "pressure_advance", {"advance": 0.05}).status_code == 200
    assert post(client, "pressure_advance", {"advance": 0.0425, "smooth_time": 0.04}).status_code == 200
    assert client.sent == ["SET_PRESSURE_ADVANCE ADVANCE=0.05", "SET_PRESSURE_ADVANCE ADVANCE=0.0425 SMOOTH_TIME=0.04"]
    assert client.noted == ["pa", "pa"]
    for body in ({"advance": -0.01}, {"advance": 2.5}, {"advance": 0.1, "smooth_time": 0.3}, {}, {"advance": "0.1"}):
        assert post(client, "pressure_advance", body).status_code == 400
    assert len(client.sent) == 2


def test_retraction_needs_the_capability_and_bounds(client):
    r = post(client, "retraction", {"retract_length": 0.8, "retract_speed": 35, "unretract_extra_length": 0})
    assert r.status_code == 200
    assert client.sent == ["SET_RETRACTION RETRACT_LENGTH=0.8 RETRACT_SPEED=35 UNRETRACT_EXTRA_LENGTH=0"]
    assert client.noted == ["retraction"]
    assert post(client, "retraction", {}).status_code == 400
    assert post(client, "retraction", {"retract_length": 21}).status_code == 400
    assert post(client, "retraction", {"retract_speed": 0}).status_code == 400
    client.mp.setattr(mu, "list_objects", lambda: [o for o in OBJECTS if o != "firmware_retraction"])
    mu.reset_cache()
    r = post(client, "retraction", {"retract_length": 1})
    assert r.status_code == 409 and len(client.sent) == 1


# ── Z offset ──────────────────────────────────────────────────────────────────
def test_babystep_bounds(client):
    assert post(client, "babystep", {"step": 0.01}).status_code == 200
    assert post(client, "babystep", {"step": -0.5}).status_code == 200
    assert client.sent == ["SET_GCODE_OFFSET Z_ADJUST=0.01 MOVE=1", "SET_GCODE_OFFSET Z_ADJUST=-0.5 MOVE=1"]
    assert client.noted == ["z_offset", "z_offset"]
    for bad in (0, 0.51, -0.6, "0.01", None, True):
        assert post(client, "babystep", {"step": bad}).status_code == 400
    assert len(client.sent) == 2


def test_babystep_is_allowed_during_a_print(client):
    go_busy(client)
    assert post(client, "babystep", {"step": 0.02}).status_code == 200


def test_save_z_offset_needs_confirmation_and_says_restart(client):
    r = post(client, "save_z_offset", {"target": "probe"})
    assert r.status_code == 409 and r.get_json()["needs_confirmation"] is True and client.sent == []
    assert post(client, "save_z_offset", {"target": "probe", "confirmed": "yes"}).status_code == 409
    r = post(client, "save_z_offset", {"target": "probe", "confirmed": True})
    body = r.get_json()
    assert r.status_code == 200 and client.sent == ["Z_OFFSET_APPLY_PROBE"]
    assert body["restart_required"] is True and "SAVE_CONFIG" in body["message"] and client.noted == ["z_offset"]
    assert post(client, "save_z_offset", {"target": "endstop", "confirmed": True}).status_code == 200
    assert client.sent[-1] == "Z_OFFSET_APPLY_ENDSTOP"
    assert post(client, "save_z_offset", {"target": "bed", "confirmed": True}).status_code == 400


def test_save_to_probe_requires_a_probe(client):
    client.mp.setattr(mu, "list_objects", lambda: [o for o in OBJECTS if o != "probe"])
    mu.reset_cache()
    assert post(client, "save_z_offset", {"target": "probe", "confirmed": True}).status_code == 409
    assert post(client, "save_z_offset", {"target": "endstop", "confirmed": True}).status_code == 200


# ── motors off / leveling ─────────────────────────────────────────────────────
def test_motors_off_and_busy_refusal(client):
    assert post(client, "motors_off").status_code == 200 and client.sent == ["M84"]
    go_busy(client)
    r = post(client, "motors_off")
    assert r.status_code == 409 and r.get_json()["print_active"] is True and client.sent == ["M84"]


def test_leveling_actions_need_the_capability(client):
    assert post(client, "level", {"action": "z_tilt_adjust"}).status_code == 200
    assert client.sent == ["Z_TILT_ADJUST"]
    assert post(client, "level", {"action": "PROBE_CALIBRATE"}).status_code == 200
    for action in ("QUAD_GANTRY_LEVEL", "SCREWS_TILT_CALCULATE", "BED_SCREWS_ADJUST"):
        r = post(client, "level", {"action": action})
        assert r.status_code == 409 and "not available" in r.get_json()["error"]
    assert client.sent == ["Z_TILT_ADJUST", "PROBE_CALIBRATE"]
    assert client.noted == []                                   # leveling is not a quality-controller family


def test_manual_probe_dialog_actions(client):
    assert post(client, "level", {"action": "TESTZ", "z": -0.1}).status_code == 200
    assert post(client, "level", {"action": "TESTZ", "z": "--"}).status_code == 200
    assert post(client, "level", {"action": "ACCEPT"}).status_code == 200
    assert post(client, "level", {"action": "ABORT"}).status_code == 200
    assert client.sent == ["TESTZ Z=-0.1", "TESTZ Z=--", "ACCEPT", "ABORT"]
    for body in ({"action": "TESTZ"}, {"action": "TESTZ", "z": 6}, {"action": "TESTZ", "z": "+x"},
                 {"action": "TESTZ", "z": "1\nM112"}, {"action": "M112"}, {"action": "G28"}, {}, {"action": 5}):
        assert post(client, "level", body).status_code == 400
    assert len(client.sent) == 4


def test_leveling_refused_while_printing_and_without_manual_probe(client):
    go_busy(client)
    for action in ("Z_TILT_ADJUST", "PROBE_CALIBRATE", "TESTZ", "ACCEPT", "ABORT"):
        r = post(client, "level", {"action": action, "z": 0.1})
        assert r.status_code == 409 and r.get_json()["print_active"] is True
    assert client.sent == []
    client.mp.setattr(printer, "_printer_is_busy", lambda: False)
    client.mp.setattr(mu, "list_objects", lambda: ["extruder", "heater_bed"])
    mu.reset_cache()
    assert post(client, "level", {"action": "ACCEPT"}).status_code == 409


# ── extrude ───────────────────────────────────────────────────────────────────
def test_extrude_script_is_relative_and_restores_state(client):
    r = post(client, "extrude", {"amount": 10, "feedrate": 120})
    assert r.status_code == 200
    assert client.sent == ["SAVE_GCODE_STATE NAME=INDUS_EXTRUDE\nM83\nG1 E10 F120\nRESTORE_GCODE_STATE NAME=INDUS_EXTRUDE"]
    post(client, "extrude", {"amount": -5.5})
    assert "G1 E-5.5 F300" in client.sent[-1]


@pytest.mark.parametrize("body", [{"amount": 100.1}, {"amount": -101}, {"amount": 0}, {"amount": "5"}, {},
                                  {"amount": 5, "feedrate": 10}, {"amount": 5, "feedrate": 3001},
                                  {"amount": 5, "feedrate": "fast"}, {"amount": True}])
def test_extrude_bounds(client, body):
    assert post(client, "extrude", body).status_code == 400 and client.sent == []


def test_extrude_boundaries_are_accepted(client):
    assert post(client, "extrude", {"amount": 100, "feedrate": 3000}).status_code == 200
    assert post(client, "extrude", {"amount": -100, "feedrate": 30}).status_code == 200


def test_cold_extrusion_and_busy_refused(client):
    client.mp.setattr(mu, "query_objects", lambda names: {"extruder": {"can_extrude": False}})
    r = post(client, "extrude", {"amount": 5})
    assert r.status_code == 409 and r.get_json()["cold"] is True and client.sent == []
    client.mp.setattr(mu, "query_objects", lambda names: {})                    # unknown: refuse rather than guess
    assert post(client, "extrude", {"amount": 5}).status_code == 409
    client.mp.setattr(mu, "query_objects", lambda names: {"extruder": {"can_extrude": True}})
    go_busy(client)
    assert post(client, "extrude", {"amount": 5}).status_code == 409 and client.sent == []


# ── Moonraker down (502) ──────────────────────────────────────────────────────
@pytest.mark.parametrize("path,body", [
    ("heater", {"heater": "extruder", "target": 100}), ("fan", {"speed": 1}), ("speed", {"factor": 100}),
    ("flow", {"factor": 100}), ("pressure_advance", {"advance": 0.1}), ("babystep", {"step": 0.01}),
    ("motors_off", {}), ("level", {"action": "Z_TILT_ADJUST"}), ("extrude", {"amount": 5}),
    ("save_z_offset", {"target": "endstop", "confirmed": True}),
    ("output_pin", {"pin": "output_pin beeper", "value": 1}), ("retraction", {"retract_length": 1}),
])
def test_moonraker_down_is_a_502_and_the_arbiter_is_not_told(client, path, body):
    moonraker_down(client)
    client.mp.setattr(mu, "list_objects", lambda: (_ for _ in ()).throw(mu.MoonrakerError("Moonraker unreachable: down")))
    client.mp.setattr(mu, "heater_limits", lambda: (_ for _ in ()).throw(mu.MoonrakerError("Moonraker unreachable: down")))
    client.mp.setattr(mu, "query_objects", lambda names: (_ for _ in ()).throw(mu.MoonrakerError("Moonraker unreachable: down")))
    r = post(client, path, body)
    assert r.status_code == 502 and "unreachable" in r.get_json()["error"] and client.noted == []


def test_502_when_only_the_script_post_fails(client):
    moonraker_down(client)
    r = post(client, "speed", {"factor": 100})
    assert r.status_code == 502 and client.noted == []


def test_klipper_rejection_is_a_422_without_arbiter(client):
    class Err:
        ok = False
        text = "Unknown command"
    client.mp.setattr(mu, "run_script", lambda *a, **k: Err())
    r = post(client, "flow", {"factor": 100})
    assert r.status_code == 422 and "Unknown command" in r.get_json()["detail"] and client.noted == []


# ── simulator branch ──────────────────────────────────────────────────────────
def test_simulator_injects_instead_of_calling_moonraker(client):
    sim = go_sim(client)
    client.mp.setattr(mu, "list_objects", lambda: (_ for _ in ()).throw(AssertionError("no Moonraker in the simulator")))
    client.mp.setattr(mu, "heater_limits", lambda: (_ for _ in ()).throw(AssertionError("no Moonraker in the simulator")))
    calls = [("heater", {"heater": "extruder", "target": 200}), ("heater", {"heater": "heater_bed", "target": 60}),
             ("fan", {"fan": "fan", "speed": 1}), ("fan", {"fan": "fan_generic aux", "speed": 0.5}),
             ("output_pin", {"pin": "output_pin led", "value": 1}), ("speed", {"factor": 110}),
             ("flow", {"factor": 98}), ("pressure_advance", {"advance": 0.04}), ("retraction", {"retract_length": 1}),
             ("babystep", {"step": -0.05}), ("save_z_offset", {"target": "probe", "confirmed": True}),
             ("motors_off", {}), ("level", {"action": "QUAD_GANTRY_LEVEL"}), ("extrude", {"amount": 5})]
    for path, body in calls:
        r = post(client, path, body)
        assert r.status_code == 200 and r.get_json()["simulated"] is True, path
    assert len(sim.injected) == len(calls) and client.sent == []
    assert sim.injected[0] == "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=200"
    assert "nozzle_temp" in client.noted and "z_offset" in client.noted and "retraction" in client.noted


def test_simulator_still_validates_and_bounds(client):
    sim = go_sim(client)
    assert post(client, "heater", {"heater": "extruder", "target": 296}).status_code == 400      # sim max 300 - margin
    assert post(client, "heater", {"heater": "heater_bed", "target": 126}).status_code == 400
    assert post(client, "heater", {"heater": "extruder; M112", "target": 1}).status_code == 400
    assert post(client, "fan", {"fan": "fan_generic a b", "speed": 1}).status_code == 400
    assert post(client, "speed", {"factor": 5}).status_code == 400
    go_busy(client)
    assert post(client, "extrude", {"amount": 5}).status_code == 409
    assert post(client, "level", {"action": "Z_TILT_ADJUST"}).status_code == 409
    assert sim.injected == []


# ── wiring ────────────────────────────────────────────────────────────────────
def test_registered_in_the_app_behind_the_auth_gate():
    from api import server
    rules = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/v1/printer/adjust/heater" in rules and "/api/v1/printer/adjust/extrude" in rules
    c = server.app.test_client()
    # the global gate runs before any blueprint: with auth required and no session the request is a 401
    import api.auth as auth
    orig = auth.auth_required
    try:
        auth.auth_required = lambda: True
        r = c.post(f"{URL}/speed", json={"factor": 100}, environ_base={"REMOTE_ADDR": "127.0.0.9"})
        assert r.status_code == 401
    finally:
        auth.auth_required = orig


def test_no_adjust_endpoint_takes_raw_gcode_from_the_client():
    import inspect
    src = inspect.getsource(adjust)
    assert "request.json" not in src and 'data.get("command")' not in src and 'data.get("gcode")' not in src
