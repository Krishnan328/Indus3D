#!/usr/bin/env python3
"""Install / uninstall the ESP8266 bed sensor hub next to Klipper and Moonraker.

    install_hub.py                          # detect everything, install, start the service
    install_hub.py --device /dev/ttyUSB0    # which serial device is the hub (when auto-detection fails)
    install_hub.py --mqtt localhost         # also publish chamber/crash status to MQTT (Moonraker sensor)
    install_hub.py --print-only             # print the udev rule and the unit (for NixOS / manual setups)
    install_hub.py --dry-run                # show what would happen, change nothing
    install_hub.py --uninstall [--purge]

What it does (idempotent):
  1. udev rule   /etc/udev/rules.d/99-esp8266-bedhub.rules: the symlink /dev/esp8266_bed_hub for THIS
                 device, matched by its USB serial number, or by its physical USB port when the adapter
                 has none (CH340 boards), group dialout, mode 0660, ModemManager told to leave it alone
  2. systemd     esp8266_bed_hub.service (the host daemon: reconnects by itself, pauses the print on a crash)
  3. Klipper     <config>/esp8266_sensor_hub/bed_sensor_hub.cfg (kept if it exists), bed_sensor_hub_shell.cfg
                 (regenerated), and the two [include] lines in printer.cfg (backup first)
  4. Moonraker   <config>/esp8266_sensor_hub/moonraker_bed_hub.conf and its [include] in moonraker.conf
"""

import argparse
import getpass
import grp
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import install_sensor as base  # noqa: E402  (config-text helpers shared with the filament sensor installer)

SERVICE_NAME = "esp8266_bed_hub.service"
RULE_NAME = "99-esp8266-bedhub.rules"
SYMLINK = "esp8266_bed_hub"
RULES_DIR = Path("/etc/udev/rules.d")
SUBDIR = "esp8266_sensor_hub"
KLIPPER_CFG, SHELL_CFG, MOONRAKER_CFG = "bed_sensor_hub.cfg", "bed_sensor_hub_shell.cfg", "moonraker_bed_hub.conf"
GENERIC_SERIALS = {"", "0", "0001", "00000001", "12345678", "1234567890"}   # shared by many adapters: useless as an identity
PYTHON_MODULES = ("serial", "numpy", "scipy", "matplotlib")
SECTION_NAMES = ("respond", "gcode_macro")


class InstallError(RuntimeError):
    pass


