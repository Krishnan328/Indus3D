import requests
from config.loader import get_moonraker_url

class MoonrakerClient:
    def __init__(self):
        self.base_url = get_moonraker_url()

    def send_gcode(self, gcode: str):
        try:
            res=requests.post(f"{self.base_url}/printer/gcode/script",params={"script":gcode},timeout=3)
            return res.ok
        except Exception as e: print(f"🔴 Moonraker error: {e}"); return False

    def get_printer_state(self):
        try:
            res=requests.get(f"{self.base_url}/printer/info",timeout=3)
            if res.ok:
                data=res.json(); state=data.get("result",{}).get("state","unknown")
                msg=data.get("result",{}).get("state_message","")
                return state, msg
        except Exception as e: print(f"🔴 State fetch error: {e}")
        return "unknown","no response"
