# ======================================================================= #
#  Indus3D extension for KIAUH - Klipper Installation And Update Helper    #
#  https://github.com/dw-0/kiauh                                           #
#                                                                          #
#  Drop the `indus3d` folder into `kiauh/kiauh/extensions/` (see            #
#  helpers/kiauh/install_extension.sh) and it appears in KIAUH's            #
#  Extensions menu, next to Mobileraker, Obico, Telegram Bot, ...           #
# ======================================================================= #

import shutil
from pathlib import Path
from shutil import which
from subprocess import run
from typing import List

from components.klipper.klipper import Klipper
from components.moonraker.moonraker import Moonraker
from core.instance_manager.instance_manager import InstanceManager
from core.logger import DialogType, Logger
from core.services.backup_service import BackupService
from extensions.base_extension import BaseExtension
from extensions.indus3d import (
    INDUS_BACKEND_DIR,
    INDUS_BRANCH,
    INDUS_CFG_NAME,
    INDUS_CFG_SRC,
    INDUS_DEPS,
    INDUS_DIR,
    INDUS_ENV,
    INDUS_FRONTEND_DIR,
    INDUS_KLIPPER_MODULE_SRC,
    INDUS_PORT,
    INDUS_REPO,
    INDUS_REQ_FILE,
    INDUS_SENSOR_INSTALLER,
    INDUS_SENSOR_SERVICE,
    INDUS_SERVICE,
    INDUS_TRACKER_SCRIPT,
    INDUS_TRACKER_SERVICE,
    KLIPPER_EXTRAS,
    KLIPPER_MODULE_NAME,
)
from utils.common import check_install_dependencies
from utils.config_utils import add_config_section, remove_config_section
from utils.fs_utils import remove_with_sudo
from utils.git_utils import git_clone_wrapper, git_pull_wrapper
from utils.input_utils import get_confirm
from utils.instance_utils import get_instances
from utils.sys_utils import (
    cmd_sysctl_manage,
    cmd_sysctl_service,
    create_python_venv,
    create_service_file,
    get_current_user,
    get_ipv4_addr,
    install_python_requirements,
    remove_system_service,
)

UPDATE_MANAGER_SECTION = "update_manager indus3d"


