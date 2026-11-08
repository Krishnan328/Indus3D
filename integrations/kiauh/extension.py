#!/usr/bin/env python3
"""
Indus3D - KIAUH Community Extension Integration Module
Compatible with KIAUH v6+ Extension Framework
"""

import os
import sys
import subprocess
import json

from extensions.base_extension import BaseExtension

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALLER_SCRIPT = os.path.join(SCRIPT_DIR, "indus3d_installer.sh")


class Indus3DExtension(BaseExtension):
    """KIAUH Extension Handler for Indus3D Digital Twin."""

    name = "Indus3D"
    description = "Edge Digital Twin, Vibration DSP & Closed-Loop Quality Controller"
    service_name = "indus3d.service"
    default_port = 5001

    def install_extension(self, **kwargs) -> None:
        if not self.install():
            raise RuntimeError("Indus3D installation failed; see installer output")

    def update_extension(self, **kwargs) -> None:
        if not self.update():
            raise RuntimeError("Indus3D update failed; see installer output")

    def remove_extension(self, **kwargs) -> None:
        if not self.remove():
            raise RuntimeError("Indus3D removal failed; see installer output")

    @staticmethod
    def _run_installer(action: str) -> bool:
        cmd = ["bash", INSTALLER_SCRIPT, action]
        result = subprocess.run(cmd)
        return result.returncode == 0

    def install(self) -> bool:
        """Invoked by KIAUH to install Indus3D."""
        return self._run_installer("install")

    def update(self) -> bool:
        """Invoked by KIAUH to update Indus3D."""
        return self._run_installer("update")

    def remove(self) -> bool:
        """Invoked by KIAUH to remove Indus3D."""
        return self._run_installer("remove")

    def start(self) -> bool:
        """Start systemd service."""
        return self._run_installer("start")

    def stop(self) -> bool:
        """Stop systemd service."""
        return self._run_installer("stop")

    def restart(self) -> bool:
        """Restart systemd service."""
        return self._run_installer("restart")

    def status(self) -> dict:
        """Returns the operational status of Indus3D to KIAUH."""
        is_active = False
        try:
            res = subprocess.run(
                ["systemctl", "is-active", "--quiet", self.service_name]
            )
            is_active = res.returncode == 0
        except Exception:
            pass

        return {
            "name": self.name,
            "installed": os.path.exists(
                os.path.expanduser("~/indus3d/backend/main.py")
            ),
            "active": is_active,
            "port": self.default_port,
            "status_text": "Running" if is_active else "Stopped",
        }


# Direct CLI compatibility
if __name__ == "__main__":
    with open(os.path.join(SCRIPT_DIR, "metadata.json"), encoding="utf-8") as stream:
        ext = Indus3DExtension(json.load(stream)["metadata"])
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "install":
        sys.exit(0 if ext.install() else 1)
    elif action == "update":
        sys.exit(0 if ext.update() else 1)
    elif action == "remove":
        sys.exit(0 if ext.remove() else 1)
    elif action == "status":
        print(json.dumps(ext.status(), indent=2))
        sys.exit(0)
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
