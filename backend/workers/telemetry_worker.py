"""
workers/telemetry_worker.py
----------------------------
Polls Klipper at 10 Hz. Runs all digital twin models and the quality
controller. Exposes .latest for the WebSocket push.

live_commands: a deque of the last N commands sent by the quality
controller or the user terminal, surfaced in the WS payload so the
frontend G-code terminal can show them without a separate endpoint.
"""

import logging
import threading
import time
from collections import deque

import requests
from db.models import get_connection

from digital_twin.state import printer_state
from digital_twin.kinematic_model import kinematic_model
from digital_twin.thermal_model import thermal_model
from digital_twin.extrusion_model import extrusion_model
from digital_twin.snapshot_logger import log_snapshot
from digital_twin.quality_controller import quality_controller
from core.alert_actions import execute_alert_action, clear_actioned
from core.notifications import notify, pop_ui_notifications
from core.timelapse import current_job as timelapse_job
from services.spoolman_client import get_spool_price_per_g
from config.loader import get_timelapse_cfg
from services import led_controller
from config import led_profiles
from config import printers as printer_registry
from services.moonraker_client import MoonrakerClient
from services.pzem_monitor import pzem_monitor
from services.disk_monitor import disk_monitor
from config.settings import settings
from digital_twin.vibration_monitor import vibration_monitor
from workers.dsp_bridge import dsp_bridge
from digital_twin.bed_safety import bed_safety

POLL_HZ = settings.TWIN_TICK_HZ

KLIPPER_OBJECTS = (
    "toolhead&motion_report&extruder&heater_bed"
    "&print_stats&display_status&gcode_move&exclude_object"
)

_moonraker = MoonrakerClient()


