"""Renders the Klipper macros with Jinja (configured like Klipper's: single-brace expressions) against
a mock `printer` and executes the result with a tiny G-code interpreter, so the safety logic is tested
even though no printer is attached."""
import ast
import configparser
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


# The shell extension is synchronous: no sweep may run until synchronized capture is implemented.
@pytest.mark.parametrize("state", ["standby", "printing", "paused", "complete"])
@pytest.mark.parametrize("apply", [0, 1])
def test_shaper_sweep_is_disabled_without_motion_or_persistence(state, apply):
    p = Printer(print_stats={"state": state})
    with pytest.raises(MacroError, match="sweep disabled"):
        p.run("BED_SHAPER_CALIBRATE_Y", APPLY=apply)
    assert p.out == []


def test_offline_capture_cli_stays_available():
    args = esp_hub_ctl.build_parser().parse_args(["shaper-capture", "--duration", "7", "--analyze"])
    assert args.duration == 7 and args.analyze and args.apply_to is None
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
