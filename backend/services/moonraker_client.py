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
