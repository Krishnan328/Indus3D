"""Renders the Klipper macros with Jinja (configured like Klipper's: single-brace expressions) against
a mock `printer` and executes the result with a tiny G-code interpreter, so the safety logic is tested
even though no printer is attached."""
import ast
import configparser
import math
import re
from pathlib import Path

import jinja2
import pytest

import esp_hub_ctl

KLIPPER = Path(__file__).resolve().parents[1] / "klipper"


class MacroError(Exception):
    pass


class Printer:
    def __init__(self, **over):
        self.status = {
            "toolhead": {"extruder": "extruder", "homed_axes": "xyz",
                         "position": {"x": 120.0, "y": 100.0, "z": 30.0, "e": 0.0},
                         "axis_minimum": {"x": 0, "y": 0, "z": -2, "e": 0},
                         "axis_maximum": {"x": 235, "y": 235, "z": 250, "e": 0},
                         "max_accel": 3000.0, "minimum_cruise_ratio": 0.5},
            "extruder": {"target": 210.0, "temperature": 209.0, "can_extrude": True},
            "heater_bed": {"target": 60.0, "temperature": 59.5},
            "pause_resume": {"is_paused": False},
            "print_stats": {"state": "printing"},
            "configfile": {"config": {"gcode_shell_command reset_hub_crash": {}, "gcode_shell_command hub_status": {},
                                      "gcode_shell_command set_hub_threshold": {}, "gcode_shell_command run_bed_shaper": {}}},
        }
        for k, v in over.items():
            self.status[k] = v
        self.macros = {}
        self.out = []
        self._load()

    def _load(self):
        cp = configparser.RawConfigParser(strict=False)
        cp.read(KLIPPER / "bed_sensor_hub.cfg")
        self.env = jinja2.Environment("{%", "%}", "{", "}")
        for sec in cp.sections():
            if sec.startswith("gcode_macro "):
                name = sec.split(" ", 1)[1].upper()
                variables = {k[len("variable_"):]: ast.literal_eval(v) for k, v in cp.items(sec) if k.startswith("variable_")}
                self.macros[name] = self.env.from_string(cp.get(sec, "gcode"))
                self.status[f"gcode_macro {name}"] = variables
        self.vars = self.status["gcode_macro _BED_HUB_VARS"]

    def run(self, name, **params):
        def raise_error(msg):
            raise MacroError(msg)
        text = self.macros[name.upper()].render(printer=self.status, params={k.upper(): str(v) for k, v in params.items()},
                                                action_raise_error=raise_error,
                                                action_respond_info=lambda m: self.out.append("// " + m))
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cmd, _, rest = line.partition(" ")
            if cmd.upper() in self.macros:
                p = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', rest))
                self.run(cmd, **{k: v.strip('"') for k, v in p.items()})
            elif cmd == "SET_GCODE_VARIABLE":
                a = dict(re.findall(r"(\w+)=(\S+)", rest))
                self.status[f"gcode_macro {a['MACRO']}"][a["VARIABLE"]] = ast.literal_eval(a["VALUE"])
            else:
                self.out.append(line)
        return self.out

    def index(self, prefix, start=0):
        return next(i for i, l in enumerate(self.out) if i >= start and l.startswith(prefix))

    def has(self, prefix):
        return any(l.startswith(prefix) for l in self.out)


@pytest.fixture
def pr():
    return Printer()


# ── crash handler ──────────────────────────────────────────────────────────
def test_handler_sequence_and_saved_state(pr):
    pr.run("BED_CRASH_HANDLER", JERK=2450)
    assert pr.vars["saved_extruder_target"] == 210.0 and pr.vars["saved_bed_target"] == 60.0
    assert pr.vars["crash_active"] is True and pr.vars["last_jerk"] == 2450 and pr.vars["retracted"] is True
    order = [pr.index(p) for p in ("SAVE_GCODE_STATE NAME=BED_CRASH_STATE", "PAUSE", "G1 E-2.0 F1800",
                                   "G1 Z10.0", "G1 X10.0 Y220.0", "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0")]
    assert order == sorted(order)
    assert not pr.has("SET_HEATER_TEMPERATURE HEATER=heater_bed")          # the bed stays hot
    assert pr.has("M83")                                                    # relative extrusion for the retract


