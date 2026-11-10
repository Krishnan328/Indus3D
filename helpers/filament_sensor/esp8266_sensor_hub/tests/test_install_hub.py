"""Installer of the bed sensor hub: udev rule identity, rendered files, idempotent config edits."""
import configparser
import re
import sys
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))
import install_hub as ih  # noqa: E402


def klipper_parse(text):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.read_string("\n".join(l.split("#")[0].rstrip() if "#" in l else l for l in text.splitlines()))   # Klipper drops '#' comments
    return cp


CH340 = {"ID_VENDOR_ID": "1a86", "ID_MODEL_ID": "7523", "ID_PATH": "platform-xhci-hcd.0-usb-0:1.3:1.0", "ID_SERIAL_SHORT": ""}
CP2102 = {"ID_VENDOR_ID": "10c4", "ID_MODEL_ID": "ea60", "ID_SERIAL_SHORT": "A50285BI", "ID_PATH": "platform-x-usb-0:2:1.0"}


# ── udev ──────────────────────────────────────────────────────────────────────
def test_parse_udevadm_output():
    assert ih.parse_udev_props("ID_VENDOR_ID=1a86\nDEVNAME=/dev/ttyUSB0\nfoo\nID_SERIAL=a=b\n") == \
        {"ID_VENDOR_ID": "1a86", "DEVNAME": "/dev/ttyUSB0", "ID_SERIAL": "a=b"}


def test_adapter_without_serial_is_matched_by_its_port():
    rule = ih.build_udev_rule(CH340)
    assert 'ENV{ID_PATH}=="platform-xhci-hcd.0-usb-0:1.3:1.0"' in rule and "ID_SERIAL_SHORT" not in rule
    assert 'ENV{ID_VENDOR_ID}=="1a86"' in rule and 'ENV{ID_MODEL_ID}=="7523"' in rule


def test_adapter_with_unique_serial_is_matched_by_serial():
    rule = ih.build_udev_rule(CP2102)
    assert 'ENV{ID_SERIAL_SHORT}=="A50285BI"' in rule and "ID_PATH" not in rule


def test_generic_serial_numbers_are_not_trusted():
    assert "ID_PATH" in ih.build_udev_rule({**CP2102, "ID_SERIAL_SHORT": "0001"})


def test_rule_has_the_required_attributes_and_safe_mode():
    rule = ih.build_udev_rule(CH340)
    assert 'SYMLINK+="esp8266_bed_hub"' in rule and 'GROUP="dialout"' in rule
    assert 'MODE="0660"' in rule and "0666" not in rule                 # not world-writable
    assert 'ENV{ID_MM_DEVICE_IGNORE}="1"' in rule                         # ModemManager must not probe the hub
    body = [l for l in rule.splitlines() if not l.startswith("#")]
    assert len(body) == 1 and body[0].startswith('SUBSYSTEM=="tty"')
    for part in body[0].split(", "):                                       # every term is KEY==/KEY+=/KEY= "value"
        assert re.fullmatch(r'[A-Z_]+(\{\w+\})?(==|\+=|=)"[^"]*"', part), part


def test_unidentifiable_device_is_refused():
    with pytest.raises(ih.InstallError):
        ih.build_udev_rule({"ID_VENDOR_ID": "1a86", "ID_MODEL_ID": "7523"})
    with pytest.raises(ih.InstallError):
        ih.build_udev_rule({})


# ── rendering ──────────────────────────────────────────────────────────────────────
def test_service_unit_is_complete(tmp_path):
    text = ih.render_service((HUB / "esp8266_bed_hub.service.in").read_text(), "krishnanu", "/venv/bin/python", HUB, tmp_path, "--mqtt localhost")
    assert "@" not in text
    assert f"ExecStart=/venv/bin/python {HUB}/scripts/esp_bed_monitor_daemon.py --serial auto" in text
    assert "--mqtt localhost" in text and "User=krishnanu" in text
    assert "SupplementaryGroups=dialout" in text and "Restart=always" in text
    assert "StateDirectory=indus3d/bed_hub" in text and "UMask=0022" in text
    assert "--mqtt" not in ih.render_service((HUB / "esp8266_bed_hub.service.in").read_text(), "u", "p", HUB, tmp_path)


