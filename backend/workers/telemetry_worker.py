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
import os
import threading
import time
import urllib.parse
from collections import deque

import requests
from db.models import get_connection

from digital_twin.state import printer_state
from digital_twin.kinematic_model import kinematic_model
from digital_twin.thermal_model import thermal_model
from digital_twin.extrusion_model import extrusion_model
from digital_twin.snapshot_logger import log_snapshot
from digital_twin.quality_controller import quality_controller
from core import command_pipeline
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
from services.filament_sensor import filament_sensor
from services.bed_sensor import bed_sensor
from config.settings import settings
from digital_twin.vibration_monitor import vibration_monitor
from workers.dsp_bridge import dsp_bridge
from digital_twin.bed_safety import bed_safety
from core.job_tracker import JobEdges

POLL_HZ = settings.TWIN_TICK_HZ

KLIPPER_OBJECTS = (
    "toolhead&motion_report&extruder&heater_bed&fan"
    "&print_stats&display_status&gcode_move&exclude_object&virtual_sdcard"
)

_moonraker = MoonrakerClient()


def _energy_wh() -> float:
    """Metered energy in Wh. The PZEM monitor reports None while the meter is offline; arithmetic on that
    would raise and silently drop the print_history row, so treat it as 0."""
    try:
        value = pzem_monitor.read().get("energy_wh", 0.0)
    except Exception:  # noqa: BLE001
        return 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


