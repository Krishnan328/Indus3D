"""Installer for the filament sensor: config edits are idempotent and never clobber existing macros."""
import configparser
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_sensor as ins  # noqa: E402


def klipper_parse(text):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)   # how Klipper reads cfg files
    cp.read_string(text)
    return cp


SAMPLE = """[gcode_macro A]
description: first
gcode:
    RESPOND MSG="a"

# Optional beeper
[gcode_macro M300]
description: beeper
gcode:
    SET_PIN PIN=beeper VALUE=1

[gcode_macro B]
gcode:
    RESPOND MSG="b"
"""


# ── text helpers ──────────────────────────────────────────────────────────────
def test_comment_section_disables_the_whole_block_only():
    out = ins.comment_section(SAMPLE, "gcode_macro M300", "disabled")
    cp = klipper_parse(out)
    assert "gcode_macro M300" not in cp.sections()
    assert 'RESPOND MSG="a"' in cp["gcode_macro A"]["gcode"] and "beeper" not in cp["gcode_macro A"]["gcode"]
    assert 'RESPOND MSG="b"' in cp["gcode_macro B"]["gcode"]
    assert "# disabled" in out


def test_commenting_a_section_never_leaks_its_body_into_the_previous_one():
    """The real-world bug: '#[gcode_macro M300]' with an active body overwrote the previous macro."""
    broken = SAMPLE.replace("[gcode_macro M300]", "#[gcode_macro M300]")
    assert "beeper" in klipper_parse(broken)["gcode_macro A"]["description"]      # what a header-only edit does
    fixed = ins.comment_section(SAMPLE, "gcode_macro M300", "x")
    assert klipper_parse(fixed)["gcode_macro A"]["description"] == "first"


def test_dedupe_only_touches_macros_and_respond_that_exist_elsewhere(tmp_path):
    other = tmp_path / "mainsail.cfg"
    other.write_text("[respond]\ndefault_type: echo\n\n[gcode_macro M300]\ngcode:\n    M118 x\n\n[virtual_sdcard]\npath: /x\n")
    ours = "[respond]\ndefault_type: echo\n\n[gcode_macro M300]\ngcode:\n    SET_PIN\n\n[gcode_macro MINE]\ngcode:\n    M117 hi\n"
    out, skipped = ins.dedupe_against(ours, [other])
    assert skipped == ["gcode_macro M300", "respond"]
    assert klipper_parse(out).sections() == ["gcode_macro MINE"]


def test_dedupe_ignores_unreadable_files(tmp_path):
    assert ins.dedupe_against("[respond]\n", [tmp_path / "missing.cfg"])[1] == []


def test_add_and_remove_include_are_idempotent():
    cfg = "# top\n[include a.cfg]\n[include b.cfg]\n[mcu]\nserial: /dev/x\n"
    new = ins.add_include(cfg, "smart.cfg")
    assert new.splitlines()[3] == "[include smart.cfg]"                      # right after the last include
    assert ins.add_include(new, "smart.cfg") is None
    assert ins.remove_include(new, "smart.cfg") == cfg
    assert ins.remove_include(cfg, "smart.cfg") is None
    assert ins.add_include("[mcu]\nx: 1\n", "smart.cfg").startswith("[include smart.cfg]")


def test_include_detection_is_not_fooled_by_a_commented_line():
    assert ins.add_include("#[include smart.cfg]\n[mcu]\n", "smart.cfg") is not None


def test_service_template_renders_without_placeholders():
    text = ins.render_service((ins.HERE / "indus3d-filament-sensor.service.in").read_text(),
                              "pi", "/venv/bin/python", Path("/opt/Indus3D/helpers/filament_sensor"), Path("/home/pi/printer_data/config"))
    assert "@" not in text and "User=pi" in text
    assert ("ExecStart=/venv/bin/python /opt/Indus3D/helpers/filament_sensor/indus3d_sensor_daemon.py "
            "--no-monitor --config /home/pi/printer_data/config/indus3d_sensor.ini") in text
    assert "SupplementaryGroups=dialout" in text