class TelemetryWorker:
    def __init__(self):
        self.latest: dict = {
            "online": False,
            "sim": False,
            "print_state": "offline",
            "cmd_x": 0.0, "cmd_y": 0.0, "cmd_z": 0.0, "cmd_e": 0.0,
            "live_x": 0.0, "live_y": 0.0, "live_z": 0.0,
            "ext_temp": 0.0, "ext_target": 0.0, "ext_pwm": 0.0,
            "bed_temp": 0.0, "bed_target": 0.0,
            "progress": 0.0,
            "quality": {"active": quality_controller.active, "corrections": []},
            "kinematics": {},
            "thermals": {},
            "extrusion": {},
            "vibration": {},
            "power": {},
            "disk": {},
            "exclude_object": {},
            "live_commands": [],
        }
        # live_commands: last 20 commands sent (quality controller + manual)
        # Each entry: {"text": str, "ts": float}
        self.live_commands: deque = deque(maxlen=20)
        # Edge-tracking for runaway flags, so the safety response can
        # auto re-arm after the condition resolves instead of firing once
        # and staying permanently deduplicated for the process lifetime.
        self._ext_runaway_prev = False
        self._bed_runaway_prev = False
        # Print-state edge tracking, for print-complete/failed notifications
        # firing exactly once per transition rather than every tick.
        self._prev_print_state = None
        self._print_start_time = 0
        self._print_start_fil_m = 0
        self._print_start_wh = 0
        self._last_pos = None
        self._last_ext_target = 0
        self._last_bed_target = 0
        self._odom_x_m = 0.0
        self._odom_y_m = 0.0
        self._odom_z_m = 0.0
        self._ext_cycles = 0
        self._bed_cycles = 0
        self._nozzle_seconds = 0.0
        self._filter_seconds = 0.0
        self._last_db_flush_time = time.time()
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        # LED state — refreshed from disk every 5s in _refresh_led_profile()
        self._led_profile              = None
        self._led_profile_refresh_time = 0.0
        self._last_led_state           = None
        self._last_led_gradient_pct    = None

    def start(self):
        self._thread.start()
        logging.info("📡 TelemetryWorker started")


    def _refresh_led_profile(self):
        """Re-read the active printer's LED profile from disk, at most
        every 5s (see the comment on self._led_profile in __init__)."""
        if time.time() - self._led_profile_refresh_time < 5.0:
            return
        self._led_profile_refresh_time = time.time()
        try:
            active_id = printer_registry.list_printers()["active"]
            self._led_profile = led_profiles.get_profile(active_id)
        except Exception as e:
            logging.info(f"⚠️  Could not load LED profile: {e}")
            self._led_profile = None

    def _send_led_color(self, profile: dict, hex_color: str):
        """Apply the profile's brightness scale, then push to every LED
        the profile is configured to drive."""
        scaled = led_controller.scale_hex(hex_color, profile.get("brightness", 100))
        led_controller.set_leds(profile["led_names"], scaled)

    def _apply_led_state(self, print_state: str, ext_temp, ext_target, bed_temp, bed_target, progress: float = 0.0):
        self._refresh_led_profile()
        profile = self._led_profile
        if not profile or not profile.get("enabled") or not profile.get("led_names"):
            return

        state_key = "idle"
        if print_state in ("error", "cancelled"):
            state_key = "error"
        elif print_state == "paused":
            state_key = "paused"
        elif print_state == "complete":
            state_key = "complete"
        elif print_state == "printing":
            heating = (ext_target > 0 and ext_temp < ext_target - 3) or (bed_target > 0 and bed_temp < bed_target - 3)
            state_key = "heating" if heating else "printing"

        if state_key == "printing" and profile.get("printing_gradient"):
            if self._last_led_state != "printing":
                self._last_led_gradient_pct = None  # just entered printing — force an immediate send
            self._last_led_state = "printing"
            pct = int(round((progress or 0.0) * 100))
            if pct == self._last_led_gradient_pct:
                return
            self._last_led_gradient_pct = pct
            self._send_led_color(profile, led_controller.progress_gradient_color(pct))
            return

        if state_key == self._last_led_state:
            return  # no change — don't spam SET_LED every tick
        self._last_led_state = state_key
        self._last_led_gradient_pct = None  # reset so re-entering gradient mode later starts fresh

        color = profile["colors"].get(state_key)
        if color:
            self._send_led_color(profile, color)

    def stop(self):
        self._running = False

    def _loop(self):
        interval = 1.0 / POLL_HZ
        while self._running:
            t0 = time.time()
            try:
                self._tick()
            except Exception as e:
                logging.info(f"⚠️  TelemetryWorker: {e}")
            time.sleep(max(0.0, interval - (time.time() - t0)))

    def _flush_maintenance(self):
        if (self._odom_x_m == 0 and self._odom_y_m == 0 and self._odom_z_m == 0 and
            self._ext_cycles == 0 and self._bed_cycles == 0 and
            self._nozzle_seconds == 0 and self._filter_seconds == 0):
            self._last_db_flush_time = time.time()
            return

        try:
            conn = get_connection()
            c = conn.cursor()
            def add_val(task, v):
                if v == 0: return
                c.execute("UPDATE maintenance_counters SET value = value + ? WHERE task_id = ?", (v, task))
                if c.rowcount == 0:
                    c.execute("INSERT INTO maintenance_counters (task_id, value) VALUES (?, ?)", (task, v))

            add_val("odometry_x_m", self._odom_x_m)
            add_val("odometry_y_m", self._odom_y_m)
            add_val("odometry_z_m", self._odom_z_m)
            add_val("ext_heat_cycles", self._ext_cycles)
            add_val("bed_heat_cycles", self._bed_cycles)
            add_val("nozzle_hours", self._nozzle_seconds / 3600.0)
            add_val("filter_hours", self._filter_seconds / 3600.0)

            conn.commit()
            conn.close()

            self._odom_x_m = 0.0
            self._odom_y_m = 0.0
            self._odom_z_m = 0.0
            self._ext_cycles = 0
            self._bed_cycles = 0
            self._nozzle_seconds = 0.0
            self._filter_seconds = 0.0
            self._last_db_flush_time = time.time()
        except Exception as e:
            logging.info(f"⚠️  Error saving maintenance data: {e}")

    def _tick(self):

        url = f"{settings.moonraker_url}/printer/objects/query?{KLIPPER_OBJECTS}"
        try:
            res = requests.get(url, timeout=1.0)
        except Exception:
            printer_state.update({"online": False})
            self.latest["online"] = False
            self.latest["print_state"] = "offline"
            return

        if not res.ok:
            printer_state.update({"online": False})
            self.latest["online"] = False
            self.latest["print_state"] = "offline"
            return

        data = res.json().get("result", {}).get("status", {})

        th  = data.get("toolhead",       {})
        mr  = data.get("motion_report",  {})
        ext = data.get("extruder",       {})
        bed = data.get("heater_bed",     {})
        ps  = data.get("print_stats",    {})
        ds  = data.get("display_status", {})
        gm  = data.get("gcode_move",     {})

        cp = th.get("position",      [0, 0, 0, 0])
        lp = mr.get("live_position", [0, 0, 0, 0])

        progress       = ds.get("progress",       0.0)
        print_duration = ps.get("print_duration", 0.0)
        file_position  = ps.get("file_position",  0)

        time_remaining = 0
        if progress > 0.01:
            time_remaining = int((print_duration / progress) * (1.0 - progress))

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
            "live_e":          round(lp[3], 3) if len(lp) > 3 else 0.0,
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