def test_zhop_is_bounded_by_the_axis_maximum(pr):
    pr.status["toolhead"]["position"]["z"] = 245.0
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert pr.has("G1 Z5.0 ")
    pr2 = Printer()
    pr2.status["toolhead"]["position"]["z"] = 250.0
    pr2.run("BED_CRASH_HANDLER", JERK=2100)
    assert not pr2.has("G1 Z")


def test_park_position_is_clamped_to_the_axes(pr):
    pr.status["toolhead"]["axis_maximum"]["y"] = 200
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert pr.has("G1 X10.0 Y200 ") or pr.has("G1 X10.0 Y200.0 ")


def test_unhomed_printer_is_not_moved_but_hotend_is_cooled(pr):
    pr.status["toolhead"]["homed_axes"] = ""
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert not any(l.startswith(("G1", "G91")) for l in pr.out)
    assert pr.has("SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0")


def test_no_second_pause_when_the_daemon_already_paused(pr):
    pr.status["pause_resume"]["is_paused"] = True
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert not pr.has("PAUSE") and pr.has("SAVE_GCODE_STATE")


def test_repeated_alert_does_not_overwrite_saved_temperatures(pr):
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    pr.status["pause_resume"]["is_paused"] = True
    pr.status["extruder"]["target"] = 0.0                                   # we switched it off ourselves
    pr.out.clear()
    pr.run("BED_CRASH_HANDLER", JERK=3000)
    assert pr.vars["saved_extruder_target"] == 210.0
    assert not pr.has("SAVE_GCODE_STATE") and not pr.has("G1")


def test_stale_flag_after_cancel_does_not_block_the_next_crash(pr):
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    pr.status["pause_resume"]["is_paused"] = False                          # print was cancelled
    pr.out.clear()
    pr.run("BED_CRASH_HANDLER", JERK=2200)
    assert pr.has("SAVE_GCODE_STATE") and pr.vars["last_jerk"] == 2200


def test_bed_off_when_configured(pr):
    pr.vars["keep_bed_hot"] = False
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert pr.has("SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=0")


def test_beeps_only_with_a_beeper_pin_and_never_break_the_handler(pr):
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert not pr.has("SET_PIN")
    pr2 = Printer()
    pr2.status["output_pin beeper"] = {"value": 0.0}
    pr2.run("BED_CRASH_HANDLER", JERK=2100)
    assert sum(1 for l in pr2.out if l.startswith("SET_PIN PIN=beeper VALUE=1")) == 3


def test_cold_extruder_is_not_retracted(pr):
    pr.status["extruder"]["can_extrude"] = False
    pr.run("BED_CRASH_HANDLER", JERK=2100)
    assert not pr.has("G1 E") and pr.vars["retracted"] is False


# ── resume ──────────────────────────────────────────────────────────────────
def crashed():
    p = Printer()
    p.run("BED_CRASH_HANDLER", JERK=2450)
    p.status["pause_resume"]["is_paused"] = True
    p.status["extruder"]["target"] = 0.0
    p.out.clear()
    return p


def test_resume_reheats_primes_resets_latch_then_resumes():
    p = crashed()
    p.run("BED_CRASH_RESUME")
    order = [p.index(x) for x in ("M140 S60.0", "M109 S210.0", "M190 S60.0", "G1 E2.0", "RUN_SHELL_COMMAND CMD=reset_hub_crash",
                                  "RESTORE_GCODE_STATE NAME=BED_CRASH_STATE MOVE=1", "RESUME")]
    assert order == sorted(order) and p.out[-1] == "RESUME"
    assert p.vars["crash_active"] is False


def test_resume_refuses_when_not_paused_or_without_a_crash():
    p = Printer()
    with pytest.raises(MacroError, match="not paused"):
        p.run("BED_CRASH_RESUME")
    p.status["pause_resume"]["is_paused"] = True
    with pytest.raises(MacroError, match="No bed crash"):
        p.run("BED_CRASH_RESUME")