# noinspection PyMethodMayBeStatic
class Indus3dExtension(BaseExtension):
    # ── install ──────────────────────────────────────────────────────────────
    def install_extension(self, **kwargs) -> None:
        Logger.print_status("Installing Indus3D ...")

        mr_instances: List[Moonraker] = get_instances(Moonraker)
        kl_instances: List[Klipper] = get_instances(Klipper)
        if not mr_instances or not kl_instances:
            Logger.print_dialog(
                DialogType.WARNING,
                [
                    "Klipper and/or Moonraker not found!",
                    "Indus3D talks to Klipper through Moonraker. "
                    "Please install both first.",
                ],
            )
            return

        Logger.print_dialog(
            DialogType.INFO,
            [
                "Indus3D is single-tenant: one backend service "
                f"('{INDUS_SERVICE}', port {INDUS_PORT}) serves the whole host.",
                "It will be wired to these instances:",
                *[f"● {i.service_file_path.name}" for i in mr_instances],
                "\n\n",
                f"Source: {INDUS_REPO} ({INDUS_BRANCH})",
            ],
        )
        if not get_confirm("Continue Indus3D installation?", True, allow_go_back=True):
            return

        install_tracker = get_confirm(
            "Also install the corrective G-code tracker (read-only logger)?", True
        )
        install_sensor = get_confirm(
            "Also install the smart filament sensor daemon? (only with the sensor hardware)", False
        )
        install_vibration = KLIPPER_EXTRAS.exists() and get_confirm(
            "Link the ADXL vibration streaming module into Klipper?", False
        )

        try:
            git_clone_wrapper(INDUS_REPO, INDUS_DIR, INDUS_BRANCH)
            self._install_dependencies()

            self._install_klipper_integration(kl_instances)
            if install_vibration:
                self._link_vibration_module(kl_instances)

            self._create_service(INDUS_SERVICE)
            if install_sensor:
                self._run_sensor_installer(kl_instances)
            if install_tracker:
                self._create_tracker_service()

            BackupService().backup_moonraker_conf()
            self._patch_update_manager(mr_instances)
            InstanceManager.restart_all(mr_instances)

            Logger.print_dialog(
                DialogType.CUSTOM,
                [
                    "Indus3D installed!",
                    f"Dashboard: http://{get_ipv4_addr()}:{INDUS_PORT}",
                    "\n\n",
                    "Closed-loop corrections are OFF by default. Until the "
                    "auto-pilot is enabled, Indus3D observes and calculates "
                    "but sends no corrective G-code.",
                    "Enable it from the dashboard, or with a POST to "
                    "/api/v1/twin/auto-pilot {\"enabled\": true}.",
                ],
                custom_title="INDUS3D",
                margin_bottom=1,
            )
        except Exception as e:
            Logger.print_error(f"Error during installation of Indus3D:\n{e}")

    # ── update ───────────────────────────────────────────────────────────────
    def update_extension(self, **kwargs) -> None:
        Logger.print_status("Updating Indus3D ...")
        if not INDUS_DIR.exists():
            Logger.print_warn("Indus3D is not installed. Nothing to update.")
            return
        try:
            self._stop(INDUS_SERVICE)
            self._stop(INDUS_TRACKER_SERVICE)
            self._stop(INDUS_SENSOR_SERVICE)
            git_pull_wrapper(INDUS_DIR)
            self._install_dependencies()
            self._start(INDUS_SERVICE)
            self._start(INDUS_TRACKER_SERVICE)
            self._start(INDUS_SENSOR_SERVICE)
            Logger.print_ok("Indus3D updated!")
        except Exception as e:
            Logger.print_error(f"Error during update of Indus3D:\n{e}")

    # ── remove ───────────────────────────────────────────────────────────────
    def remove_extension(self, **kwargs) -> None:
        Logger.print_status("Removing Indus3D ...")
        mr_instances: List[Moonraker] = get_instances(Moonraker)
        kl_instances: List[Klipper] = get_instances(Klipper)

        try:
            remove_system_service(INDUS_TRACKER_SERVICE)
            remove_system_service(INDUS_SERVICE)
            self._run_sensor_installer(kl_instances, uninstall=True)

            BackupService().backup_moonraker_conf()
            remove_config_section(UPDATE_MANAGER_SECTION, mr_instances)
            self._remove_klipper_integration(kl_instances)

            # Keep the checkout by default: it can hold the user's database,
            # captured telemetry and sensor calibration under backend/.
            if INDUS_DIR.exists() and get_confirm(
                f"Delete '{INDUS_DIR}' including its database and captures?",
                False,
            ):
                shutil.rmtree(INDUS_DIR)
            else:
                Logger.print_info(f"Kept '{INDUS_DIR}'.")
            Logger.print_ok("Indus3D removed!")
        except Exception as e:
            Logger.print_error(f"Error during removal of Indus3D:\n{e}")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _install_dependencies(self) -> None:
        check_install_dependencies(set(INDUS_DEPS))
        if create_python_venv(INDUS_ENV, interactive=False) or INDUS_ENV.exists():
            install_python_requirements(INDUS_ENV, INDUS_REQ_FILE)
        self._build_frontend()

    def _build_frontend(self) -> None:
        if INDUS_FRONTEND_DIR.joinpath("dist/index.html").exists():
            return
        if which("npm") is None:
            Logger.print_warn(
                "npm not found: the dashboard bundle was not built. Install "
                "nodejs/npm and run 'npm install && npm run build' in "
                f"'{INDUS_FRONTEND_DIR}'."
            )
            return
        Logger.print_status("Building the dashboard (npm) ...")
        for cmd in (["npm", "install", "--no-audit", "--no-fund"], ["npm", "run", "build"]):
            if run(cmd, cwd=INDUS_FRONTEND_DIR).returncode != 0:
                Logger.print_warn(f"'{' '.join(cmd)}' failed; dashboard not built.")
                return

    def _run_sensor_installer(self, kl_instances: List[Klipper], uninstall: bool = False) -> None:
        """Install (or remove) the filament sensor daemon via its own installer, using Indus3D's venv
        (it already has pyserial). The installer is idempotent and keeps the user's sensor settings."""
        if not INDUS_SENSOR_INSTALLER.exists() or not kl_instances:
            return
        cmd = [str(INDUS_ENV.joinpath("bin/python")), str(INDUS_SENSOR_INSTALLER),
               "--klipper-config", str(kl_instances[0].base.cfg_dir)]
        cmd += ["--uninstall"] if uninstall else ["--python", str(INDUS_ENV.joinpath("bin/python"))]
        Logger.print_status(f"{'Removing' if uninstall else 'Installing'} the filament sensor daemon ...")
        try:
            run(cmd, check=True)
        except Exception as e:  # noqa: BLE001 — the sensor is optional; never fail the Indus3D install over it
            Logger.print_warn(f"Filament sensor step did not complete: {e}")

    def _create_service(self, name: str) -> None:
        content = f"""[Unit]
Description=Indus3D Digital Twin and Quality Controller
After=network-online.target moonraker.service klipper.service
Wants=network-online.target

[Service]
Type=simple
User={get_current_user()}
WorkingDirectory={INDUS_BACKEND_DIR}
ExecStart={INDUS_ENV}/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
        create_service_file(name, content)
        cmd_sysctl_manage("daemon-reload")
        cmd_sysctl_service(name, "enable")
        cmd_sysctl_service(name, "start")

    def _create_tracker_service(self) -> None:
        if not INDUS_TRACKER_SCRIPT.exists():
            Logger.print_warn(f"Tracker script missing: '{INDUS_TRACKER_SCRIPT}'. Skipped.")
            return
        content = f"""[Unit]