class TelemetryWorker:
    def __init__(self):
        self.latest: dict = {}
        # live_commands: last 100 commands sent (quality controller + manual + moonraker responses)
        # Each entry: {"text": str, "ts": float}
        self.live_commands: deque = deque(maxlen=100)
        # Edge-tracking for runaway flags, so the safety response can
        # auto re-arm after the condition resolves instead of firing once
        # and staying permanently deduplicated for the process lifetime.
        self._ext_runaway_prev = False
        self._bed_runaway_prev = False
        # Print-state edge tracking, for print-complete/failed notifications
        # firing exactly once per transition rather than every tick.
        self._prev_print_state = None
        # Start/end of each job, including queued jobs that follow each other inside one poll interval
        self._edges = JobEdges()
        self._job_filename = ""
        self._last_fil_m = 0.0
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
        self._cond = threading.Condition()
        self._session = requests.Session()
        self._running = True
        self._last_valid_x = 0.0
        self._last_valid_y = 0.0
        self._last_valid_z = 0.0
        self._process_lock = threading.Lock()
        self._klipper_data = {}
        self._ws_connected = False
        self._klippy_state = "ready"
        self._klippy_connected = True
        self._klippy_msg = ""
        self._moonraker_online = True
        self._last_info_check = 0.0
        self._last_ws_msg_time = 0.0
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._ws_thread = threading.Thread(target=self._moonraker_ws_loop, daemon=True)
        # LED state — refreshed from disk every 5s in _refresh_led_profile()
        self._led_profile              = None
        self._led_profile_refresh_time = 0.0
        self._last_led_state           = None
        self._last_led_gradient_pct    = None
        self._extra_temp_sensors: list = []
        self._device_temperatures: dict = {}

    def _discover_temp_sensors(self) -> list:
        """Discovers additional temperature sensors (e.g. toolhead boards, MCU sensors, eddy probes)."""
        try:
            url = f"{settings.moonraker_url}/printer/objects/list"
            res = self._session.get(url, timeout=1.5)
            if res.ok:
                objects = res.json().get("result", {}).get("objects", [])
                sensors = [
                    obj for obj in objects
                    if any(obj.startswith(p) for p in (
                        "temperature_sensor ",
                        "temperature_probe ",
                        "temperature_fan ",
                        "bme280 ",
                        "htu21d ",
                        "lm75 ",
                        "heater_generic ",
                    ))
                ]
                if sensors:
                    self._extra_temp_sensors = sensors
                    return sensors
        except Exception as e:
            logging.debug(f"Failed to discover extra temperature sensors: {e}")
        return getattr(self, "_extra_temp_sensors", [])

    def _build_sub_req(self, req_id: int = 9999) -> dict:
        """Constructs Moonraker printer.objects.subscribe request payload including discovered temp sensors."""
        sub_objs = {
            "toolhead": None,
            "motion_report": None,
            "gcode_move": None,
            "extruder": None,
            "heater_bed": None,
            "print_stats": None,
            "display_status": None,
            "exclude_object": None,
            "virtual_sdcard": None,
        }
        for sensor in self._discover_temp_sensors():
            sub_objs[sensor] = None
        return {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {"objects": sub_objs},
            "id": req_id,
        }

    def inject_gcode(self, gcode: str) -> bool:
        """Inject a G-code command to Moonraker and log it to live_commands."""
        self.live_commands.append({"text": str(gcode), "ts": time.time()})
        return _moonraker.send_gcode(gcode)

    def set_temperature(self, heater: str, target: float) -> bool:
        """Set temperature target for extruder or heater_bed, optimistically updating local state."""
        try:
            target_val = float(target)
        except (ValueError, TypeError):
            return False
        if "bed" in heater.lower():
            target_val = max(0.0, min(150.0, target_val))
            cmd = f"M140 S{target_val:.1f}"
            with self._process_lock:
                self._klipper_data.setdefault("heater_bed", {})["target"] = target_val
                printer_state.update({"bed_target": target_val})
        else:
            target_val = max(0.0, min(350.0, target_val))
            cmd = f"M104 S{target_val:.1f}"
            with self._process_lock:
                self._klipper_data.setdefault("extruder", {})["target"] = target_val
                printer_state.update({"ext_target": target_val})
        return self.inject_gcode(cmd)

    def start(self):
        self._preload_gcode_store()
        self._thread.start()
        self._ws_thread.start()
        logging.info("📡 TelemetryWorker started (polling loop + Moonraker WebSocket)")

    def _preload_gcode_store(self):
        """Preload the last 50 gcode store entries from Moonraker on startup / connection."""
        try:
            res = self._session.get(f"{settings.moonraker_url}/server/gcode_store?count=50", timeout=3)
            if res.ok:
                items = res.json().get("result", {}).get("gcode_store", [])
                existing_texts = {cmd["text"] if isinstance(cmd, dict) else cmd for cmd in self.live_commands}
                for item in items:
                    msg = item.get("message", "")
                    ts = item.get("time", time.time())
                    if msg and msg not in existing_texts:
                        self.live_commands.append({"text": msg, "ts": ts})
                        existing_texts.add(msg)
        except Exception as e:
            logging.debug(f"Could not preload gcode_store: {e}")

    def wait_for_telemetry(self, timeout: float = 0.1) -> bool:
        """Blocks until a new telemetry snapshot is published or timeout expires."""
        with self._cond:
            return self._cond.wait(timeout)


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

    def _moonraker_ws_loop(self):
        """Connects to Moonraker WebSocket and subscribes to printer objects.
        Receives push updates (notify_status_update) in real time (sub-10ms),
        bypassing slow HTTP polling."""
        import json
        try:
            import simple_websocket
        except ImportError:
            logging.warning("⚠️ simple_websocket not available, using HTTP polling only")
            return

        ws_url = f"ws://{settings.MOONRAKER_HOST}:{settings.MOONRAKER_PORT}/websocket"

        while self._running:
            try:
                logging.info(f"🔌 Connecting to Moonraker WebSocket at {ws_url}...")
                ws = simple_websocket.Client.connect(ws_url)

                # 1. Query initial printer info to get immediate state & state_message
                info_req = {
                    "jsonrpc": "2.0",
                    "method": "printer.info",
                    "id": 9998,
                }
                ws.send(json.dumps(info_req))

                # 2. Subscribe to printer objects
                sub_req = self._build_sub_req(9999)
                ws.send(json.dumps(sub_req))
                self._ws_connected = True
                logging.info(f"🔌 Subscribed to Moonraker live telemetry stream (with {len(self._extra_temp_sensors)} extra sensors)")
                self._preload_gcode_store()

                while self._running:
                    raw = ws.receive()
                    if not raw:
                        break
                    self._last_ws_msg_time = time.time()
                    msg = json.loads(raw)
                    if msg.get("id") == 9998:
                        res = msg.get("result", {})
                        st = res.get("state", "ready")
                        msg_str = res.get("state_message", "")
                        self._klippy_state = st
                        self._klippy_connected = (st == "ready")
                        self._klippy_msg = msg_str
                        if st != "ready":
                            self._publish_disconnected_or_error(
                                online=True,
                                klippy_state=st,
                                klippy_connected=(st == "ready"),
                                state_message=msg_str,
                            )
                    elif msg.get("id") == 9999:
                        status = msg.get("result", {}).get("status", {})
                        for k, v in status.items():
                            if k not in self._klipper_data:
                                self._klipper_data[k] = {}
                            if isinstance(v, dict):
                                self._klipper_data[k].update(v)
                            else:
                                self._klipper_data[k] = v
                        self._process_data(self._klipper_data)
                    elif msg.get("method") == "notify_status_update":
                        patch = msg.get("params", [{}])[0]
                        for k, v in patch.items():
                            if k not in self._klipper_data:
                                self._klipper_data[k] = {}
                            if isinstance(v, dict):
                                self._klipper_data[k].update(v)
                            else:
                                self._klipper_data[k] = v
                        self._process_data(self._klipper_data)
                    elif msg.get("method") == "notify_gcode_response":
                        params = msg.get("params", [])
                        if params:
                            self.live_commands.append({"text": str(params[0]), "ts": time.time()})
                    elif msg.get("method") == "notify_klippy_shutdown":
                        params = msg.get("params", [])
                        err = str(params[0]) if params else "MCU shutdown"
                        self._klippy_state = "shutdown"
                        self._klippy_connected = False
                        self._klippy_msg = err
                        self._publish_disconnected_or_error(
                            online=True,
                            klippy_state="shutdown",
                            klippy_connected=False,
                            state_message=err,
                        )
                    elif msg.get("method") == "notify_klippy_disconnected":
                        self._klippy_state = "disconnected"
                        self._klippy_connected = False
                        self._klippy_msg = "Klippy host process disconnected"
                        self._publish_disconnected_or_error(
                            online=True,
                            klippy_state="disconnected",
                            klippy_connected=False,
                            state_message="Klippy host process disconnected",
                        )
                    elif msg.get("method") == "notify_klippy_ready":
                        self._klippy_state = "ready"
                        self._klippy_connected = True
                        self._klippy_msg = ""
                        printer_state.update({
                            "online": True,
                            "klippy_state": "ready",
                            "klippy_connected": True,
                            "state_message": "",
                        })
                        try:
                            ws.send(json.dumps(self._build_sub_req(9999)))
                            logging.info("🔌 Re-subscribed to Moonraker objects after notify_klippy_ready")
                        except Exception as sub_err:
                            logging.debug(f"Failed to resubscribe after ready: {sub_err}")
                    elif msg.get("method") == "notify_klippy_state_changed":
                        params = msg.get("params", [{}])
                        first = params[0] if params else {}
                        if isinstance(first, dict):
                            st = first.get("state", "ready")
                            msg_str = first.get("state_message", "")
                        else:
                            st = str(first)
                            msg_str = ""
                        self._klippy_state = st
                        self._klippy_connected = (st == "ready")
                        self._klippy_msg = msg_str
                        if st == "ready":
                            try:
                                ws.send(json.dumps(self._build_sub_req(9999)))
                                logging.info("🔌 Re-subscribed to Moonraker objects after notify_klippy_state_changed ready")
                            except Exception as sub_err:
                                logging.debug(f"Failed to resubscribe after state changed: {sub_err}")
                        else:
                            self._publish_disconnected_or_error(
                                online=True,
                                klippy_state=st,
                                klippy_connected=(st == "ready"),
                                state_message=msg_str,
                            )
            except Exception as e:
                logging.debug(f"Moonraker WS loop reconnecting: {e}")
            finally:
                self._ws_connected = False
                try:
                    ws.close()
                except Exception:
                    pass
            time.sleep(2.0)

    def _loop(self):
        while self._running:
            t0 = time.time()
            try:
                # Periodic verification of Moonraker /printer/info state
                now = time.time()
                info_interval = 1.0 if (self._klippy_state != "ready" or not self._klippy_connected) else 2.5
                if now - self._last_info_check >= info_interval:
                    self._last_info_check = now
                    try:
                        info = _moonraker.get_printer_info()
                        self._moonraker_online = info["moonraker_online"]
                        self._klippy_state = info["state"]
                        self._klippy_connected = info["klippy_connected"]
                        self._klippy_msg = info["state_message"]
                        if not self._moonraker_online or self._klippy_state != "ready":
                            self._publish_disconnected_or_error(
                                online=self._moonraker_online,
                                klippy_state=self._klippy_state,
                                klippy_connected=self._klippy_connected,
                                state_message=self._klippy_msg,
                            )
                    except Exception:
                        pass

                # If WebSocket is connected and has pushed messages recently (<1.5s),
                # continue processing the streaming status.
                # If WebSocket is disconnected or has gone silent for >1.5s (e.g. dropped subscriptions),
                # immediately fall back to HTTP polling so telemetry NEVER stalls.
                ws_healthy = self._ws_connected and (now - self._last_ws_msg_time < 1.5)
                if ws_healthy and self._klipper_data:
                    self._process_data(self._klipper_data)
                else:
                    self._tick_http()
            except Exception as e:
                logging.info(f"⚠️  TelemetryWorker: {e}")
            # Run the high-rate controller only while a print is active.  At
            # idle, Moonraker's WebSocket is already event-driven and a 4 Hz
            # pass is enough for the dashboard and heater monitoring.  When
            # Klipper is unavailable we intentionally back off further: a
            # failed MCU must not turn into 25 HTTP checks and full model
            # evaluations per second.
            tick_hz = self._target_tick_hz()
            interval = 1.0 / tick_hz
            time.sleep(max(0.0, interval - (time.time() - t0)))

    def _target_tick_hz(self) -> float:
        """Return the appropriate background processing rate for live state.

        This is deliberately separate from the WebSocket subscription.  A
        Moonraker status change is received immediately; this rate limits only
        duplicated model work, fallback HTTP polling and UI snapshot creation.
        """
        if not self._moonraker_online or not self._klippy_connected or self._klippy_state != "ready":
            return max(0.1, settings.TWIN_OFFLINE_TICK_HZ)
        if self._klipper_data.get("print_stats", {}).get("state") == "printing":
            return max(0.1, POLL_HZ)
        return max(0.1, settings.TWIN_IDLE_TICK_HZ)

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

    def _finish_job(self, snap, ext_, job_ended, job_switched):
        """print_history, timelapse, notifications and the QA report for the job that just ended."""
        ended_name = self._job_filename or snap.get("filename", "unknown file")
        # after a hand-over the live filament counter already belongs to the new job
        fil_now = self._last_fil_m if job_switched else ext_.get("filament_consumed_m", 0.0)

        duration_s = (time.time() - self._print_start_time) if self._print_start_time else 0.0
        fil_used_g = max(0.0, fil_now - self._print_start_fil_m) * 3.0   # approx 3 g per metre of 1.75 mm PLA
        power_used_wh = max(0.0, _energy_wh() - self._print_start_wh)
        # Active Spoolman calculation (optional, fallback to 0 cost if not available)
        cost = fil_used_g * get_spool_price_per_g()
        cost += (power_used_wh / 1000.0) * 0.15          # electricity at $0.15 / kWh

        # Log to print_history first: the timelapse link and the QA report need its id
        history_id = None
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT MAX(id) FROM config_history")
            conf_row = c.fetchone()
            config_id = conf_row[0] if conf_row and conf_row[0] else None

            c.execute('''
                INSERT INTO print_history
                (filename, status, print_time_seconds, filament_used_g, power_used_wh, cost_usd, config_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (ended_name or "unknown", job_ended, duration_s, fil_used_g, power_used_wh, cost, config_id))
            history_id = c.lastrowid

            # Update total lifetime stats in odometry
            c.execute("UPDATE odometry SET travel_meters = travel_meters + ? WHERE axis = 'E'",
                      (max(0.0, fil_now - self._print_start_fil_m),))

            # Update virtual spool usage
            c.execute("SELECT value FROM printer_config WHERE key = 'virtual_spool_used_g'")
            row = c.fetchone()
            used_g = float(row[0]) if row else 0.0
            used_g += fil_used_g
            c.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('virtual_spool_used_g', ?)", (str(used_g),))

            conn.commit()
            conn.close()
        except Exception as e:
            logging.info(f"⚠️  Error saving print history: {e}")

        # Captured now: the next queued job overwrites self._print_start_time before a stitch can finish.
        start_ts, end_ts = self._print_start_time, time.time()

        def _start_report():
            if job_ended == "complete" and history_id:
                try:
                    from services.qa_reporter import trigger_qa_report
                    trigger_qa_report(history_id, start_ts, end_ts, ended_name or "unknown")
                except Exception as re:
                    logging.warning(f"QA report trigger error: {re}")

        # With a timelapse the stitch thread runs the report once the video link is in print_history (or the
        # stitch failed); otherwise there is nothing to wait for and it starts right away.
        chained = timelapse_job.finish(job_ended, history_id=history_id, on_done=_start_report)

        try:
            from core.notifications import notify_print_completed, notify_print_halted
            if job_ended == "complete":
                excursions = None
                try:
                    from services.quality_metrics import count_excursions
                    excursions = count_excursions(start_ts, end_ts)    # None when it cannot be measured
                except Exception as qe:
                    logging.debug(f"Excursion count unavailable: {qe}")
                notify_print_completed(filename=ended_name, duration_s=duration_s, energy_wh=power_used_wh,
                                       cost_usd=cost, filament_g=fil_used_g, excursions=excursions)
            elif job_ended in ("error", "cancelled"):
                notify_print_halted(filename=ended_name, status=job_ended)
        except Exception as ne:
            logging.warning(f"Print completion notification error: {ne}")

        if not chained:
            _start_report()

    def _publish_disconnected_or_error(self, online: bool, klippy_state: str, klippy_connected: bool, state_message: str):
        """Immediately update state and push snapshot to WebSocket clients
        when Moonraker is unreachable or Klipper is shutdown/disconnected."""
        update = {
            "online": online,
            "klippy_state": klippy_state,
            "klippy_connected": klippy_connected,
            "state_message": state_message,
            "device_temperatures": getattr(self, "_device_temperatures", {}),
        }
        if klippy_state in ("shutdown", "error"):
            update["print_state"] = "error"
        elif not klippy_connected or not online or klippy_state == "disconnected":
            update["print_state"] = "disconnected"

        printer_state.update(update)
        snap = printer_state.snapshot()

        vib_dict, _ = vibration_monitor.update(
            dsp_bridge.latest, snap["print_state"], dsp_bridge.available,
            autoz_latest=dsp_bridge.latest_autoz,
        )

        latest_payload = {
            **snap,
            "online":           online,
            "klippy_state":     klippy_state,
            "klippy_connected": klippy_connected,
            "state_message":    state_message,
            "device_temperatures": getattr(self, "_device_temperatures", {}),
            "power":            pzem_monitor.read(),
            "disk":             disk_monitor.check(),
            "kinematics":       {},
            "thermals":         {},
            "extrusion":        {},
            "vibration":        vib_dict,
            "live_commands":    list(self.live_commands),
            "notifications":    pop_ui_notifications(),
            "quality": {
                "active":      quality_controller.active,
                "corrections": quality_controller.corrections[:10],
            },
        }
        with self._cond:
            self.latest = latest_payload
            self._cond.notify_all()

    def _tick_http(self):
        info = _moonraker.get_printer_info()
        self._moonraker_online = info["moonraker_online"]
        self._klippy_state = info["state"]
        self._klippy_connected = info["klippy_connected"]
        self._klippy_msg = info["state_message"]

        if not self._moonraker_online or self._klippy_state != "ready":
            self._publish_disconnected_or_error(
                online=self._moonraker_online,
                klippy_state=self._klippy_state,
                klippy_connected=self._klippy_connected,
                state_message=self._klippy_msg,
            )
            return

        temp_query = "&".join(urllib.parse.quote(s) for s in self._discover_temp_sensors())
        url = f"{settings.moonraker_url}/printer/objects/query?{KLIPPER_OBJECTS}"
        if temp_query:
            url += f"&{temp_query}"
        try:
            res = self._session.get(url, timeout=1.0)
            if res.ok:
                data = res.json().get("result", {}).get("status", {})
                for k, v in data.items():
                    if k not in self._klipper_data:
                        self._klipper_data[k] = {}
                    if isinstance(v, dict):
                        self._klipper_data[k].update(v)
                    else:
                        self._klipper_data[k] = v
                self._process_data(self._klipper_data)
                return
        except Exception:
            pass

        self._publish_disconnected_or_error(
            online=self._moonraker_online,
            klippy_state=self._klippy_state,
            klippy_connected=self._klippy_connected,
            state_message=self._klippy_msg,
        )

    def _tick(self):
        self._tick_http()

    def _process_data(self, data: dict):
        if not data:
            return

        with self._process_lock:
            th  = data.get("toolhead",       {})
            mr  = data.get("motion_report",  {})
            ext = data.get("extruder",       {})
            bed = data.get("heater_bed",     {})
            fan = data.get("fan",            {})
            ps  = data.get("print_stats",    {})
            ds  = data.get("display_status", {})
            gm  = data.get("gcode_move",     {})

            homed_axes = th.get("homed_axes", "")

            ho  = gm.get("homing_origin",    [0.0, 0.0, 0.0, 0.0])
            ho_x = ho[0] if len(ho) > 0 else 0.0
            ho_y = ho[1] if len(ho) > 1 else 0.0
            ho_z = ho[2] if len(ho) > 2 else 0.0
            ho_e = ho[3] if len(ho) > 3 else 0.0

            cp = th.get("position",      [0, 0, 0, 0])
            lp = mr.get("live_position", [0, 0, 0, 0])
            gp = gm.get("gcode_position")

            # Physical limits for clamping (from bed_safety / toolhead limits)
            axis_min = th.get("axis_minimum", [bed_safety.min_x, bed_safety.min_y, bed_safety.min_z, 0.0])
            axis_max = th.get("axis_maximum", [bed_safety.max_x, bed_safety.max_y, bed_safety.max_z, 0.0])
            min_x = float(axis_min[0]) if len(axis_min) > 0 else bed_safety.min_x
            min_y = float(axis_min[1]) if len(axis_min) > 1 else bed_safety.min_y
            min_z = float(axis_min[2]) if len(axis_min) > 2 else bed_safety.min_z
            max_x = float(axis_max[0]) if len(axis_max) > 0 else bed_safety.max_x
            max_y = float(axis_max[1]) if len(axis_max) > 1 else bed_safety.max_y
            max_z = float(axis_max[2]) if len(axis_max) > 2 else bed_safety.max_z

            # Commanded position in user/G-code coordinates
            if gp and len(gp) >= 3:
                cmd_x, cmd_y, cmd_z = float(gp[0]), float(gp[1]), float(gp[2])
                cmd_e = float(gp[3]) if len(gp) > 3 else 0.0
            else:
                cmd_x = float(cp[0]) - ho_x
                cmd_y = float(cp[1]) - ho_y
                cmd_z = float(cp[2]) - ho_z
                cmd_e = (float(cp[3]) if len(cp) > 3 else 0.0) - ho_e

            # Live kinematic position: guard against trapq glitches and translate to user coordinates
            raw_lx = float(lp[0]) if (lp[0] != 0 or cp[0] == 0) else float(cp[0])
            raw_ly = float(lp[1]) if (lp[1] != 0 or cp[1] == 0) else float(cp[1])
            raw_lz = float(lp[2]) if (lp[2] != 0 or cp[2] == 0) else float(cp[2])
            raw_le = float(lp[3]) if len(lp) > 3 else 0.0

            live_x = raw_lx - ho_x
            live_y = raw_ly - ho_y
            live_z = raw_lz - ho_z
            live_e = raw_le - ho_e

            # Homing artifact rejection:
            # In Klipper, during homing moves (G28), axes not yet homed have virtual search
            # targets (e.g. 1.5 * axis_length, such as 477.5 mm), and homed_axes does not contain the axis.
            # We reject unphysical search positions and maintain the last valid position until confirmed homed.
            if min_x <= live_x <= max_x:
                self._last_valid_x = live_x
            else:
                live_x = self._last_valid_x
                cmd_x = self._last_valid_x

            if min_y <= live_y <= max_y:
                self._last_valid_y = live_y
            else:
                live_y = self._last_valid_y
                cmd_y = self._last_valid_y

            if min_z <= live_z <= max_z:
                self._last_valid_z = live_z
            else:
                live_z = self._last_valid_z
                cmd_z = self._last_valid_z

            # Defense-in-depth clamping to physical bed bounds
            cmd_x = max(min_x, min(max_x, cmd_x))
            cmd_y = max(min_y, min(max_y, cmd_y))
            cmd_z = max(min_z, min(max_z, cmd_z))
            live_x = max(min_x, min(max_x, live_x))
            live_y = max(min_y, min(max_y, live_y))
            live_z = max(min_z, min(max_z, live_z))

            progress       = ds.get("progress",       0.0)
            print_duration = ps.get("print_duration", 0.0)
            vsd            = data.get("virtual_sdcard", {})
            vsd_pos        = vsd.get("file_position")
            file_position  = int(vsd_pos) if vsd_pos is not None else int(ps.get("file_position", 0))
            vsd_prog       = vsd.get("progress")
            if vsd_prog is not None and float(vsd_prog) > 0:
                progress = float(vsd_prog)
            vsd_path       = vsd.get("file_path", "")
            effective_filename = ps.get("filename", "") or (os.path.basename(vsd_path) if vsd_path else "")

            time_remaining = 0
            if progress > 0.01:
                time_remaining = int((print_duration / progress) * (1.0 - progress))

            speed_factor = round(gm.get("speed_factor",   1.0) * 100, 1)
            flow_factor  = round(gm.get("extrude_factor", 1.0) * 100, 1)

            klipper_print_state = ps.get("state", "standby")
            if self._klippy_state in ("shutdown", "error"):
                effective_print_state = "error"
            elif not self._klippy_connected or not self._moonraker_online or self._klippy_state == "disconnected":
                effective_print_state = "disconnected"
            else:
                effective_print_state = klipper_print_state

            # --- Extract device temperatures (e.g. temperature_sensor EBB36, temperature_probe btt_eddy) ---
            dev_temps = {}
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                if any(k.startswith(p) for p in (
                    "temperature_sensor ",
                    "temperature_probe ",
                    "temperature_fan ",
                    "bme280 ",
                    "htu21d ",
                    "lm75 ",
                    "heater_generic ",
                )):
                    parts = k.split(" ", 1)
                    sensor_type = parts[0]
                    sensor_name = parts[1] if len(parts) > 1 else k
                    temp = v.get("temperature")
                    if temp is not None:
                        entry = {
                            "name": sensor_name,
                            "full_name": k,
                            "type": sensor_type,
                            "temperature": round(float(temp), 1),
                        }
                        if "target" in v:
                            entry["target"] = round(float(v["target"]), 1)
                        if "speed" in v:
                            entry["speed"] = round(float(v["speed"]), 2)
                        dev_temps[sensor_name] = entry

            self._device_temperatures = dev_temps

            update = {
                "online":          self._moonraker_online,
                "klippy_state":    self._klippy_state,
                "klippy_connected": self._klippy_connected,
                "state_message":   self._klippy_msg,
                "device_temperatures": dev_temps,
                "cmd_x":           round(cmd_x, 3),
                "cmd_y":           round(cmd_y, 3),
                "cmd_z":           round(cmd_z, 3),
                "cmd_e":           round(cmd_e, 3),
                "live_x":          round(live_x, 3),
                "live_y":          round(live_y, 3),
                "live_z":          round(live_z, 3),
                "live_e":          round(live_e, 3),
                "homed_axes":      homed_axes,
                "is_homed":        ("x" in homed_axes and "y" in homed_axes and "z" in homed_axes),
                "velocity":        round(mr.get("live_velocity", 0.0), 3),
                "ext_temp":        ext.get("temperature", 0),
                "ext_target":      ext.get("target", 0),
                "ext_pwm":         round(ext.get("power", 0), 4),
                "bed_temp":        bed.get("temperature", 0),
                "bed_target":      bed.get("target", 0),
                "print_state":     effective_print_state,
                "filename":        effective_filename,
                "file_position":   file_position,
                "progress":        round(progress, 4),
                "print_duration":  int(print_duration),
                "time_remaining":  time_remaining,
                "speed_factor":    speed_factor,
                "flow_factor":     flow_factor,
                "fan_speed":       round(fan.get("speed", 0.0) * 100, 1),
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
            # not part of the state snapshot, but job-boundary detection (core/job_tracker) needs it:
            # Klipper's print_duration restarts at 0 for every job, including the same file queued twice
            snap["print_duration"] = update.get("print_duration", 0)
            in_screw_zone, zone_idx = bed_safety.is_in_exclusion_zone(
                snap.get("live_x", 0.0), snap.get("live_y", 0.0), snap.get("live_z", 0.0)
            )
            snap["bed_collision_hazard"] = in_screw_zone
            snap["bed_collision_zone"] = zone_idx

            # --- Read external edge sensors (RP2040 filament sensor & ESP8266 bed hub) ---
            fil_data = filament_sensor.read()
            bed_data = bed_sensor.read()

            if bed_data.get("connected") and bed_data.get("chamber"):
                ch = bed_data["chamber"]
                if ch.get("temp_c") is not None:
                    dev_temps["Chamber"] = {
                        "temperature": round(float(ch["temp_c"]), 1),
                        "humidity": round(float(ch.get("humidity_pct", 0) or 0), 1),
                        "pressure": round(float(ch.get("pressure_hpa", 0) or 0), 1)
                    }

            kin  = kinematic_model.update(snap)
            thm  = thermal_model.update(snap)
            ext_ = extrusion_model.update(
                snap,
                measured_dia=fil_data.get("diameter_mm") if fil_data.get("connected") else None
            )
            ext_["filament_sensor"] = fil_data

            # Moonraker's job queue can load the next job within milliseconds of the previous one completing,
            # faster than this poll: the "complete" state is then never seen and every plugin would treat the two
            # jobs as one print. Synthesize the missing end of the old job first (plugins see a non-printing tick,
            # the controller drops its commanded values), then the normal tick below is the start of the new one.
            job_ended, job_started, job_switched = self._edges.step(snap)
            if job_switched:
                logging.info(f"🔁 TelemetryWorker: new job {snap.get('filename')!r} followed {self._job_filename!r} directly")
                gap = dict(snap, print_state="complete")
                command_pipeline.tick(gap, "live")
                quality_controller.update(gap, kin, thm, ext_)
                # book the old job (history, virtual spool usage) before the new job's plugins look at the spool
                self._finish_job(snap, ext_, job_ended, job_switched)

            command_pipeline.tick(snap, "live")

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

            cur_state = snap["print_state"]
            # End of a job first, then the start of the next one: with a queue both can happen on one tick.
            if job_ended and not job_switched:
                self._finish_job(snap, ext_, job_ended, job_switched)

            if job_started:
                if get_timelapse_cfg().get("enabled"):
                    timelapse_job.start(snap.get("filename", ""))
                self._job_filename = snap.get("filename", "")
                self._print_start_time = time.time()
                self._print_start_fil_m = ext_.get("filament_consumed_m", 0.0)
                self._print_start_wh = _energy_wh()
                try:
                    from core.notifications import notify_print_started
                    notify_print_started(
                        filename=snap.get("filename", "unknown file"),
                        bed_temp=snap.get("bed_target"),
                        ext_temp=snap.get("ext_target"),
                    )
                except Exception as ne:
                    logging.debug(f"Print start notification skipped: {ne}")
            self._last_fil_m = ext_.get("filament_consumed_m", 0.0)

            self._prev_print_state = cur_state

            # Quality controller — send corrective commands and log them
            if snap["print_state"] == "printing":
                if get_timelapse_cfg().get("enabled"):
                    timelapse_job.maybe_capture(snap["cmd_z"])
                # Every command goes through the plugin pipeline (shadow, arbiter, watchdog, audit);
                # with no plugins it is update + send, as before.
                for r in command_pipeline.run_quality_cycle(
                        quality_controller, snap, kin, thm, ext_, _moonraker.send_gcode, "live",
                        autoz=dsp_bridge.latest_autoz):
                    tag = "[QC]" if r["ok"] else "[QC FAIL]"
                    self.live_commands.append({"text": f"{tag} {r['command']}", "ts": r["ts"]})

            if snap["print_state"] == "printing":
                log_snapshot(snap, kin, thm, ext_)

            vib_dict, _vib_alerts = vibration_monitor.update(
                dsp_bridge.latest, snap["print_state"], dsp_bridge.available,
                autoz_latest=dsp_bridge.latest_autoz,
            )

            self._apply_led_state(
                snap["print_state"],
                snap.get("ext_temp", 0), snap.get("ext_target", 0),
                snap.get("bed_temp", 0), snap.get("bed_target", 0),
                snap.get("progress", 0.0),
            )

            latest_payload = {
                **snap,
                "power":           pzem_monitor.read(),
                "disk":            disk_monitor.check(),
                "device_temperatures": dev_temps,
                "chamber":         bed_data.get("chamber", {}),
                "bed_accel":       bed_data.get("bed_accel", {}),
                "filament_sensor": fil_data,
                "kinematics":      kin,
                "thermals":        thm,
                "extrusion":       ext_,
                "vibration":       vib_dict,
                "exclude_object":  data.get("exclude_object", {}),
                "live_commands": list(self.live_commands),
                "notifications": pop_ui_notifications(),
                "quality": {
                    "active":      quality_controller.active,
                    "corrections": quality_controller.corrections[:10],
                },
            }
            with self._cond:
                self.latest = latest_payload
                self._cond.notify_all()

    @property
    def power(self) -> dict:
        """Returns the latest PZEM-004T power monitor telemetry readings."""
        return pzem_monitor.read()


telemetry_worker = TelemetryWorker()
