"""Phase-0 control foundations: Moonraker helpers, typed macro endpoint, Klipper status poller,
UI rate-limit category, arbiter manual override, jog script."""
import time

import pytest
import requests
from flask import Flask

from api import moonraker_util as mu
from api import printer_status as ps
from api import rate_limiter as rl

OBJECTS = ["extruder", "extruder1", "heater_bed", "heater_generic chamber", "temperature_sensor mcu",
           "temperature_fan pi_fan", "fan", "heater_fan hotend_fan", "fan_generic exhaust", "output_pin beeper",
           "probe", "z_tilt", "firmware_retraction", "gcode_move", "toolhead", "configfile",
           "gcode_macro PAUSE", "gcode_macro BED_CRASH_RESUME", "gcode_macro _HIDDEN", "gcode_macro Load_Filament"]


@pytest.fixture(autouse=True)
def fresh():
    mu.reset_cache()
    ps.reset()
    yield
    mu.reset_cache()
    ps.reset()


@pytest.fixture
def objects(monkeypatch):
    monkeypatch.setattr(mu, "list_objects", lambda: list(OBJECTS))
    return OBJECTS


# ── moonraker_util ─────────────────────────────────────────────────────────────
def test_macro_script_builder_accepts_plain_parameters():
    assert mu.build_macro_script("SET_BED_CRASH_THRESHOLD", {"value": 2500}) == "SET_BED_CRASH_THRESHOLD VALUE=2500"
    assert mu.build_macro_script("M", {"a": True, "b": "x.y-1"}) == "M A=1 B=x.y-1"
    assert mu.build_macro_script("PAUSE", None) == "PAUSE"


@pytest.mark.parametrize("name,params", [
    ("PAUSE\nM112", None), ("A B", None), ("", None), ("x;y", None),
    ("M", {"bad key": 1}), ("M", {"K": "a b"}), ("M", {"K": "1\nM112"}), ("M", {"K": "a;b"}),
    ("M", {"K": "x" * 65}), ("M", {"1K": 1}), ("M", {"K": "{x}"}), ("M", {"K": '"q"'}),
])
def test_macro_script_builder_rejects_injection(name, params):
    with pytest.raises(ValueError):
        mu.build_macro_script(name, params)


def test_valid_name_is_case_insensitive_and_only_for_known_objects(objects):
    assert mu.valid_name("gcode_macro", "load_filament") == "Load_Filament"
    assert mu.valid_name("output_pin", "BEEPER") == "beeper"
    assert mu.valid_name("gcode_macro", "FORMAT_DISK") is None
    assert mu.valid_name("output_pin", "PAUSE") is None                    # right name, wrong family
    assert mu.valid_name("gcode_macro", "") is None and mu.valid_name("gcode_macro", None) is None
    assert mu.macro_names() == ["BED_CRASH_RESUME", "Load_Filament", "PAUSE", "_HIDDEN"]


def test_query_objects_url_encodes_names(monkeypatch):
    seen = {}

    class R:
        ok = True
        status_code = 200

        def json(self):
            return {"result": {"status": {"heater_generic chamber": {"temperature": 30}}}}

    monkeypatch.setattr(mu.requests, "get", lambda u, timeout=None: (seen.setdefault("url", u), R())[1])
    out = mu.query_objects(["extruder", "heater_generic chamber"])
    assert seen["url"].endswith("/printer/objects/query?extruder&heater_generic%20chamber")
    assert out["heater_generic chamber"]["temperature"] == 30
    assert mu.query_objects([]) == {}