Description=Indus3D corrective G-code tracker (read-only)
After={INDUS_SERVICE}
Wants={INDUS_SERVICE}

[Service]
Type=simple
User={get_current_user()}
WorkingDirectory={INDUS_DIR}
ExecStart={INDUS_ENV}/bin/python {INDUS_TRACKER_SCRIPT} --follow
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
        create_service_file(INDUS_TRACKER_SERVICE, content)
        cmd_sysctl_manage("daemon-reload")
        cmd_sysctl_service(INDUS_TRACKER_SERVICE, "enable")
        cmd_sysctl_service(INDUS_TRACKER_SERVICE, "start")

    def _install_klipper_integration(self, kl_instances: List[Klipper]) -> None:
        """Copy indus3d.cfg next to printer.cfg and [include] it."""
        BackupService().backup_printer_config_dir()
        for inst in kl_instances:
            target = inst.base.cfg_dir.joinpath(INDUS_CFG_NAME)
            Logger.print_status(f"Install '{INDUS_CFG_NAME}' in '{inst.base.cfg_dir}' ...")
            if not INDUS_CFG_SRC.exists():
                Logger.print_warn(f"'{INDUS_CFG_SRC}' missing in checkout. Skipped.")
                continue
            if target.exists():
                Logger.print_info("Already present. Skipped ...")
            else:
                shutil.copy(INDUS_CFG_SRC, target)
        add_config_section(f"include {INDUS_CFG_NAME}", kl_instances)

    def _remove_klipper_integration(self, kl_instances: List[Klipper]) -> None:
        remove_config_section(f"include {INDUS_CFG_NAME}", kl_instances)
        for inst in kl_instances:
            cfg = inst.base.cfg_dir.joinpath(INDUS_CFG_NAME)
            if cfg.exists():
                remove_with_sudo(cfg)
        module = KLIPPER_EXTRAS.joinpath(KLIPPER_MODULE_NAME)
        if module.is_symlink():
            module.unlink()

    def _link_vibration_module(self, kl_instances: List[Klipper]) -> None:
        if not INDUS_KLIPPER_MODULE_SRC.exists():
            Logger.print_warn("indus_vibration.py not found in the checkout. Skipped.")
            return
        InstanceManager.stop_all(kl_instances)
        try:
            Path(KLIPPER_EXTRAS.joinpath(KLIPPER_MODULE_NAME)).unlink(missing_ok=True)
            KLIPPER_EXTRAS.joinpath(KLIPPER_MODULE_NAME).symlink_to(INDUS_KLIPPER_MODULE_SRC)
            Logger.print_ok(f"Linked {KLIPPER_MODULE_NAME} into Klipper extras.")
        finally:
            InstanceManager.start_all(kl_instances)

    def _patch_update_manager(self, instances: List[Moonraker]) -> None:
        add_config_section(
            section=UPDATE_MANAGER_SECTION,
            instances=instances,
            options=[
                ("type", "git_repo"),
                ("path", str(INDUS_DIR)),
                ("origin", INDUS_REPO),
                ("primary_branch", INDUS_BRANCH),
                ("env", f"{INDUS_ENV}/bin/python"),
                ("requirements", "backend/requirements.txt"),
                ("is_system_service", "True"),
                ("managed_services", "indus3d"),
            ],
        )

    def _stop(self, name: str) -> None:
        try:
            cmd_sysctl_service(name, "stop")
        except Exception:
            pass  # optional units (the tracker) may not exist

    def _start(self, name: str) -> None:
        try:
            cmd_sysctl_service(name, "start")
        except Exception:
            pass
