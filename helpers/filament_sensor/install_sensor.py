#!/usr/bin/env python3
"""Install / uninstall the smart filament sensor daemon next to Klipper.

    install_sensor.py                         # detect the Klipper config dir, install, enable the service
    install_sensor.py --klipper-config DIR    # explicit config dir (the one with printer.cfg)
    install_sensor.py --dry-run               # show what would happen, change nothing
    install_sensor.py --no-service            # config files only
    install_sensor.py --uninstall [--purge]   # remove service + include (--purge also removes the ini)

What it does (all idempotent; nothing is overwritten):
  1. indus3d_sensor.ini         copied to the config dir if absent (your edits are kept)
  2. smart_filament_sensor.cfg  copied there; any [respond] / [gcode_macro X] section that another
                                .cfg already defines is commented out IN THE COPY, whole block,
                                so a duplicate can never overwrite your existing macro
  3. printer.cfg                gets [include smart_filament_sensor.cfg] (timestamped backup first)
  4. systemd service            indus3d-filament-sensor.service rendered from the template for the
                                current user and Python (the one with pyserial), enabled and started

Debian-family hosts with systemd. On NixOS declare the service in your configuration instead; steps 1-3
still apply (use --no-service).
"""

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

HERE = Path(__file__).resolve().parent
SERVICE_NAME = "indus3d-filament-sensor.service"
TEMPLATE = HERE / "indus3d-filament-sensor.service.in"
INI_NAME, CFG_NAME = "indus3d_sensor.ini", "smart_filament_sensor.cfg"
SYSTEMD_DIR = Path("/etc/systemd/system")
SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$")


class InstallError(RuntimeError):
    pass


# -- config text helpers ------------------------------------------------------------
def sections_defined(text: str) -> set:
    return {m.group(1).strip() for line in text.splitlines() if (m := SECTION_RE.match(line))}