# ── installer ─────────────────────────────────────────────────────────────────
@pytest.fixture
def conf(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "printer.cfg").write_text("[include mainsail.cfg]\n[mcu]\nserial: /dev/x\n")
    (d / "mainsail.cfg").write_text("[respond]\ndefault_type: echo\n\n[gcode_macro M300]\ngcode:\n    M118 beep\n")
    return d


def installer(conf, dry=False):
    logs = []
    return ins.Installer(conf, "/usr/bin/python3", "tester", dry_run=dry, log=logs.append), logs


def test_install_creates_files_backs_up_and_is_idempotent(conf):
    i, _ = installer(conf)
    i.install_ini()
    i.install_klipper_cfg()
    assert (conf / "indus3d_sensor.ini").exists() and (conf / "smart_filament_sensor.cfg").exists()
    assert "[include smart_filament_sensor.cfg]" in (conf / "printer.cfg").read_text()
    assert len(list(conf.glob("printer.cfg.indus3d_bak_*"))) == 1

    cp = klipper_parse((conf / "smart_filament_sensor.cfg").read_text())
    assert "respond" not in cp.sections() and "gcode_macro M300" not in cp.sections()   # mainsail.cfg owns them
    assert "gcode_macro SMART_RUNOUT_PAUSE" in cp.sections()
    assert "Spool Profile set" in cp["gcode_macro SET_FILAMENT_SPOOL"]["gcode"]       # no leaked body

    before = {p.name: p.read_text() for p in conf.iterdir()}
    i.install_ini()
    i.install_klipper_cfg()
    assert {p.name: p.read_text() for p in conf.iterdir()} == before                    # second run changes nothing


def test_install_keeps_the_users_ini(conf):
    (conf / "indus3d_sensor.ini").write_text("[sensor]\nport = /dev/mine\n")
    installer(conf)[0].install_ini()
    assert "/dev/mine" in (conf / "indus3d_sensor.ini").read_text()


def test_dry_run_changes_nothing(conf):
    before = {p.name: p.read_text() for p in conf.iterdir()}
    i, logs = installer(conf, dry=True)
    i.install_ini()
    i.install_klipper_cfg()
    assert {p.name: p.read_text() for p in conf.iterdir()} == before
    assert all(l.startswith("[dry-run]") for l in logs) and logs


def test_uninstall_removes_include_and_config_but_keeps_the_ini_unless_purged(conf):
    i, _ = installer(conf)
    i.install_ini()
    i.install_klipper_cfg()
    i.uninstall()
    assert "smart_filament_sensor" not in (conf / "printer.cfg").read_text()
    assert not (conf / "smart_filament_sensor.cfg").exists() and (conf / "indus3d_sensor.ini").exists()
    i.uninstall(purge=True)
    assert not (conf / "indus3d_sensor.ini").exists()


# ── discovery ─────────────────────────────────────────────────────────────────
def test_detect_config_dir(tmp_path):
    with pytest.raises(ins.InstallError):
        ins.detect_config_dir(str(tmp_path), tmp_path)                       # no printer.cfg there
    cfg = tmp_path / "printer_data" / "config"
    cfg.mkdir(parents=True)
    (cfg / "printer.cfg").write_text("")
    assert ins.detect_config_dir(None, tmp_path) == cfg
    assert ins.detect_config_dir(str(cfg), tmp_path) == cfg


def test_pick_python_requires_pyserial(monkeypatch, tmp_path):
    monkeypatch.setattr(ins, "has_pyserial", lambda p: p == sys.executable)
    assert ins.pick_python(None, tmp_path) == sys.executable
    monkeypatch.setattr(ins, "has_pyserial", lambda p: False)
    with pytest.raises(ins.InstallError, match="pyserial"):
        ins.pick_python(None, tmp_path)


def test_real_sensor_cfg_parses_and_defines_the_macro_the_daemon_calls():
    cp = klipper_parse((ins.HERE / "smart_filament_sensor.cfg").read_text())
    assert "gcode_macro SMART_RUNOUT_PAUSE" in cp.sections()
    assert "SMART_RUNOUT_PAUSE" in (ins.HERE / "indus3d_sensor_daemon.py").read_text()