# -- udev --------------------------------------------------------------------------------
def parse_udev_props(text: str) -> Dict[str, str]:
    """`udevadm info -q property -n DEV` output -> dict."""
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def udev_properties(device: str) -> Dict[str, str]:
    try:
        r = subprocess.run(["udevadm", "info", "-q", "property", "-n", device], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InstallError(f"cannot run udevadm for {device}: {e}")
    if r.returncode != 0:
        raise InstallError(f"udevadm does not know {device}: {r.stderr.strip()}")
    return parse_udev_props(r.stdout)


def build_udev_rule(props: Dict[str, str], symlink: str = SYMLINK, group: str = "dialout", mode: str = "0660") -> str:
    """The rule that gives THIS adapter a stable name. The adapter is identified by its USB serial
    number when it has a unique one, else by the physical port it sits in (cheap CH340 adapters have
    no serial and would otherwise all look identical, so another one could steal the name)."""
    vid, pid = props.get("ID_VENDOR_ID"), props.get("ID_MODEL_ID")
    if not (vid and pid):
        raise InstallError("the device reports no USB vendor/product id: is it a USB serial adapter?")
    serial_no, id_path = props.get("ID_SERIAL_SHORT", ""), props.get("ID_PATH", "")
    if serial_no and serial_no not in GENERIC_SERIALS:
        ident, how = f'ENV{{ID_SERIAL_SHORT}}=="{serial_no}"', f"USB serial {serial_no}"
    elif id_path:
        ident, how = f'ENV{{ID_PATH}}=="{id_path}"', f"USB port {id_path} (the adapter has no unique serial number: keep it in this port, or re-run this installer after moving it)"
    else:
        raise InstallError("the device has neither a unique USB serial number nor a physical path to match on")
    return (f"# Indus3D ESP8266 bed sensor hub, identified by {how}\n"
            f'SUBSYSTEM=="tty", ENV{{ID_VENDOR_ID}}=="{vid}", ENV{{ID_MODEL_ID}}=="{pid}", {ident}, '
            f'SYMLINK+="{symlink}", GROUP="{group}", MODE="{mode}", ENV{{ID_MM_DEVICE_IGNORE}}="1"\n')


# -- text rendering -----------------------------------------------------------------------
def render_service(template: str, user: str, python: str, install_dir: Path, config_dir: Path, extra_args: str = "") -> str:
    return (template.replace("@USER@", user).replace("@PYTHON@", python).replace("@INSTALL_DIR@", str(install_dir))
            .replace("@CONFIG_DIR@", str(config_dir)).replace("@EXTRA_ARGS@", (" " + extra_args) if extra_args else ""))


def render_shell_cfg(template: str, python: str, scripts: Path, hub_url: str) -> str:
    return template.replace("@PYTHON@", python).replace("@SCRIPTS@", str(scripts)).replace("@HUB_URL@", hub_url)


def set_variable(cfg_text: str, name: str, value: str) -> str:
    """Set `variable_<name>: "<value>"` in the _BED_HUB_VARS macro text."""
    return re.sub(rf'^(variable_{name}:[ \t]*)[^#\n]*?([ \t]*(?:#.*)?)$', lambda m: f'{m.group(1)}"{value}"{m.group(2)}',
                  cfg_text, count=1, flags=re.M)


def has_modules(python: str, modules=PYTHON_MODULES) -> List[str]:
    """Modules from `modules` that `python` cannot import."""
    code = "import importlib.util as u;print(' '.join(m for m in %r if u.find_spec(m) is None))" % (list(modules),)
    try:
        r = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return list(modules)
    return r.stdout.split() if r.returncode == 0 else list(modules)


def pick_python(explicit: Optional[str], missing=has_modules) -> str:
    candidates = ([explicit] if explicit else []) + [str(HERE / ".venv" / "bin" / "python"),
                                                    str(HERE.parent / ".venv" / "bin" / "python"), sys.executable]
    last = None
    for c in candidates:
        if c and Path(c).exists():
            last = missing(c)
            if not last:
                return c
    raise InstallError(f"no Python with {', '.join(PYTHON_MODULES)} found (missing in the best candidate: {', '.join(last or PYTHON_MODULES)}). "
                       f"Create one: python3 -m venv {HERE / '.venv'} && {HERE / '.venv' / 'bin' / 'pip'} install pyserial numpy scipy matplotlib")


def detect_device(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    if os.path.exists("/dev/" + SYMLINK):
        return "/dev/" + SYMLINK
    sys.path.insert(0, str(HERE / "scripts"))
    import esp_bed_monitor_daemon as dm
    for cand in dm.candidate_ports():
        if dm.probe_port(cand):
            return cand
    raise InstallError("could not find the hub among the serial devices (it must be plugged in, powered and not held "
                       "by another program). Pass --device /dev/ttyUSB0 (see `ls /dev/serial/by-id`)")


# -- the installer -----------------------------------------------------------------------
class Installer:
    def __init__(self, config_dir: Path, python: str, user: str, device: Optional[str] = None, mqtt: str = "",
                 dry_run=False, run: Callable = None, props: Callable = udev_properties, log=print,
                 rules_dir: Path = RULES_DIR, hub_url: str = "http://127.0.0.1:7127"):
        self.config_dir, self.python, self.user, self.device = config_dir, python, user, device
        self.mqtt, self.dry, self.log = mqtt, dry_run, log
        self._run = run or (lambda cmd, **kw: subprocess.run(cmd, check=True, **kw))
        self._props, self.rules_dir, self.hub_url = props, rules_dir, hub_url
        self.dir = config_dir / SUBDIR
        self.warnings: List[str] = []

    def _say(self, msg):
        self.log(("[dry-run] " if self.dry else "") + msg)

    def _write(self, path: Path, text: str):
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def _backup(self, path: Path) -> Path:
        b = path.with_name(f"{path.name}.indus3d_bak_{time.strftime('%Y%m%d-%H%M%S')}")
        if not self.dry:
            shutil.copy(path, b)
        return b

    def _sudo_install(self, text: str, dest: Path):
        tmp = self.config_dir / f".{dest.name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        try:
            self._run(["sudo", "install", "-m", "644", str(tmp), str(dest)])
        finally:
            tmp.unlink(missing_ok=True)

    # udev ------------------------------------------------------------------------------
    def rule_text(self) -> str:
        return build_udev_rule(self._props(self.device))

    def install_udev(self):
        rule, dest = self.rule_text(), self.rules_dir / RULE_NAME
        self._say(f"install {dest}:\n    " + rule.strip().replace("\n", "\n    "))
        if self.dry:
            return
        self._sudo_install(rule, dest)
        self._run(["sudo", "udevadm", "control", "--reload-rules"])
        self._run(["sudo", "udevadm", "trigger", "--subsystem-match=tty", "--action=add"])

    # klipper / moonraker ------------------------------------------------------------------
    def install_klipper(self, force_cfg=False):
        cfg_dest = self.dir / KLIPPER_CFG
        if cfg_dest.exists() and not force_cfg:
            self._say(f"keep existing {cfg_dest} (use --force-cfg to replace it with the packaged version; your copy is backed up)")
        else:
            if cfg_dest.exists():
                self._say(f"back up {cfg_dest.name} -> {self._backup(cfg_dest).name}")
            text = (HERE / "klipper" / KLIPPER_CFG).read_text(encoding="utf-8")
            text = set_variable(text, "printer_cfg", str(self.config_dir / "printer.cfg"))
            text = set_variable(text, "outdir", str(self.config_dir / "bed_hub_output"))
            others = [p for p in self.config_dir.rglob("*.cfg") if p != cfg_dest and SUBDIR not in p.parts]
            text, skipped = base.dedupe_against(text, others)
            for sec in skipped:
                self.warnings.append(f"[{sec}] is already defined elsewhere in your Klipper config: your existing one stays active "
                                     f"and the hub's copy was disabled. If it is an older hub macro, delete it so the new one is used.")
            self._say(f"create {cfg_dest}")
            self._write(cfg_dest, text)
        shell = render_shell_cfg((HERE / "klipper" / (SHELL_CFG + ".in")).read_text(encoding="utf-8"),
                                 self.python, HERE / "scripts", self.hub_url)
        self._say(f"write {self.dir / SHELL_CFG} (python: {self.python})")
        self._write(self.dir / SHELL_CFG, shell)
        if not self.dry:
            (self.config_dir / "bed_hub_output").mkdir(exist_ok=True)
        self._add_include(self.config_dir / "printer.cfg", [f"{SUBDIR}/{KLIPPER_CFG}", f"{SUBDIR}/{SHELL_CFG}"])

    def install_moonraker(self):
        dest = self.dir / MOONRAKER_CFG
        self._say(f"write {dest}")
        self._write(dest, (HERE / "klipper" / MOONRAKER_CFG).read_text(encoding="utf-8"))
        conf = self.config_dir / "moonraker.conf"
        if not conf.exists():
            return self.warnings.append(f"{conf} not found: add [include {SUBDIR}/{MOONRAKER_CFG}] to your moonraker.conf yourself")
        self._add_include(conf, [f"{SUBDIR}/{MOONRAKER_CFG}"])

    def _add_include(self, target: Path, files: List[str]):
        text, changed = target.read_text(encoding="utf-8"), False
        for f in files:
            new = base.add_include(text, f)
            if new is not None:
                text, changed = new, True
                self._say(f"add [include {f}] to {target.name}")
            else:
                self._say(f"{target.name} already includes {f}")
        if changed:
            self._say(f"back up {target.name} -> {self._backup(target).name}")
            self._write(target, text)

    # service -------------------------------------------------------------------------------
    def service_text(self) -> str:
        extra = f"--mqtt {self.mqtt}" if self.mqtt else ""
        return render_service((HERE / "esp8266_bed_hub.service.in").read_text(encoding="utf-8"), self.user, self.python, HERE,
                              self.config_dir, extra)

    def install_service(self):
        if not shutil.which("systemctl"):
            return self._say("systemd not found: skipping the service (run scripts/esp_bed_monitor_daemon.py yourself)")
        dest = base.SYSTEMD_DIR / SERVICE_NAME
        self._say(f"install {dest} and enable it")
        if self.dry:
            return
        self._sudo_install(self.service_text(), dest)
        self._run(["sudo", "systemctl", "daemon-reload"])
        self._run(["sudo", "systemctl", "enable", "--now", SERVICE_NAME])

    # uninstall -------------------------------------------------------------------------------
    def uninstall(self, purge=False):
        if shutil.which("systemctl") and (base.SYSTEMD_DIR / SERVICE_NAME).exists():
            self._say(f"stop, disable and remove {SERVICE_NAME}")
            if not self.dry:
                for cmd in (["stop", SERVICE_NAME], ["disable", SERVICE_NAME]):
                    subprocess.run(["sudo", "systemctl", *cmd], check=False)
                self._run(["sudo", "rm", "-f", str(base.SYSTEMD_DIR / SERVICE_NAME)])
                self._run(["sudo", "systemctl", "daemon-reload"])
        if (self.rules_dir / RULE_NAME).exists():
            self._say(f"remove {self.rules_dir / RULE_NAME}")
            if not self.dry:
                self._run(["sudo", "rm", "-f", str(self.rules_dir / RULE_NAME)])
                self._run(["sudo", "udevadm", "control", "--reload-rules"])
        for target, files in ((self.config_dir / "printer.cfg", [KLIPPER_CFG, SHELL_CFG]),
                              (self.config_dir / "moonraker.conf", [MOONRAKER_CFG])):
            if not target.exists():
                continue
            text, changed = target.read_text(encoding="utf-8"), False
            for f in files:
                new = base.remove_include(text, f"{SUBDIR}/{f}")
                if new is not None:
                    text, changed = new, True
            if changed:
                self._say(f"back up {target.name} -> {self._backup(target).name}; remove the includes")
                self._write(target, text)
        for f in (SHELL_CFG, MOONRAKER_CFG) + ((KLIPPER_CFG,) if purge else ()):
            p = self.dir / f
            if p.exists():
                self._say(f"remove {p}")
                if not self.dry:
                    p.unlink()
        if (self.dir / KLIPPER_CFG).exists():
            self._say(f"kept {self.dir / KLIPPER_CFG} (your macro settings; --purge removes it)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--klipper-config", help="Klipper config directory (contains printer.cfg and moonraker.conf)")
    ap.add_argument("--device", help="the hub's serial device, e.g. /dev/ttyUSB0")
    ap.add_argument("--python", help="Python with pyserial, numpy, scipy and matplotlib")
    ap.add_argument("--user", default=getpass.getuser(), help="user the daemon runs as")
    ap.add_argument("--mqtt", default="", metavar="HOST[:PORT]", help="publish status to this MQTT broker (Moonraker sensor card)")
    ap.add_argument("--no-udev", action="store_true")
    ap.add_argument("--no-service", action="store_true")
    ap.add_argument("--no-klipper", action="store_true", help="skip the Klipper and Moonraker config changes")
    ap.add_argument("--force-cfg", action="store_true", help="replace an existing bed_sensor_hub.cfg with the packaged one")
    ap.add_argument("--print-only", action="store_true", help="print the udev rule and the unit, change nothing")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if os.geteuid() == 0:
        print("Run as your normal user, not root (sudo is used where needed).", file=sys.stderr)
        return 1
    try:
        cfg_dir = base.detect_config_dir(args.klipper_config, Path.home())
        inst = Installer(cfg_dir, "", args.user, mqtt=args.mqtt, dry_run=args.dry_run or args.print_only)
        if args.uninstall:
            inst.uninstall(args.purge)
            return 0
        inst.python = pick_python(args.python)
        if not args.no_udev:
            inst.device = detect_device(args.device)
        if args.print_only:
            if not args.no_udev:
                print(f"# {RULES_DIR / RULE_NAME}\n{inst.rule_text()}")
            print(f"# {base.SYSTEMD_DIR / SERVICE_NAME}\n{inst.service_text()}")
            return 0
        if not args.no_udev:
            inst.install_udev()
        if not args.no_klipper:
            inst.install_klipper(args.force_cfg)
            inst.install_moonraker()
        if not args.no_service:
            inst.install_service()
    except (InstallError, base.InstallError, OSError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in inst.warnings:
        print(f"warning: {w}", file=sys.stderr)
    try:
        if "dialout" not in [grp.getgrgid(g).gr_name for g in os.getgroups()]:
            print("note: your user is not in the dialout group; the service does not need it, your own shell does "
                  "(sudo usermod -aG dialout $USER).")
    except (KeyError, OSError):
        pass
    print("Done. Restart Klipper and Moonraker (FIRMWARE_RESTART; sudo systemctl restart moonraker), then check "
          "BED_HUB_STATUS in the console.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