def test_resume_without_shell_commands_still_resumes_but_says_so():
    p = crashed()
    p.status["configfile"]["config"] = {}
    p.run("BED_CRASH_RESUME")
    assert p.out[-1] == "RESUME" and any("not configured" in l for l in p.out)


# ── hub helper macros ────────────────────────────────────────────────────────
def test_threshold_validation_and_command():
    p = Printer()
    for bad in (499, 8001, 0):
        with pytest.raises(MacroError):
            p.run("SET_BED_CRASH_THRESHOLD", VALUE=bad)
    with pytest.raises(MacroError):
        p.run("SET_BED_CRASH_THRESHOLD")
    p.run("SET_BED_CRASH_THRESHOLD", VALUE=2500)
    assert 'RUN_SHELL_COMMAND CMD=set_hub_threshold PARAMS="2500"' in p.out
    assert p.vars["crash_threshold_mg"] == 2500


def test_reset_and_status_buttons():
    p = Printer()
    p.run("BED_HUB_RESET_CRASH")
    p.run("BED_HUB_STATUS")
    assert "RUN_SHELL_COMMAND CMD=reset_hub_crash" in p.out and "RUN_SHELL_COMMAND CMD=hub_status" in p.out
    p2 = Printer()
    p2.status["configfile"]["config"] = {}
    with pytest.raises(MacroError, match="not configured"):
        p2.run("BED_HUB_STATUS")


def test_reset_clears_the_stale_flag_only_when_not_paused():
    p = crashed()
    p.run("BED_HUB_RESET_CRASH")
    assert p.vars["crash_active"] is True                                    # still paused: keep it for the resume
    p.status["pause_resume"]["is_paused"] = False
    p.run("BED_HUB_RESET_CRASH")
    assert p.vars["crash_active"] is False


# ── shaper sweep ──────────────────────────────────────────────────────────────
def sweep(**kw):
    p = Printer(print_stats={"state": "standby"})
    p.vars["printer_cfg"] = kw.pop("cfg", "/cfg/printer.cfg")
    for k, v in kw.pop("vars", {}).items():
        p.vars[k] = v
    p.status.update(kw.pop("status", {}))
    p.run("BED_SHAPER_CALIBRATE_Y", **kw)
    return p


def moves(p):
    """[(accel, [signed Y moves])] per frequency step."""
    steps, cur = [], None
    for l in p.out:
        m = re.match(r"SET_VELOCITY_LIMIT ACCEL=(\d+)", l)
        if m:
            cur = (int(m.group(1)), [])
            steps.append(cur)
        m = re.match(r"G1 Y(-?[\d.]+) F(\d+)", l)
        if m and cur:
            cur[1].append(float(m.group(1)))
    return steps[:-1]                                                        # the last one restores the limits


def test_sweep_order_capture_before_motion_and_restores_everything():
    p = sweep()
    cap = p.index("RUN_SHELL_COMMAND CMD=run_bed_shaper")
    assert not p.has("SET_INPUT_SHAPER")                       # no [input_shaper] configured: nothing to switch
    assert cap < p.index("G4 P1500") < p.index("G1 Y")
    assert p.has("SET_VELOCITY_LIMIT ACCEL=3000.0 MINIMUM_CRUISE_RATIO=0.5")
    last_move = max(i for i, l in enumerate(p.out) if l.startswith("G1 Y"))
    assert p.index("SET_VELOCITY_LIMIT ACCEL=3000.0", last_move) > last_move       # limits restored after the sweep
    assert p.has("RESTORE_GCODE_STATE NAME=BED_SHAPER")
    assert p.has("M400")


def test_sweep_disables_and_restores_an_active_shaper():
    p = sweep(status={"input_shaper": {"shaper_type_x": "zv", "shaper_freq_x": 60.0, "shaper_type_y": "mzv", "shaper_freq_y": 40.0}})
    assert p.has("SET_INPUT_SHAPER SHAPER_FREQ_X=0 SHAPER_FREQ_Y=0")
    assert p.has("SET_INPUT_SHAPER SHAPER_FREQ_X=60.0 SHAPER_FREQ_Y=40.0 SHAPER_TYPE_Y=mzv")
    assert p.index("SET_INPUT_SHAPER SHAPER_FREQ_X=0") < p.index("G1 Y")