def test_shell_cfg_rendering_leaves_no_placeholders():
    t = ih.render_shell_cfg((HUB / "klipper" / "bed_sensor_hub_shell.cfg.in").read_text(), "/venv/bin/python", HUB / "scripts", "http://127.0.0.1:7127")
    assert "@" not in t
    cp = klipper_parse(t)
    assert set(cp.sections()) == {f"gcode_shell_command {n}" for n in ("reset_hub_crash", "hub_status", "set_hub_threshold", "run_bed_shaper")}
    assert cp["gcode_shell_command run_bed_shaper"]["command"].startswith("/venv/bin/python")


def test_set_variable_edits_only_the_requested_line():
    text = (HUB / "klipper" / "bed_sensor_hub.cfg").read_text()
    new = ih.set_variable(text, "printer_cfg", "/var/lib/moonraker/config/printer.cfg")
    assert 'variable_printer_cfg: "/var/lib/moonraker/config/printer.cfg"' in new
    assert len(re.findall(r"^variable_printer_cfg:", new, re.M)) == 1 and 'variable_outdir: "/tmp/bed_shaper"' in new
    assert klipper_parse(new)["gcode_macro _BED_HUB_VARS"]["variable_printer_cfg"] == '"/var/lib/moonraker/config/printer.cfg"'


# ── installing into a config dir ──────────────────────────────────────────────────────
def make_config(tmp_path, extra=None):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "printer.cfg").write_text("[include mainsail.cfg]\n[printer]\nkinematics: corexy\n")
    (cfg / "moonraker.conf").write_text("[server]\nhost: 0.0.0.0\n\n[authorization]\ntrusted_clients:\n    127.0.0.0/8\n")
    (cfg / "mainsail.cfg").write_text("[respond]\n[gcode_macro PAUSE]\ngcode:\n    SAVE_GCODE_STATE NAME=PAUSE_STATE\n")
    for k, v in (extra or {}).items():
        (cfg / k).write_text(v)
    return cfg


def installer(cfg, calls=None, **kw):
    log = []
    run = (lambda cmd, **k: calls.append(cmd)) if calls is not None else (lambda cmd, **k: None)
    inst = ih.Installer(cfg, "/venv/bin/python", "krishnanu", device="/dev/ttyUSB0", run=run, props=lambda d: CH340,
                        log=log.append, rules_dir=cfg / "rules", **kw)
    return inst, log