def test_moonraker_errors_become_moonraker_error(monkeypatch):
    monkeypatch.setattr(mu.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    with pytest.raises(mu.MoonrakerError, match="unreachable"):
        mu.list_objects()

    class Bad:
        ok = False
        status_code = 503
    monkeypatch.setattr(mu.requests, "get", lambda *a, **k: Bad())
    mu.reset_cache()
    with pytest.raises(mu.MoonrakerError, match="503"):
        mu.list_objects()


def test_object_list_is_cached(monkeypatch):
    calls = []

    class R:
        ok = True

        def json(self):
            return {"result": {"objects": ["extruder"]}}
    monkeypatch.setattr(mu.requests, "get", lambda *a, **k: (calls.append(1), R())[1])
    mu.list_objects()
    mu.list_objects()
    assert len(calls) == 1


def test_heater_limits_from_configfile(monkeypatch):
    cfg = {"configfile": {"settings": {
        "extruder": {"min_temp": 0, "max_temp": 285}, "heater_bed": {"min_temp": 0, "max_temp": 120},
        "heater_generic chamber": {"min_temp": 0, "max_temp": 70}, "fan": {"pin": "x"},
        "extruder1": {"min_temp": 0}}}}
    monkeypatch.setattr(mu, "get_json", lambda path, timeout=5: {"status": cfg})
    assert mu.heater_limits() == {"extruder": {"min_temp": 0.0, "max_temp": 285.0},
                                  "heater_bed": {"min_temp": 0.0, "max_temp": 120.0},
                                  "heater_generic chamber": {"min_temp": 0.0, "max_temp": 70.0}}


# ── status poller ─────────────────────────────────────────────────────────────────
def test_classification_and_capabilities():
    g = ps.classify(OBJECTS)
    assert g["heaters"] == ["extruder", "extruder1", "heater_bed", "heater_generic chamber"]
    assert g["sensors"] == ["temperature_sensor mcu", "temperature_fan pi_fan"]
    assert g["fans"] == ["fan", "heater_fan hotend_fan", "fan_generic exhaust"]
    assert g["outputs"] == ["output_pin beeper"]
    assert "toolhead" not in sum(g.values(), []) and "configfile" not in sum(g.values(), [])
    cap = ps.capabilities(OBJECTS, g)
    assert cap["probe"] and cap["z_tilt"] and cap["firmware_retraction"]
    assert not cap["quad_gantry_level"] and not cap["screws_tilt_adjust"]
    assert cap["extruders"] == ["extruder", "extruder1"]
    assert cap["tool_macros"]["load_filament"] == "LOAD_FILAMENT"             # matched case-insensitively
    assert cap["tool_macros"]["clean_nozzle"] is None


def test_snapshot_queries_moonraker_once_per_ttl(monkeypatch, objects):
    queries = []
    monkeypatch.setattr(mu, "query_objects", lambda names: (queries.append(names), {"extruder": {"temperature": 200}})[1])
    monkeypatch.setattr(mu, "heater_limits", lambda: {"extruder": {"min_temp": 0, "max_temp": 285}})
    a = ps.snapshot()
    b = ps.snapshot()
    assert a is b and len(queries) == 1
    assert "toolhead" not in queries[0] and "heater_generic chamber" in queries[0]
    assert a["limits"]["extruder"]["max_temp"] == 285 and a["status"]["extruder"]["temperature"] == 200
    time.sleep(ps.TTL_S + 0.05)
    ps.snapshot()
    assert len(queries) == 2


def test_snapshot_survives_missing_limits(monkeypatch, objects):
    monkeypatch.setattr(mu, "query_objects", lambda names: {})
    monkeypatch.setattr(mu, "heater_limits", lambda: (_ for _ in ()).throw(mu.MoonrakerError("no")))
    assert ps.snapshot()["limits"] == {}


# ── routes ──────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, objects):
    from api.routes import printer
    import workers
    monkeypatch.setattr(workers, "_active_worker", None)
    monkeypatch.setattr(printer, "_printer_is_busy", lambda: False)
    sent = []

    class R:
        ok = True
        text = ""
    monkeypatch.setattr(mu, "run_script", lambda script, timeout=10: (sent.append(script), R())[1])
    app = Flask(__name__)
    app.register_blueprint(printer.printer_bp, url_prefix="/api/v1/printer")
    c = app.test_client()
    c.sent, c.printer, c.R = sent, printer, R
    return c


def test_macro_runs_known_macro_with_canonical_name(client):
    r = client.post("/api/v1/printer/macro/load_filament", json={"params": {"temp": 215}})
    assert r.status_code == 200 and r.get_json()["macro"] == "Load_Filament"
    assert client.sent == ["Load_Filament TEMP=215"]


def test_macro_unknown_name_and_bad_params(client):
    assert client.post("/api/v1/printer/macro/FORMAT_DISK").status_code == 404
    assert client.post("/api/v1/printer/macro/M112").status_code == 404           # not a macro: no way to reach raw G-code
    assert client.post("/api/v1/printer/macro/PAUSE", json={"params": {"x": "1\nM112"}}).status_code == 400
    assert client.post("/api/v1/printer/macro/PAUSE", json={"params": [1]}).status_code == 400
    assert client.sent == []


def test_macro_during_print_needs_confirmation_except_pause_resume(client, monkeypatch):
    monkeypatch.setattr(client.printer, "_printer_is_busy", lambda: True)
    r = client.post("/api/v1/printer/macro/BED_CRASH_RESUME")
    assert r.status_code == 409 and r.get_json()["needs_confirmation"] is True and client.sent == []
    assert client.post("/api/v1/printer/macro/BED_CRASH_RESUME", json={"confirmed": True}).status_code == 200
    assert client.post("/api/v1/printer/macro/PAUSE").status_code == 200
    assert client.post("/api/v1/printer/macro/BED_CRASH_RESUME", json={"confirmed": "yes"}).status_code == 409


def test_macro_errors_from_klipper_and_moonraker(client, monkeypatch):
    class Err:
        ok = False
        text = "Unknown command"
    monkeypatch.setattr(mu, "run_script", lambda *a, **k: Err())
    r = client.post("/api/v1/printer/macro/PAUSE")
    assert r.status_code == 422 and "Unknown command" in r.get_json()["detail"]
    monkeypatch.setattr(mu, "run_script", lambda *a, **k: (_ for _ in ()).throw(mu.MoonrakerError("down")))
    assert client.post("/api/v1/printer/macro/PAUSE").status_code == 502
    monkeypatch.setattr(mu, "list_objects", lambda: (_ for _ in ()).throw(mu.MoonrakerError("down")))
    mu.reset_cache()
    assert client.post("/api/v1/printer/macro/PAUSE").status_code == 502


def test_macro_in_simulator_injects_instead_of_calling_moonraker(client, monkeypatch):
    import workers

    class Sim:
        def __init__(self):
            self.injected = []

        def inject_gcode(self, s):
            self.injected.append(s)
    sim = Sim()
    monkeypatch.setattr(workers, "_active_worker", sim)
    r = client.post("/api/v1/printer/macro/anything", json={"params": {"a": 1}})
    assert r.status_code == 200 and r.get_json()["simulated"] is True
    assert sim.injected == ["anything A=1"] and client.sent == []


def test_status_route(client, monkeypatch):
    monkeypatch.setattr(mu, "query_objects", lambda names: {"fan": {"speed": 0.5}})
    monkeypatch.setattr(mu, "heater_limits", lambda: {})
    d = client.get("/api/v1/printer/status").get_json()
    assert d["ok"] and d["status"]["fan"]["speed"] == 0.5 and "BED_CRASH_RESUME" in d["capabilities"]["macros"]
    monkeypatch.setattr(mu, "query_objects", lambda names: (_ for _ in ()).throw(mu.MoonrakerError("down")))
    ps.reset()
    r = client.get("/api/v1/printer/status")
    assert r.status_code == 502 and r.get_json()["ok"] is False


# ── rate limiter ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def limited():
    rl._requests.clear(); rl._bans.clear(); rl._violations.clear()
    app = Flask(__name__)
    rl.check_rate_limit(app)
    for path in ("/api/v1/control/jog", "/api/v1/control/execute", "/api/v1/printer/macro/X",
                 "/api/v1/printer/gcode", "/api/v1/printer/adjust/fan", "/api/v1/printer/restart",
                 "/api/v1/control/home"):
        app.add_url_rule(path, path, lambda: "ok", methods=["POST"])
    yield app.test_client()
    rl._requests.clear(); rl._bans.clear(); rl._violations.clear()


def post(c, path, ip="9.9.9.1"):
    return c.post(path, environ_base={"REMOTE_ADDR": ip})


def test_interactive_paths_use_the_higher_limit(limited):
    for path in ("/api/v1/control/jog", "/api/v1/control/execute", "/api/v1/printer/macro/X",
                 "/api/v1/printer/gcode", "/api/v1/printer/adjust/fan"):
        for _ in range(30):
            assert post(limited, path, ip="9.9.9.2").status_code == 200
        rl._requests.clear()
    for _ in range(11):                                                       # 11 jogs in a minute used to be a 429
        assert post(limited, "/api/v1/control/jog", ip="9.9.9.3").status_code == 200


def test_ui_adjust_limit_is_a_429_that_never_bans(limited):
    lim = rl._LIMITS["ui_adjust"][0]
    for _ in range(lim):
        assert post(limited, "/api/v1/control/jog", ip="9.9.9.4").status_code == 200
    for _ in range(10):                                                       # far more than 3 violations
        r = post(limited, "/api/v1/control/jog", ip="9.9.9.4")
        assert r.status_code == 429 and r.get_json()["category"] == "ui_adjust"
    assert "9.9.9.4" not in rl._bans
    rl._requests.clear()
    assert post(limited, "/api/v1/control/jog", ip="9.9.9.4").status_code == 200   # recovers, no ban


def test_destructive_paths_keep_the_strict_limit_but_only_login_bans(limited):
    lim = rl._LIMITS["hardware_cmd"][0]
    assert lim < rl._LIMITS["ui_adjust"][0]
    for path in ("/api/v1/printer/restart", "/api/v1/control/home"):
        rl._requests.clear()
        codes = [post(limited, path, ip="9.9.9.5").status_code for _ in range(lim + 1)]
        assert codes[:lim] == [200] * lim and codes[lim] == 429
    for _ in range(5):
        post(limited, "/api/v1/printer/restart", ip="9.9.9.5")
    assert "9.9.9.5" not in rl._bans                                          # operators are never locked out of the printer


# ── arbiter ──────────────────────────────────────────────────────────────────────────
def test_manual_override_makes_the_controller_yield_then_expire():
    from plugins.arbiter import Arbiter, family_of
    a = Arbiter(external=set(), yield_s=30)
    ctx = {"now": time.time()}
    assert a.filter(["M221 S90"], ctx) == ["M221 S90"]
    until = a.manual_override("flow", detail="slider")
    assert until > time.time() + 29
    ctx = {"now": time.time()}
    assert a.filter(["M221 S90", "M106 S255"], ctx) == ["M106 S255"]          # only the flow family yields
    assert ctx["vetoes"][0]["command"] == "M221 S90"
    ctx = {"now": time.time() + 31}
    assert a.filter(["M221 S90"], ctx) == ["M221 S90"]
    assert a.events[0]["manual"] is True and "slider" in a.events[0]["detail"]
    assert a.manual_override("fan", seconds=5) < time.time() + 6
    assert a.status()["yielding"].keys() >= {"flow", "fan"}


def test_manual_override_never_shortens_an_existing_yield():
    from plugins.arbiter import Arbiter
    a = Arbiter(external=set(), yield_s=60)
    long_until = a.manual_override("pa")
    assert a.manual_override("pa", seconds=1) == long_until


def test_new_families_and_helper():
    from plugins import arbiter as ab
    assert ab.family_of("SET_GCODE_OFFSET Z_ADJUST=0.01") == "z_offset"
    assert ab.family_of("M140 S60") == "bed_temp" and ab.family_of("SET_FAN_SPEED FAN=x SPEED=1") == "fan"
    assert ab.note_manual_change("speed", 1) is not None


# ── jog script ────────────────────────────────────────────────────────────────────────
def test_jog_wraps_motion_in_saved_state_and_forces_relative_extrusion(monkeypatch):
    from api import server
    scripts = []
    monkeypatch.setattr(server, "_worker", lambda: None)
    monkeypatch.setattr(server, "_run_managed_gcode", lambda s: (scripts.append(s), {"status": "ok"})[1])
    r = server.app.test_client().post("/api/v1/control/jog", json={"e": 5, "feedrate": 300},
                                      environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    lines = scripts[0].splitlines()
    assert lines[0] == "SAVE_GCODE_STATE NAME=INDUS_JOG" and lines[-1] == "RESTORE_GCODE_STATE NAME=INDUS_JOG"
    assert lines.index("G91") < lines.index("M83") < next(i for i, l in enumerate(lines) if l.startswith("G1 E5.000"))
