"""
workers/telemetry_worker.py
-----------------------------
Polls Klipper at 10 Hz. On each tick:
  - Updates shared PrinterState
  - Runs all digital twin models
  - Runs QualityController and sends any corrective commands
  - Logs snapshot to DB during printing
"""

import threading
import time
import requests

from digital_twin.state import printer_state
from digital_twin.kinematic_model import kinematic_model
from digital_twin.thermal_model import thermal_model
from digital_twin.extrusion_model import extrusion_model
from digital_twin.snapshot_logger import log_snapshot
from digital_twin.quality_controller import quality_controller
from services.moonraker_client import MoonrakerClient
from config.loader import get_moonraker_url

POLL_HZ = 10

KLIPPER_OBJECTS = (
    "toolhead&motion_report&extruder&heater_bed"
    "&print_stats&display_status&gcode_move"
)

_moonraker_client = MoonrakerClient()


class TelemetryWorker:
    def __init__(self):
        self.latest: dict = {}
        self._running     = True
        self._thread      = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        print("📡 TelemetryWorker started")

    def stop(self):
        self._running = False

    def _loop(self):
        interval = 1.0 / POLL_HZ
        while self._running:
            start = time.time()
            try:
                self._tick()
            except Exception as e:
                print(f"⚠️  TelemetryWorker: {e}")
            time.sleep(max(0.0, interval - (time.time() - start)))

    def _tick(self):
        base  = get_moonraker_url()
        query = f"{base}/printer/objects/query?{KLIPPER_OBJECTS}"

        res = requests.get(query, timeout=1.0)
        if not res.ok:
            printer_state.update({"online": False})
            return

        data = res.json().get("result", {}).get("status", {})

        th  = data.get("toolhead",       {})
        mr  = data.get("motion_report",  {})
        ext = data.get("extruder",       {})
        bed = data.get("heater_bed",     {})
        ps  = data.get("print_stats",    {})
        ds  = data.get("display_status", {})
        gm  = data.get("gcode_move",     {})

        cp  = th.get("position",      [0, 0, 0, 0])
        lp  = mr.get("live_position", [0, 0, 0, 0])

        progress        = ds.get("progress", 0.0)
        print_duration  = ps.get("print_duration", 0.0)
        file_position   = ps.get("file_position", 0)

        time_remaining = 0
        if progress > 0.01:
            time_remaining = int((print_duration / progress) * (1.0 - progress))

        # Read current speed/flow factors set by quality controller
        speed_factor = round(gm.get("speed_factor",   1.0) * 100, 1)
        flow_factor  = round(gm.get("extrude_factor", 1.0) * 100, 1)

        update = {
            "online":          True,
            "cmd_x":           round(cp[0], 3),
            "cmd_y":           round(cp[1], 3),
            "cmd_z":           round(cp[2], 3),
            "cmd_e":           round(cp[3], 3),
            "live_x":          round(lp[0], 3),
            "live_y":          round(lp[1], 3),
            "live_z":          round(lp[2], 3),
            "velocity":        round(mr.get("live_velocity", 0.0), 3),
            "ext_temp":        ext.get("temperature", 0),
            "ext_target":      ext.get("target", 0),
            "ext_pwm":         round(ext.get("power", 0), 4),
            "bed_temp":        bed.get("temperature", 0),
            "bed_target":      bed.get("target", 0),
            "print_state":     ps.get("state", "standby"),
            "filename":        ps.get("filename", ""),
            "file_position":   file_position,
            "progress":        round(progress, 4),
            "print_duration":  int(print_duration),
            "time_remaining":  time_remaining,
            "speed_factor":    speed_factor,
            "flow_factor":     flow_factor,
        }

        printer_state.update(update)
        snap = printer_state.snapshot()

        kin  = kinematic_model.update(snap)
        thm  = thermal_model.update(snap)
        ext_ = extrusion_model.update(snap)

        # ── Quality controller — send corrective commands ─────────────────────
        commands = quality_controller.update(snap, kin, thm, ext_)
        for cmd in commands:
            _moonraker_client.send_gcode(cmd)

        if snap["print_state"] == "printing":
            log_snapshot(snap, kin, thm, ext_)

        self.latest = {
            **snap,
            "kinematics":   kin,
            "thermals":     thm,
            "extrusion":    ext_,
            "quality":      {
                "active":      quality_controller.active,
                "corrections": quality_controller.corrections[:10],
            },
        }


telemetry_worker = TelemetryWorker()