def test_sweep_homes_only_when_needed():
    assert not sweep().has("G28")
    assert sweep(status={"toolhead": {**Printer().status["toolhead"], "homed_axes": ""}}).has("G28")


def test_sweep_physics_each_halfcycle_lasts_half_a_period():
    p = sweep()
    steps = moves(p)
    freqs = list(range(5, 121, 5))
    assert len(steps) == len(freqs)
    total = 0.0
    for (accel, ys), f in zip(steps, freqs):
        assert accel <= 7000 * 1.001
        assert abs(sum(ys)) < 1e-9                                           # returns to where it started
        assert max(abs(y) for y in ys) <= 3.0 + 1e-9
        assert len(ys) // 2 >= 2
        L = abs(ys[0])
        half = 2 * math.sqrt(L / accel)                                      # triangular velocity profile
        assert half == pytest.approx(1 / (2 * f), rel=0.03)
        total += len(ys) // 2 / f
    assert total < 12


def test_sweep_capture_parameters_match_the_cli():
    p = sweep(cfg="/var/lib/moonraker/config/printer.cfg", APPLY=1)
    cmd = next(l for l in p.out if "CMD=run_bed_shaper" in l)
    params = re.search(r'PARAMS="([^"]*)"', cmd).group(1).split()
    args = esp_hub_ctl.build_parser().parse_args(["shaper-capture"] + params)
    assert args.analyze and args.axis == "Y" and args.rate == 1600
    assert 5 <= args.duration <= 15
    assert args.apply_to == "/var/lib/moonraker/config/printer.cfg"
    no_apply = next(l for l in sweep().out if "CMD=run_bed_shaper" in l)
    assert "--apply-to" not in no_apply


def test_sweep_refuses_unsafe_or_impossible_requests():
    with pytest.raises(MacroError, match="Not while"):
        Printer().run("BED_SHAPER_CALIBRATE_Y")
    with pytest.raises(MacroError, match="at most 15"):
        sweep(vars={"sweep_step_hz": 1})
    with pytest.raises(MacroError, match="variable_printer_cfg"):
        sweep(cfg="", APPLY=1)
    p = Printer(print_stats={"state": "standby"})
    p.status["configfile"]["config"] = {}
    with pytest.raises(MacroError, match="run_bed_shaper"):
        p.run("BED_SHAPER_CALIBRATE_Y")


def test_sweep_uses_accel_to_decel_on_older_klipper():
    th = {k: v for k, v in Printer().status["toolhead"].items() if k != "minimum_cruise_ratio"}
    th["max_accel_to_decel"] = 1500.0
    p = sweep(status={"toolhead": th})
    assert any("ACCEL_TO_DECEL=" in l for l in p.out) and not any("MINIMUM_CRUISE_RATIO" in l for l in p.out)
    assert p.has("SET_VELOCITY_LIMIT ACCEL=3000.0 ACCEL_TO_DECEL=1500.0")


# ── consistency with the shell command file ────────────────────────────────────────────
def test_every_shell_command_the_macros_call_is_defined():
    macros = (KLIPPER / "bed_sensor_hub.cfg").read_text()
    used = set(re.findall(r"RUN_SHELL_COMMAND CMD=(\w+)", macros))
    shell = (KLIPPER / "bed_sensor_hub_shell.cfg.in").read_text()
    defined = set(re.findall(r"^\[gcode_shell_command (\w+)\]", shell, re.M))
    assert used and used == defined


def test_shell_commands_use_real_subcommands():
    shell = (KLIPPER / "bed_sensor_hub_shell.cfg.in").read_text()
    parser = esp_hub_ctl.build_parser()
    for m in re.finditer(r"^command: .*esp_hub_ctl\.py --url @HUB_URL@ ([\w-]+)", shell, re.M):
        base = ["--url", "http://x"] + [m.group(1)]
        extra = {"set-threshold": ["2000"]}.get(m.group(1), [])
        parser.parse_args(base + extra)
