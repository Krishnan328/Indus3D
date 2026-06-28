import threading
import time

class PrinterState:
    def __init__(self):
        self._lock = threading.Lock()
        self.cmd_x = 0.0; self.cmd_y = 0.0; self.cmd_z = 0.0; self.cmd_e = 0.0
        self.live_x = 0.0; self.live_y = 0.0; self.live_z = 0.0
        self.velocity = 0.0
        self.ext_temp = 0.0; self.ext_target = 0.0; self.ext_pwm = 0.0
        self.bed_temp = 0.0; self.bed_target = 0.0
        self.print_state = "standby"; self.filename = ""; self.file_position = 0
        self.last_updated = time.time(); self.online = False

    def update(self, data: dict):
        with self._lock:
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            self.last_updated = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cmd_x": self.cmd_x, "cmd_y": self.cmd_y,
                "cmd_z": self.cmd_z, "cmd_e": self.cmd_e,
                "live_x": self.live_x, "live_y": self.live_y, "live_z": self.live_z,
                "velocity": self.velocity,
                "ext_temp": self.ext_temp, "ext_target": self.ext_target, "ext_pwm": self.ext_pwm,
                "bed_temp": self.bed_temp, "bed_target": self.bed_target,
                "print_state": self.print_state, "filename": self.filename,
                "file_position": self.file_position,
                "last_updated": self.last_updated, "online": self.online,
            }

printer_state = PrinterState()