# --- Maintenance Tracking ---
        if self._last_pos:
            self._odom_x_m += abs(lp[0] - self._last_pos[0]) / 1000.0
            self._odom_y_m += abs(lp[1] - self._last_pos[1]) / 1000.0
            self._odom_z_m += abs(lp[2] - self._last_pos[2]) / 1000.0
        self._last_pos = lp

        ext_t = ext.get("target", 0)
        if ext_t > 50 and self._last_ext_target <= 50: self._ext_cycles += 1
        self._last_ext_target = ext_t

        bed_t = bed.get("target", 0)
        if bed_t > 40 and self._last_bed_target <= 40: self._bed_cycles += 1
        self._last_bed_target = bed_t

        if update["print_state"] == "printing":
            self._nozzle_seconds += (1.0 / POLL_HZ)
            self._filter_seconds += (1.0 / POLL_HZ)

        if time.time() - self._last_db_flush_time > 5.0:
            self._flush_maintenance()
        # ----------------------------

        printer_state.update(update)

        snap = printer_state.snapshot()
        in_screw_zone, zone_idx = bed_safety.is_in_exclusion_zone(
            snap.get("live_x", 0.0), snap.get("live_y", 0.0), snap.get("live_z", 0.0)
        )
        snap["bed_collision_hazard"] = in_screw_zone
        snap["bed_collision_zone"] = zone_idx

        kin  = kinematic_model.update(snap)
        thm  = thermal_model.update(snap)
        ext_ = extrusion_model.update(snap)

        # Critical alerts act immediately from here, not from a frontend
        # HTTP call — a runaway with nobody looking at the dashboard still
        # needs M112 (and, if configured, a physical power cutoff) to fire.
        # See core/alert_actions.py: this is deduplicated internally, safe
        # to call every tick.
        # Critical alerts act immediately from here, not from a frontend
        # HTTP call — a runaway with nobody looking at the dashboard still
        # needs M112 (and, if configured, a physical power cutoff) to fire.
        # See core/alert_actions.py: this is deduplicated internally, safe
        # to call every tick. Falling edge re-arms it for next time.
        ext_runaway = bool(thm.get("ext_runaway_flag"))
        bed_runaway = bool(thm.get("bed_runaway_flag"))
        if ext_runaway:
            execute_alert_action("ext_runaway", snap["print_state"])
        elif self._ext_runaway_prev:
            clear_actioned("ext_runaway")
        if bed_runaway:
            execute_alert_action("bed_runaway", snap["print_state"])
        elif self._bed_runaway_prev:
            clear_actioned("bed_runaway")
        self._ext_runaway_prev = ext_runaway
        self._bed_runaway_prev = bed_runaway

        # Print completion/failure notification, and timelapse start/finish —
        # both fire once on the actual transition, not every tick.
        cur_state = snap["print_state"]
        if self._prev_print_state != "printing" and cur_state == "printing":
            if get_timelapse_cfg().get("enabled"):
                timelapse_job.start(snap.get("filename", ""))
            self._print_start_time = time.time()
            self._print_start_fil_m = ext_.get("filament_consumed_m", 0.0)
            self._print_start_wh = pzem_monitor.read().get("energy_wh", 0.0)

        if self._prev_print_state == "printing" and cur_state != "printing":
            if cur_state == "complete":
                notify(f"✅ Indus3D: print completed ({snap.get('filename', 'unknown file')})")
            elif cur_state in ("error", "cancelled"):
                notify(f"🛑 Indus3D: print {cur_state} ({snap.get('filename', 'unknown file')})")
            timelapse_job.finish(cur_state)

            # Log to print_history
            try:
                duration_s = time.time() - self._print_start_time
                fil_used_g = (ext_.get("filament_consumed_m", 0.0) - self._print_start_fil_m) * 3.0 # Approx 3g per meter of 1.75 PLA
                power_used_wh = pzem_monitor.read().get("energy_wh", 0.0) - self._print_start_wh

                # Active Spoolman calculation (optional, fallback to 0 cost if not available)
                price_per_g = get_spool_price_per_g()
                cost = fil_used_g * price_per_g
                # Add a bit for electricity (e.g. $0.15 / kWh)
                cost += (power_used_wh / 1000.0) * 0.15

                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT MAX(id) FROM config_history")
                conf_row = c.fetchone()
                config_id = conf_row[0] if conf_row and conf_row[0] else None

                c.execute('''
                    INSERT INTO print_history
                    (filename, status, print_time_seconds, filament_used_g, power_used_wh, cost_usd, config_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (snap.get("filename", "unknown"), cur_state, duration_s, fil_used_g, power_used_wh, cost, config_id))
                history_id = c.lastrowid

                # Update total lifetime stats in odometry
                c.execute("UPDATE odometry SET travel_meters = travel_meters + ? WHERE axis = 'E'",
                          (ext_.get("filament_consumed_m", 0.0) - self._print_start_fil_m,))

                # Update virtual spool usage
                c.execute("SELECT value FROM printer_config WHERE key = 'virtual_spool_used_g'")
                row = c.fetchone()
                used_g = float(row[0]) if row else 0.0
                used_g += fil_used_g
                c.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('virtual_spool_used_g', ?)", (str(used_g),))

                conn.commit()
                conn.close()

                if cur_state == "complete":
                    from services.qa_reporter import trigger_qa_report
                    trigger_qa_report(history_id, self._print_start_time, time.time(), snap.get("filename", "unknown"))
            except Exception as e:
                logging.info(f"⚠️  Error saving print history: {e}")

        self._prev_print_state = cur_state

        # Quality controller — send corrective commands and log them
        if snap["print_state"] == "printing":
            if get_timelapse_cfg().get("enabled"):
                timelapse_job.maybe_capture(snap["cmd_z"])
            cmds = quality_controller.update(snap, kin, thm, ext_)
            for cmd in cmds:
                ok = _moonraker.send_gcode(cmd)
                tag = "[QC]" if ok else "[QC FAIL]"
                self.live_commands.append({"text": f"{tag} {cmd}", "ts": time.time()})

        if snap["print_state"] == "printing":
            log_snapshot(snap, kin, thm, ext_)

        # Vibration monitor — reads latest DSP result and raises alerts
        vib_dict, _vib_alerts = vibration_monitor.update(
            dsp_bridge.latest, snap["print_state"]
        )

        # LED state management
        self._apply_led_state(
            snap["print_state"],
            snap.get("ext_temp", 0), snap.get("ext_target", 0),
            snap.get("bed_temp", 0), snap.get("bed_target", 0),
            snap.get("progress", 0.0),
        )

        self.latest = {
            **snap,
            "power":         pzem_monitor.read(),
            "disk":          disk_monitor.check(),
            "kinematics":    kin,
            "thermals":      thm,
            "extrusion":     ext_,
            "vibration":     vib_dict,
            "exclude_object": data.get("exclude_object", {}),
            # live_commands surfaces quality controller + user terminal commands
            # so the frontend G-code terminal can show them
            "live_commands": list(self.live_commands)[-10:],
            "notifications": pop_ui_notifications(),
            "quality": {
                "active":      quality_controller.active,
                "corrections": quality_controller.corrections[:10],
            },
        }


telemetry_worker = TelemetryWorker()
