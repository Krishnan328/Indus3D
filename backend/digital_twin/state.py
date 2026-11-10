import threading
import time

class PrinterState:
    def __init__(self):
        self._lock = threading.Lock()
        self.cmd_x = 0.0; self.cmd_y = 0.0; self.cmd_z = 0.0; self.cmd_e = 0.0
        self.live_x = 0.0; self.live_y = 0.0; self.live_z = 0.0; self.live_e = 0.0
        self.velocity = 0.0
        self.homed_axes = ""
        self.is_homed = False
        self.ext_temp = 0.0; self.ext_target = 0.0; self.ext_pwm = 0.0
        self.bed_temp = 0.0; self.bed_target = 0.0
        self.fan_speed = 0.0
        self.speed_factor = 100.0
        self.flow_factor = 100.0
        self.progress = 0.0
        self.print_duration = 0
        self.time_remaining = 0
        self.print_state = "standby"; self.filename = ""; self.file_position = 0
        self.last_updated = time.time(); self.online = False
        self.klippy_state = "ready"
        self.klippy_connected = True
        self.state_message = ""
        self.device_temperatures = {}

    def update(self, data: dict):
        with self._lock:
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            self.last_updated = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "timestamp": self.last_updated,
                "last_updated": self.last_updated,
                "cmd_x": self.cmd_x, "cmd_y": self.cmd_y,
                "cmd_z": self.cmd_z, "cmd_e": self.cmd_e,
                "live_x": self.live_x, "live_y": self.live_y, "live_z": self.live_z,
                "live_e": self.live_e,
                "velocity": self.velocity,
                "homed_axes": self.homed_axes,
                "is_homed": self.is_homed,
                "ext_temp": self.ext_temp, "ext_target": self.ext_target, "ext_pwm": self.ext_pwm,
                "bed_temp": self.bed_temp, "bed_target": self.bed_target,
                "fan_speed": self.fan_speed,
                "speed_factor": self.speed_factor,
                "flow_factor": self.flow_factor,
                "progress": self.progress,
                "print_duration": self.print_duration,
                "time_remaining": self.time_remaining,
                "print_state": self.print_state, "filename": self.filename,
                "file_position": self.file_position,
                "last_updated": self.last_updated, "online": self.online,
                "klippy_state": self.klippy_state,
                "klippy_connected": self.klippy_connected,
                "state_message": self.state_message,
                "device_temperatures": dict(self.device_temperatures),
            }

printer_state = PrinterState()
