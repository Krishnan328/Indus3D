import logging
import requests
from config.settings import settings

class MoonrakerClient:
    def __init__(self):
        self.session = requests.Session()

    @property
    def base_url(self) -> str:
        return settings.moonraker_url

    def send_gcode(self, gcode: str) -> bool:
        """Send a G-code string to Moonraker. Returns True on success."""
        try:
            res = self.session.post(
                f"{self.base_url}/printer/gcode/script",
                params={"script": gcode},
                timeout=3,
            )
            if not res.ok:
                logging.warning(f"⚠️  Moonraker rejected gcode {gcode!r}: {res.status_code} {res.text[:120]}")
            return res.ok
        except Exception as e:
            logging.warning(f"🔴 Moonraker send_gcode error: {e}")
            return False

    def get_printer_state(self):
        try:
            res = self.session.get(f"{self.base_url}/printer/info", timeout=3)
            if res.ok:
                data  = res.json()
                state = data.get("result", {}).get("state", "unknown")
                msg   = data.get("result", {}).get("state_message", "")
                return state, msg
        except Exception as e:
            logging.warning(f"🔴 Moonraker state fetch error: {e}")
        return "unknown", "no response"

    def get_printer_info(self) -> dict:
        """Query Moonraker /printer/info and fallback to /server/info if disconnected.
        Returns a structured dictionary with connection and error diagnostics."""
        try:
            res = self.session.get(f"{self.base_url}/printer/info", timeout=2)
            if res.ok:
                data = res.json().get("result", {})
                state = data.get("state", "ready")
                msg = data.get("state_message", "")
                hostname = data.get("hostname", "")
                return {
                    "moonraker_online": True,
                    "state": state,
                    "state_message": msg,
                    "klippy_connected": state == "ready",
                    "hostname": hostname,
                }
            # If /printer/info returned non-200, check /server/info to see if Moonraker is up
            s_res = self.session.get(f"{self.base_url}/server/info", timeout=2)
            if s_res.ok:
                s_data = s_res.json().get("result", {})
                k_state = s_data.get("klippy_state", "disconnected")
                return {
                    "moonraker_online": True,
                    "state": k_state,
                    "state_message": "Klippy host process disconnected or not responding",
                    "klippy_connected": bool(s_data.get("klippy_connected", False)),
                    "hostname": "",
                }
        except Exception as e:
            return {
                "moonraker_online": False,
                "state": "offline",
                "state_message": f"Unable to reach Moonraker at {self.base_url}: {e}",
                "klippy_connected": False,
                "hostname": "",
            }
        return {
            "moonraker_online": False,
            "state": "offline",
            "state_message": "Unable to communicate with Moonraker",
            "klippy_connected": False,
            "hostname": "",
        }

    def firmware_restart(self) -> bool:
        """Restarts the firmware by resetting microcontrollers and restarting Klippy."""
        try:
            res = self.session.post(f"{self.base_url}/printer/firmware_restart", timeout=5)
            if res.ok:
                return True
            # Fallback to gcode script if endpoint not supported
            res = self.session.post(
                f"{self.base_url}/printer/gcode/script",
                params={"script": "FIRMWARE_RESTART"},
                timeout=5
            )
            return res.ok
        except Exception as e:
            logging.warning(f"🔴 Moonraker firmware_restart error: {e}")
            return False

    def restart_klipper(self) -> bool:
        """Restarts the Klippy host software process."""
        try:
            res = self.session.post(f"{self.base_url}/printer/restart", timeout=5)
            if res.ok:
                return True
            res = self.session.post(
                f"{self.base_url}/printer/gcode/script",
                params={"script": "RESTART"},
                timeout=5
            )
            return res.ok
        except Exception as e:
            logging.warning(f"🔴 Moonraker restart error: {e}")
            return False

    def restart_moonraker(self) -> bool:
        """Restarts the Moonraker server process."""
        try:
            res = self.session.post(f"{self.base_url}/server/restart", timeout=5)
            return res.ok
        except Exception as e:
            logging.warning(f"🔴 Moonraker server restart error: {e}")
            return False

    def set_power(self, device: str, action: str) -> bool:
        """action: 'on' or 'off'. Returns False (and logs) rather than
        raising, same failure style as send_gcode — callers on the
        telemetry thread must never be blocked by this."""
        if action not in ("on", "off"):
            logging.warning(f"🔴 set_power: invalid action {action!r}")
            return False
        try:
            res = self.session.post(
                f"{self.base_url}/machine/device_power/{action}",
                params={"device": device}, timeout=3,
            )
            return res.ok
        except Exception as e:
            logging.warning(f"🔴 Power device error ({device}): {e}")
            return False

    def get_gcode_store(self, count: int = 100) -> list:
        """Return recent Klipper console messages, or an empty list on error."""
        try:
            res = self.session.get(
                f"{self.base_url}/server/gcode_store",
                params={"count": count}, timeout=3,
            )
            if not res.ok:
                return []
            return res.json().get("result", {}).get("gcode_store", [])
        except Exception as e:
            logging.warning(f"🔴 gcode_store fetch error: {e}")
            return []