def comment_section(text: str, section: str, note: str) -> str:
    """Comment out `[section]` and every line up to the next section header."""
    out, inside = [], False
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            inside = m.group(1).strip() == section
            if inside:
                out.append(f"# {note}")
                out.append(f"#{line}")
                continue
        out.append(f"#{line}" if inside and line.strip() and not line.startswith("#") else line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def dedupe_against(text: str, other_files: List[Path]) -> (str, List[str]):
    """Comment out sections of `text` that any of `other_files` already defines."""
    existing = set()
    for f in other_files:
        try:
            existing |= sections_defined(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    skipped = []
    for sec in sorted(sections_defined(text)):
        if sec in existing and (sec == "respond" or sec.startswith("gcode_macro ")):
            text = comment_section(text, sec, f"Indus3D: '[{sec}]' is already defined in your config; this copy is disabled.")
            skipped.append(sec)
    return text, skipped


def add_include(printer_cfg: str, filename: str) -> Optional[str]:
    """Return new printer.cfg text with the include added, or None if already present."""
    inc = f"[include {filename}]"
    if re.search(rf"^\s*\[include\s+{re.escape(filename)}\]", printer_cfg, re.M):
        return None
    lines = printer_cfg.splitlines()
    idx = max((i for i, l in enumerate(lines) if l.strip().startswith("[include ")), default=-1)
    if idx >= 0:
        lines.insert(idx + 1, inc)
    else:
        lines = [inc, ""] + lines
    return "\n".join(lines) + "\n"


def remove_include(printer_cfg: str, filename: str) -> Optional[str]:
    pat = re.compile(rf"^[ \t]*\[include\s+{re.escape(filename)}\][ \t]*\n?", re.M)
    new = pat.sub("", printer_cfg)
    return None if new == printer_cfg else new


def render_service(template: str, user: str, python: str, install_dir: Path, config_dir: Path) -> str:
    return (template.replace("@USER@", user).replace("@PYTHON@", python)
            .replace("@INSTALL_DIR@", str(install_dir)).replace("@CONFIG_DIR@", str(config_dir)))


# -- environment discovery -------------------------------------------------------------
def detect_config_dir(explicit: Optional[str], home: Path) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not (p / "printer.cfg").is_file():
            raise InstallError(f"no printer.cfg in {p}")
        return p
    for cand in (home / "printer_data" / "config", Path("/var/lib/moonraker/config")):
        if (cand / "printer.cfg").is_file():
            return cand
    raise InstallError("could not find a Klipper config directory (a folder containing printer.cfg); "
                       "pass --klipper-config DIR")


def has_pyserial(python: str) -> bool:
    try:
        return subprocess.run([python, "-c", "import serial"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_python(explicit: Optional[str], repo_root: Path) -> str:
    candidates = ([explicit] if explicit else []) + [str(repo_root / "backend" / ".venv" / "bin" / "python"),
                                                    str(HERE / ".venv" / "bin" / "python"), sys.executable]
    for c in candidates:
        if c and Path(c).exists() and has_pyserial(c):
            return c
    raise InstallError("no Python with pyserial found. Install it (e.g. `python3 -m venv "
                       f"{HERE / '.venv'} && {HERE / '.venv' / 'bin' / 'pip'} install pyserial`) or pass --python")


# -- actions ---------------------------------------------------------------------------
class Installer:
    def __init__(self, config_dir: Path, python: str, user: str, dry_run=False, run: Callable = None, log=print):
        self.config_dir, self.python, self.user = config_dir, python, user
        self.dry = dry_run
        self._run = run or (lambda cmd, **kw: subprocess.run(cmd, check=True, **kw))
        self.log = log

    def _say(self, msg):
        self.log(("[dry-run] " if self.dry else "") + msg)

    def _write(self, path: Path, text: str):
        if not self.dry:
            path.write_text(text, encoding="utf-8")

    def install_ini(self):
        dest = self.config_dir / INI_NAME
        if dest.exists():
            return self._say(f"keep existing {dest}")
        self._say(f"create {dest}")
        if not self.dry:
            shutil.copy(HERE / INI_NAME, dest)

    def install_klipper_cfg(self):
        dest = self.config_dir / CFG_NAME
        if dest.exists():
            self._say(f"keep existing {dest}")
        else:
            others = [p for p in self.config_dir.glob("*.cfg") if p.name != CFG_NAME]
            text, skipped = dedupe_against((HERE / CFG_NAME).read_text(encoding="utf-8"), others)
            self._say(f"create {dest}" + (f" (disabled duplicates: {', '.join(skipped)})" if skipped else ""))
            self._write(dest, text)
        printer = self.config_dir / "printer.cfg"
        new = add_include(printer.read_text(encoding="utf-8"), CFG_NAME)
        if new is None:
            return self._say(f"{printer} already includes {CFG_NAME}")
        backup = printer.with_name(f"printer.cfg.indus3d_bak_{time.strftime('%Y%m%d-%H%M%S')}")
        self._say(f"back up printer.cfg -> {backup.name}; add [include {CFG_NAME}]")
        if not self.dry:
            shutil.copy(printer, backup)
            printer.write_text(new, encoding="utf-8")

    def service_text(self) -> str:
        return render_service(TEMPLATE.read_text(encoding="utf-8"), self.user, self.python, HERE, self.config_dir)

    def install_service(self):
        if not shutil.which("systemctl"):
            return self._say("systemd not found: skipping the service (run the daemon yourself, see the README)")
        self._say(f"install {SYSTEMD_DIR / SERVICE_NAME} and enable it")
        if self.dry:
            return
        tmp = self.config_dir / f".{SERVICE_NAME}.tmp"
        tmp.write_text(self.service_text(), encoding="utf-8")
        try:
            self._run(["sudo", "install", "-m", "644", str(tmp), str(SYSTEMD_DIR / SERVICE_NAME)])
        finally:
            tmp.unlink(missing_ok=True)
        self._run(["sudo", "systemctl", "daemon-reload"])
        self._run(["sudo", "systemctl", "enable", "--now", SERVICE_NAME])

    def uninstall(self, purge=False):
        if shutil.which("systemctl") and (SYSTEMD_DIR / SERVICE_NAME).exists():
            self._say(f"stop, disable and remove {SERVICE_NAME}")
            if not self.dry:
                for cmd in (["stop", SERVICE_NAME], ["disable", SERVICE_NAME]):
                    subprocess.run(["sudo", "systemctl", *cmd], check=False)
                self._run(["sudo", "rm", "-f", str(SYSTEMD_DIR / SERVICE_NAME)])
                self._run(["sudo", "systemctl", "daemon-reload"])
        printer = self.config_dir / "printer.cfg"
        if printer.exists():
            new = remove_include(printer.read_text(encoding="utf-8"), CFG_NAME)
            if new is not None:
                backup = printer.with_name(f"printer.cfg.indus3d_bak_{time.strftime('%Y%m%d-%H%M%S')}")
                self._say(f"back up printer.cfg -> {backup.name}; remove the include")
                if not self.dry:
                    shutil.copy(printer, backup)
                    printer.write_text(new, encoding="utf-8")
        cfg = self.config_dir / CFG_NAME
        if cfg.exists():
            self._say(f"remove {cfg}")
            if not self.dry:
                cfg.unlink()
        ini = self.config_dir / INI_NAME
        if purge and ini.exists():
            self._say(f"remove {ini} (--purge)")
            if not self.dry:
                ini.unlink()
        elif ini.exists():
            self._say(f"kept {ini} (your calibration settings; use --purge to remove)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--klipper-config", help="Klipper config directory (contains printer.cfg)")
    ap.add_argument("--python", help="Python with pyserial for the service")
    ap.add_argument("--user", default=getpass.getuser())
    ap.add_argument("--no-service", action="store_true")
    ap.add_argument("--no-klipper", action="store_true", help="skip the Klipper config changes")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if os.geteuid() == 0:
        print("Run as your normal user, not root (sudo is used where needed).", file=sys.stderr)
        return 1
    try:
        cfg_dir = detect_config_dir(args.klipper_config, Path.home())
        inst = Installer(cfg_dir, "", args.user, args.dry_run)
        if args.uninstall:
            inst.uninstall(args.purge)
            return 0
        inst.python = pick_python(args.python, HERE.parent.parent)
        inst.install_ini()
        if not args.no_klipper:
            inst.install_klipper_cfg()
        if not args.no_service:
            inst.install_service()
    except InstallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("Done. Configure the sensor in " + str(cfg_dir / INI_NAME) + ", then FIRMWARE_RESTART Klipper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