def test_install_klipper_and_moonraker_are_idempotent(tmp_path):
    cfg = make_config(tmp_path)
    inst, _ = installer(cfg)
    inst.install_klipper()
    inst.install_moonraker()
    printer, moon = (cfg / "printer.cfg").read_text(), (cfg / "moonraker.conf").read_text()
    assert "[include esp8266_sensor_hub/bed_sensor_hub.cfg]" in printer and "[include esp8266_sensor_hub/bed_sensor_hub_shell.cfg]" in printer
    assert "[include esp8266_sensor_hub/moonraker_bed_hub.conf]" in moon
    assert moon.count("[authorization]") == 1                              # never adds a second one
    assert len(list(cfg.glob("printer.cfg.indus3d_bak_*"))) == 1
    cp = klipper_parse((cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg").read_text())
    assert f'"{cfg}/printer.cfg"' in cp["gcode_macro _BED_HUB_VARS"]["variable_printer_cfg"]
    assert f'"{cfg}/bed_hub_output"' in cp["gcode_macro _BED_HUB_VARS"]["variable_outdir"]
    assert (cfg / "bed_hub_output").is_dir()
    before = (printer, moon, (cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg").read_text())
    inst2, _ = installer(cfg)
    inst2.install_klipper()
    inst2.install_moonraker()
    after = ((cfg / "printer.cfg").read_text(), (cfg / "moonraker.conf").read_text(), (cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg").read_text())
    assert before == after
    assert len(list(cfg.glob("printer.cfg.indus3d_bak_*"))) == 1           # no new backup when nothing changed


def test_user_edits_survive_a_reinstall_but_force_replaces_with_backup(tmp_path):
    cfg = make_config(tmp_path)
    inst, _ = installer(cfg)
    inst.install_klipper()
    f = cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg"
    f.write_text(f.read_text().replace("variable_zhop: 10.0", "variable_zhop: 25.0"))
    inst2, _ = installer(cfg)
    inst2.install_klipper()
    assert "variable_zhop: 25.0" in f.read_text()
    inst3, _ = installer(cfg)
    inst3.install_klipper(force_cfg=True)
    assert "variable_zhop: 10.0" in f.read_text()
    assert any("zhop: 25.0" in b.read_text() for b in f.parent.glob("bed_sensor_hub.cfg.indus3d_bak_*"))


def test_macro_already_defined_elsewhere_is_disabled_in_the_copy_with_a_warning(tmp_path):
    old = "[gcode_macro BED_CRASH_HANDLER]\ngcode:\n    M117 old\n"
    cfg = make_config(tmp_path, {"old_hub.cfg": old})
    inst, _ = installer(cfg)
    inst.install_klipper()
    cp = klipper_parse((cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg").read_text())
    assert "gcode_macro BED_CRASH_HANDLER" not in cp.sections() and "gcode_macro BED_CRASH_RESUME" in cp.sections()
    assert "respond" not in cp.sections()                                  # mainsail.cfg already has [respond]
    assert any("BED_CRASH_HANDLER" in w for w in inst.warnings)


def test_udev_and_service_use_sudo_install_and_reload(tmp_path, monkeypatch):
    calls = []
    cfg = make_config(tmp_path)
    inst, _ = installer(cfg, calls)
    monkeypatch.setattr(ih.shutil, "which", lambda x: "/bin/systemctl")
    inst.install_udev()
    inst.install_service()
    flat = [" ".join(c) for c in calls]
    assert any(c.startswith("sudo install -m 644") and c.endswith(f"{cfg}/rules/{ih.RULE_NAME}") for c in flat)
    assert any("udevadm control --reload-rules" in c for c in flat) and any("udevadm trigger" in c for c in flat)
    assert any(c.endswith(f"/etc/systemd/system/{ih.SERVICE_NAME}") for c in flat)
    assert any("systemctl enable --now esp8266_bed_hub.service" in c for c in flat)
    assert not list(cfg.glob(".*.tmp"))                                    # temp files are cleaned up


def test_dry_run_changes_nothing(tmp_path):
    cfg = make_config(tmp_path)
    before = {p.name: p.read_text() for p in cfg.iterdir() if p.is_file()}
    calls = []
    inst, log = installer(cfg, calls, dry_run=True)
    inst.install_udev()
    inst.install_klipper()
    inst.install_moonraker()
    assert calls == [] and {p.name: p.read_text() for p in cfg.iterdir() if p.is_file()} == before
    assert not (cfg / "esp8266_sensor_hub").exists() and any("[dry-run]" in l for l in log)


def test_uninstall_removes_includes_and_generated_files_keeps_settings(tmp_path):
    cfg = make_config(tmp_path)
    inst, _ = installer(cfg)
    inst.install_klipper()
    inst.install_moonraker()
    inst.uninstall()
    assert "esp8266_sensor_hub" not in (cfg / "printer.cfg").read_text() and "esp8266_sensor_hub" not in (cfg / "moonraker.conf").read_text()
    assert not (cfg / "esp8266_sensor_hub" / "bed_sensor_hub_shell.cfg").exists()
    assert (cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg").exists()
    inst.uninstall(purge=True)
    assert not (cfg / "esp8266_sensor_hub" / "bed_sensor_hub.cfg").exists()


def test_python_selection_reports_missing_modules(tmp_path):
    py = tmp_path / "python"
    py.write_text("")
    with pytest.raises(ih.InstallError, match="numpy"):
        ih.pick_python(str(py), missing=lambda p: ["numpy", "scipy"])
    assert ih.pick_python(str(py), missing=lambda p: []) == str(py)
