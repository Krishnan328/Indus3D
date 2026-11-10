"""Renders the KAMP / PRINT_START / PRINT_END Klipper macros with Jinja (configured like Klipper's:
single-brace expressions) against a mock `printer`, and runs the emitted G-code through a small
interpreter. No printer is needed."""
import ast
import configparser
import math
import re
from pathlib import Path

import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[2]
CFG_FILES = ["kamp/KAMP_Settings.cfg", "kamp/Adaptive_Mesh.cfg", "kamp/Adaptive_Purge.cfg",
             "kamp/Smart_Park.cfg", "print_start_end.cfg"]


class MacroError(Exception):
    pass


def square(x0, y0, x1, y1):
    return {"name": "part", "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


class Printer:
    def __init__(self, files=CFG_FILES, probe="eddy", bed=True, can_extrude=True, homed="xyz",
                 objects=None, filament_d=None, crash=None, sensors=None, bed_mesh=True,
                 limits=((0, 0, 0), (235, 235, 250)), pos=(100.0, 100.0, 30.0), kamp_vars=None, mesh_cfg=True):
        (x0, y0, z0), (x1, y1, z1) = limits
        raw = {}
        settings = {"extruder": {}}
        if filament_d:
            settings["extruder"]["filament_diameter"] = filament_d
        if bed_mesh:
            raw["bed_mesh"] = {}
            if mesh_cfg:
                settings["bed_mesh"] = {"mesh_min": (30.0, 20.0), "mesh_max": (210.0, 215.0)}
        if probe == "eddy":
            raw["probe_eddy_current my_eddy"] = {}
            settings["probe_eddy_current my_eddy"] = {"x_offset": 0.0, "y_offset": 20.0}
        elif probe == "probe":
            raw["probe"] = {}
            settings["probe"] = {"x_offset": -20.0, "y_offset": -10.0}
        for name, state in (sensors or {}).items():
            raw[name] = {}
        self.status = {
            "toolhead": {"homed_axes": homed, "position": dict(zip("xyz", pos)),
                         "axis_minimum": {"x": x0, "y": y0, "z": z0}, "axis_maximum": {"x": x1, "y": y1, "z": z1}},
            "extruder": {"target": 210.0, "temperature": 209.0, "can_extrude": can_extrude},
            "exclude_object": {"objects": objects or []},
            "configfile": {"config": raw, "settings": settings},
            "fan": {"speed": 0.5},
            "bed_mesh": {},
        }
        if can_extrude is None:
            del self.status["extruder"]["can_extrude"]
        if bed:
            self.status["heater_bed"] = {"target": 60.0, "temperature": 59.0}
        for name, state in (sensors or {}).items():
            self.status[name] = {"filament_detected": state}
        if crash is not None:
            self.status["gcode_macro _BED_HUB_VARS"] = {"crash_active": crash}
        self.macros = {}
        self.out = []
        self.env = jinja2.Environment("{%", "%}", "{", "}")
        for f in files:
            self._load(ROOT / f)
        if kamp_vars:
            self.status["gcode_macro _KAMP_Settings"].update(kamp_vars)
        self.moves = []
        self.abs_xy = True
        self.abs_e = True
        self.stack = []
        self.pos = dict(zip("xyz", pos))

    def add_macro(self, name, body):
        self.macros[name] = self.env.from_string(body)

    def _load(self, path):
        cp = configparser.RawConfigParser(strict=False)
        cp.read(path)
        for sec in cp.sections():
            if sec.startswith("gcode_macro "):
                name = sec.split(" ", 1)[1]
                variables = {k[len("variable_"):]: ast.literal_eval(v) for k, v in cp.items(sec) if k.startswith("variable_")}
                self.macros[name.upper()] = self.env.from_string(cp.get(sec, "gcode"))
                self.status[f"gcode_macro {name}"] = variables

    def run(self, name, rawparams="", fail_on=None):
        params = {k.upper(): v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', rawparams)}

        def raise_error(msg):
            raise MacroError(msg)
        text = self.macros[name.upper()].render(printer=self.status, params=params, rawparams=rawparams,
                                                action_raise_error=raise_error,
                                                action_respond_info=lambda m: self.out.append("// " + m) or "")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cmd, _, rest = line.partition(" ")
            if cmd.upper() in self.macros:
                self.run(cmd, rest)
                continue
            self.out.append(line)
            self._exec(cmd, rest, line)
        return self.out

    def _exec(self, cmd, rest, line):
        if cmd == "G90":
            self.abs_xy = True
        elif cmd == "G91":
            self.abs_xy = False
        elif cmd == "M82":
            self.abs_e = True
        elif cmd == "M83":
            self.abs_e = False
        elif cmd == "SAVE_GCODE_STATE":
            self.stack.append((self.abs_xy, self.abs_e))
        elif cmd == "RESTORE_GCODE_STATE":
            self.abs_xy, self.abs_e = self.stack.pop()
        elif cmd == "G1":
            a = {k: float(v) for k, v in re.findall(r"([XYZEF])(-?[\d.]+)", rest)}
            before = dict(self.pos)
            for ax in "xyz":
                if ax.upper() in a:
                    self.pos[ax] = a[ax.upper()] if self.abs_xy else self.pos[ax] + a[ax.upper()]
            self.moves.append({"line": line, "a": a, "before": before, "after": dict(self.pos), "rel_e": not self.abs_e})

    def has(self, prefix):
        return any(l.startswith(prefix) for l in self.out)

    def index(self, prefix):
        return next(i for i, l in enumerate(self.out) if l.startswith(prefix))

    def info(self):
        return " ".join(l for l in self.out if l.startswith("//"))


def purge(**kw):
    p = Printer(**kw)
    p.run("LINE_PURGE")
    return p


def purge_move(p):
    return next(m for m in p.moves if "E" in m["a"] and m["a"]["E"] > 0)


def flow_of(p, fil_d=1.75):
    m = purge_move(p)
    dist = math.dist([m["before"][k] for k in "xyz"], [m["after"][k] for k in "xyz"])
    vol = math.pi * (fil_d / 2) ** 2 * m["a"]["E"]
    return vol / (dist / (m["a"]["F"] / 60.0))


# ── repository layout ──────────────────────────────────────────────────────
def test_exactly_one_copy_of_each_macro_file():
    names = {"Adaptive_Mesh.cfg", "Adaptive_Purge.cfg", "KAMP_Settings.cfg", "Smart_Park.cfg", "print_start_end.cfg"}
    found = []
    for p in ROOT.rglob("*.cfg"):
        rel = p.relative_to(ROOT)
        if any(part in (".git", "node_modules", ".claude") for part in rel.parts):
            continue
        if p.name in names:
            found.append(str(rel))
    assert sorted(found) == sorted(["kamp/Adaptive_Mesh.cfg", "kamp/Adaptive_Purge.cfg", "kamp/KAMP_Settings.cfg",
                                    "kamp/Smart_Park.cfg", "print_start_end.cfg"])


def test_installer_copy_sources_exist():
    text = (ROOT / "integrations/kiauh/indus3d_installer.sh").read_text()
    sources = set(re.findall(r'\$\{INSTALL_DIR\}/(kamp|print_start_end\.cfg)', text))
    assert sources == {"kamp", "print_start_end.cfg"}
    assert (ROOT / "kamp").is_dir() and (ROOT / "print_start_end.cfg").is_file()
    cfg = (ROOT / "indus3d.cfg").read_text()
    for f in ("KAMP_Settings", "Adaptive_Mesh", "Adaptive_Purge", "Smart_Park"):
        assert (ROOT / "kamp" / f"{f}.cfg").is_file() and f"[include kamp/{f}.cfg]" in cfg


# ── adaptive mesh ───────────────────────────────────────────────────────────
def mesh(rawparams="", **kw):
    p = Printer(**kw)
    p.run("BED_MESH_CALIBRATE", rawparams)
    return p


def base_line(p):
    return next(l for l in p.out if l.startswith("_BED_MESH_CALIBRATE_BASE"))


def test_default_method_never_passes_rapid_scan():
    p = mesh(objects=[square(100, 100, 140, 140)])
    assert "METHOD" not in base_line(p)


def test_rapid_scan_opt_in_with_eddy_probe():
    p = mesh(objects=[square(100, 100, 140, 140)], kamp_vars={"probe_method": "rapid_scan"})
    assert "METHOD=rapid_scan" in base_line(p)


def test_rapid_scan_falls_back_with_normal_probe_and_no_probe():
    for probe in ("probe", "none"):
        p = mesh(objects=[square(100, 100, 140, 140)], probe=probe, kamp_vars={"probe_method": "rapid_scan"})
        assert "METHOD" not in base_line(p)
        assert "not supported" in p.info()


def test_explicit_rapid_scan_param_is_dropped_without_eddy_and_not_duplicated_with_eddy():
    p = mesh("METHOD=rapid_scan", probe="probe", objects=[square(100, 100, 140, 140)])
    assert "METHOD" not in base_line(p)
    p = mesh("METHOD=rapid_scan", objects=[square(100, 100, 140, 140)])
    assert base_line(p).count("METHOD=") == 1


def test_mesh_bounds_come_from_bed_mesh_config_and_probe_offsets():
    # object nozzle bounds 100..140; eddy y_offset +20 -> probe y 115..145 (+-5 margin)
    p = mesh(objects=[square(100, 100, 140, 140)])
    assert "MESH_MIN=95.0,115.0" in base_line(p) and "MESH_MAX=145.0,165.0" in base_line(p)
    # object outside the configured mesh area is clamped to mesh_min/mesh_max (30,20)-(210,215)
    p = mesh(objects=[square(0, 0, 300, 300)])
    assert "MESH_MIN=30.0,20.0" in base_line(p) and "MESH_MAX=210.0,215.0" in base_line(p)


def test_mesh_bounds_fall_back_to_axis_limits_without_mesh_min():
    p = mesh(objects=[square(0, 0, 400, 400)], mesh_cfg=False, probe="probe")   # offsets -20,-10
    assert "MESH_MIN=-20.0,-10.0" in base_line(p) and "MESH_MAX=215.0,225.0" in base_line(p)


def test_optional_overrides_win_over_auto_bounds():
    p = mesh(objects=[square(0, 0, 300, 300)], kamp_vars={"mesh_min_x": 50.0, "mesh_max_y": 180.0})
    assert "MESH_MIN=50.0,20.0" in base_line(p) and "MESH_MAX=210.0,180.0" in base_line(p)


def test_empty_exclude_object_falls_back_to_full_bed_mesh():
    p = mesh("PROFILE=x", objects=[])
    line = base_line(p)
    assert "MESH_MIN" not in line and "PROFILE=x" in line


def test_object_without_polygon_is_treated_as_empty():
    p = mesh(objects=[{"name": "a"}])
    assert "MESH_MIN" not in base_line(p)


# ── line purge ──────────────────────────────────────────────────────────────
def test_purge_flow_never_exceeds_the_setting():
    for flow in (3.0, 12.0, 25.0):
        for fd in (1.75, 2.85):
            p = purge(objects=[square(100, 100, 140, 140)], filament_d=fd, kamp_vars={"flow_rate": flow})
            assert flow_of(p, fd) <= flow + 1e-6, (flow, fd)


def test_purge_flow_is_exact_below_the_speed_cap():
    p = purge(objects=[square(100, 100, 140, 140)], kamp_vars={"flow_rate": 5.0})
    assert flow_of(p) == pytest.approx(5.0, rel=1e-3)


def test_default_filament_diameter_is_1_75_and_old_bug_is_gone():
    p = purge(objects=[square(100, 100, 140, 140)])        # defaults: flow 12, 25 mm over 30 mm
    assert flow_of(p) <= 12.0 + 1e-6
    assert purge_move(p)["a"]["F"] != 12 * 60


def test_purge_targets_stay_inside_axis_limits():
    p = purge(objects=[square(180, 180, 230, 230)], limits=((0, 0, 0), (235, 235, 250)))
    for m in p.moves:
        for ax in "xyz":
            assert 0 <= m["after"][ax] <= {"x": 235, "y": 235, "z": 250}[ax], m["line"]
    p = purge(objects=[], limits=((10, 10, 0), (120, 120, 100)), pos=(60, 60, 30))
    for m in p.moves:
        assert 10 <= m["after"]["x"] <= 120 and 10 <= m["after"]["y"] <= 120


def test_purge_does_not_overlap_the_model_when_clamped():
    # model starts 12 mm from the edge: margin 8 would push the line to y=10, 2 mm from the model
    p = purge(objects=[square(60, 12, 100, 60)])
    m = purge_move(p)
    ys = {m["after"]["y"]} | {mv["after"]["y"] for mv in p.moves if "E" in mv["a"] or "Z" in mv["a"]}
    wipe = [mv for mv in p.moves if mv["a"].get("F") == 9000][0]
    ys = (min(m["after"]["y"], wipe["after"]["y"]), max(m["after"]["y"], wipe["after"]["y"]))
    xs = (m["before"]["x"], wipe["after"]["x"])
    hit = xs[1] > 60 and xs[0] < 100 and ys[1] > 12 and ys[0] < 60
    assert not hit
    assert "behind the model" in p.info() or ys[1] < 12


def test_purge_is_shortened_or_skipped_when_both_sides_are_blocked():
    # model fills the bed in Y, starting close to the left edge: no room in front or behind
    p = purge(objects=[square(40, 5, 200, 230)])
    if p.has("G1 X"):
        m = purge_move(p)
        assert m["after"]["x"] + 10 <= 40 - 3 + 1e-6
        assert "shortened" in p.info()
    p = purge(objects=[square(12, 5, 200, 230)])
    assert not p.has("G1") and "no room" in p.info()


def test_purge_wrapped_in_gcode_state_and_modes_do_not_leak():
    p = Printer(objects=[square(100, 100, 140, 140)])
    p.abs_xy = False
    p.abs_e = True            # slicer is in G91 / M82
    p.run("LINE_PURGE")
    assert p.out[p.index("SAVE_GCODE_STATE")] and p.out[-1].startswith("RESTORE_GCODE_STATE")
    assert p.abs_xy is False and p.abs_e is True


def test_purge_skipped_when_cold_or_unhomed():
    assert not purge(can_extrude=False, objects=[square(100, 100, 140, 140)]).has("G1")
    assert not purge(homed="", objects=[square(100, 100, 140, 140)]).has("G1")


def test_purge_without_can_extrude_key_still_runs():
    assert purge(can_extrude=None, objects=[square(100, 100, 140, 140)]).has("G1 X")


def test_empty_exclude_object_purges_in_the_front_left_corner():
    p = purge(objects=[])
    assert p.has("G1 X10.0 Y10.0 F6000")


# ── smart park ──────────────────────────────────────────────────────────────
def test_smart_park_is_clamped_and_needs_homing():
    p = Printer(objects=[square(220, 220, 233, 233)])
    p.run("SMART_PARK")
    for m in p.moves:
        assert 0 <= m["after"]["x"] <= 235 and 0 <= m["after"]["y"] <= 235 and m["after"]["z"] <= 250
    assert p.has("RESTORE_GCODE_STATE")
    p = Printer(homed="", objects=[square(100, 100, 120, 120)])
    p.run("SMART_PARK")
    assert not p.has("G1")
    p = Printer(objects=[], limits=((0, 0, 0), (235, 235, 4)))
    p.run("SMART_PARK")
    assert all(m["after"]["z"] <= 4 for m in p.moves)


# ── PRINT_START ─────────────────────────────────────────────────────────────
def start(**kw):
    p = Printer(**kw)
    p.run("PRINT_START", "BED_TEMP=60 EXTRUDER_TEMP=210")
    return p


def test_start_full_sequence_with_eddy_defaults_to_normal_mesh():
    p = start(objects=[square(100, 100, 140, 140)])
    assert p.has("M140 S60.0") and p.has("M104 S150.0") and p.has("M109 S210.0") and p.has("M190 S60.0")
    assert "METHOD" not in next(l for l in p.out if l.startswith("_BED_MESH_CALIBRATE_BASE"))
    assert p.index("_BED_MESH_CALIBRATE_BASE") < p.index("M109") < p.index("G92 E0")
    assert not p.has("G28")


def test_start_passes_rapid_scan_only_when_asked_and_supported():
    ask = {"probe_method": "rapid_scan"}
    p = start(kamp_vars=ask, objects=[square(100, 100, 140, 140)])
    assert "METHOD=rapid_scan" in next(l for l in p.out if l.startswith("_BED_MESH_CALIBRATE_BASE"))
    for probe in ("probe", "none"):
        p = start(kamp_vars=ask, probe=probe, objects=[square(100, 100, 140, 140)])
        assert "METHOD" not in next(l for l in p.out if l.startswith("_BED_MESH_CALIBRATE_BASE"))


def test_start_homes_when_needed_and_survives_no_probe_and_no_bed_mesh():
    assert start(homed="").has("G28")
    p = start(probe="none", bed_mesh=False)
    assert not p.has("_BED_MESH_CALIBRATE_BASE") and p.has("M109")


def test_start_without_heated_bed_raises_nothing_and_skips_bed_commands():
    p = start(bed=False, objects=[square(100, 100, 140, 140)])
    assert not p.has("M140") and not p.has("M190") and p.has("M109 S210.0")
    assert "no heated bed" in p.info()


def test_start_with_missing_can_extrude_key():
    assert start(can_extrude=None).has("M109 S210.0")


def test_start_reports_missing_filament_without_aborting():
    p = start(sensors={"filament_switch_sensor runout": False, "filament_motion_sensor enc": True})
    assert "filament sensor 'runout' reports NO filament" in p.info()
    assert "'enc'" not in p.info()
    assert p.has("M109 S210.0") and not p.has("PAUSE") and not p.has("CANCEL")


def test_start_clean_report_when_sensors_are_fine():
    p = start(sensors={"filament_switch_sensor runout": True})
    assert "NO filament" not in p.info() and "OK" in p.info()


def test_start_without_kamp_installed_skips_kamp_steps():
    p = Printer(files=["print_start_end.cfg"], objects=[square(100, 100, 140, 140)])
    p.run("PRINT_START", "BED_TEMP=60 EXTRUDER_TEMP=210")
    assert p.has("BED_MESH_CALIBRATE") and not p.has("G1") and p.has("M109 S210.0")


def test_start_runs_nozzle_wipe_when_defined():
    p = Printer(objects=[])
    p.status["gcode_macro NOZZLE_WIPE"] = {}
    p.add_macro("NOZZLE_WIPE", "G1 X1 F100")
    p.run("PRINT_START", "BED_TEMP=60 EXTRUDER_TEMP=210")
    assert p.has("G1 X1 F100")


# ── PRINT_END ───────────────────────────────────────────────────────────────
def end(**kw):
    p = Printer(**kw)
    p.run("PRINT_END")
    return p


def first_motion(p):
    return next(i for i, l in enumerate(p.out) if l.startswith(("G1", "M84", "BED_MESH_CLEAR")))


def test_end_turns_heaters_and_fan_off_before_anything_can_fail():
    p = end()
    for cmd in ("M140 S0", "M104 S0", "M106 S0"):
        assert p.index(cmd) < first_motion(p)
    assert p.index("G1 E-2.5") < p.index("M84") and p.has("BED_MESH_CLEAR")


def test_end_cold_extruder_skips_retract_but_still_cools_and_parks():
    p = end(can_extrude=False)
    assert not p.has("G1 E") and p.has("M104 S0") and p.has("M140 S0")
    assert p.has("G1 X") and p.has("M84")


def test_end_unhomed_does_not_move_but_cools_down():
    p = end(homed="")
    assert not any(l.startswith("G1 X") or l.startswith("G1 Z") for l in p.out)
    assert p.has("M140 S0") and p.has("M104 S0")


def test_end_partially_homed_only_does_what_is_safe():
    p = end(homed="z")
    assert p.has("G1 Z") and not p.has("G1 X")


def test_end_with_crash_latched_never_moves_the_toolhead():
    p = end(crash=True)
    assert not p.has("G1") and not p.has("M84") and not p.has("BED_MESH_CLEAR")
    assert p.has("M104 S0") and "crash is latched" in p.info()


def test_end_with_hub_present_but_not_latched_behaves_normally():
    assert end(crash=False).has("G1 X")


def test_end_without_bed_or_bed_mesh_or_fan_is_clean():
    p = Printer(bed=False, bed_mesh=False)
    del p.status["fan"], p.status["bed_mesh"]
    p.run("PRINT_END")
    assert not p.has("M140") and not p.has("M106") and not p.has("BED_MESH_CLEAR") and p.has("M104 S0")


def test_end_lift_and_park_stay_inside_the_axes_and_state_is_restored():
    p = Printer(pos=(100, 100, 248), limits=((0, 0, 0), (200, 100, 250)))
    p.abs_e = True
    p.run("PRINT_END")
    for m in p.moves:
        if "X" in m["a"]:
            assert 0 <= m["a"]["X"] <= 200 and 0 <= m["a"]["Y"] <= 100
        if "Z" in m["a"]:
            assert m["a"]["Z"] <= 250
    assert p.abs_e is True and p.abs_xy is True


def test_no_hardcoded_machine_values_remain():
    settings = (ROOT / "kamp/KAMP_Settings.cfg").read_text()
    assert 'variable_probe_method: "default"' in settings
    assert "305" not in settings and "270" not in settings
    code = [l for l in (ROOT / "print_start_end.cfg").read_text().splitlines() if not l.lstrip().startswith("#")]
    assert sum(1 for l in code if "METHOD=rapid_scan" in l) == 1      # only the conditional branch
