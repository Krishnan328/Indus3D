import os

"""
workers/simulator.py
----------------------
Key fixes in this version:
  1. NO heating delay — temps set instantly, printing starts in ~5 seconds
  2. file_position starts at waypoints[0]["byte"] on tick 0 of printing
     (was stuck at 0 due to wp_idx > 0 guard, now fixed)
  3. Advances WAYPOINTS_PER_TICK waypoints each tick so benchy
     completes visually in ~60-90 seconds not 10 minutes
  4. M221/M220/SET_INPUT_SHAPER from quality controller appended
     to gcode_feed so they appear in the terminal
  5. Sim uses indus_sim_ender3.cfg profile (Ender 3 framework)
"""

import logging
import math
import time
import random
import sys
import threading
from collections import deque

from digital_twin.state import printer_state
from digital_twin.kinematic_model import kinematic_model
from digital_twin.thermal_model import thermal_model
from digital_twin.extrusion_model import extrusion_model
from digital_twin.snapshot_logger import log_snapshot
from digital_twin.quality_controller import quality_controller
from digital_twin.vibration_monitor import vibration_monitor
from config.loader import get_profile
from config.settings import settings
from workers.gcode_shapes import get_shape_gcode
from workers.dsp_bridge import dsp_bridge
from digital_twin.bed_safety import bed_safety

POLL_HZ          = settings.TWIN_TICK_HZ
_DT              = 1.0 / POLL_HZ
WAYPOINTS_PER_TICK = 4     # 12k full-detail waypoints complete in ~60–90 s

# CLI flags
_shape  = "benchy"
_layers = 240      # benchy: full 0.2 mm / ~48 mm preview (not sparse 0.8 mm slices).
                   # cube: still a literal layer count. Override with --layers.
for i, arg in enumerate(sys.argv):
    if arg == "--shape"  and i + 1 < len(sys.argv): _shape  = sys.argv[i + 1]
    if arg == "--layers" and i + 1 < len(sys.argv): _layers = int(sys.argv[i + 1])

MAINTENANCE_RULES = [
    {"metric": "odometry_x_m",    "threshold": 500,  "msg": "Lubricate X-axis linear rail and lead screw"},
    {"metric": "odometry_y_m",    "threshold": 500,  "msg": "Lubricate Y-axis rods and clean belt"},
    {"metric": "odometry_z_m",    "threshold": 200,  "msg": "Lubricate Z-axis lead screw with PTFE grease"},
    {"metric": "ext_heat_cycles", "threshold": 300,  "msg": "Inspect extruder heater cartridge and thermistor"},
    {"metric": "bed_heat_cycles", "threshold": 300,  "msg": "Check heated bed wiring and thermistor connection"},
    {"metric": "stress_x",        "threshold": 0.3,  "msg": "Check X-axis belt tension"},
    {"metric": "stress_y",        "threshold": 0.3,  "msg": "Check Y-axis belt tension"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Thermal simulator — only used during printing for realistic sensor data
# ─────────────────────────────────────────────────────────────────────────────
class _HeaterSim:
    def __init__(self, ambient=24.0):
        self.temp    = ambient
        self.target  = 0.0
        self.pwm     = 0.0
        self._ambient= ambient
        self._fault  = False
        self._drain  = 0.0

    def set_target(self, t, instant=False):
        self.target = t
        if instant:
            self.temp = t   # skip heating delay

    def inject_runaway(self, drain=3.0): self._fault = True;  self._drain = drain
    def clear_fault(self):               self._fault = False; self._drain = 0.0

    def step(self, dt):
        # Light noise around target to show realistic PID behavior
        noise = random.gauss(0, 0.05)
        if self.target > 0:
            err       = self.target - self.temp
            self.pwm  = max(0., min(1., err / 10.))
            delta     = self.pwm * 0.8 * dt - (self.temp - self._ambient) * 0.003 * dt
            if self._fault: delta -= self._drain * dt
            self.temp = round(self.temp + delta + noise, 3)
        else:
            self.temp = round(max(self._ambient, self.temp - 0.5 * dt + noise), 3)
            self.pwm  = 0.


# ─────────────────────────────────────────────────────────────────────────────
# Axis simulator — lightweight, fast
# ─────────────────────────────────────────────────────────────────────────────
class _AxisSim:
    def __init__(self, max_vel=200., max_accel=1500.):
        self.pos        = 0.
        self.velocity   = 0.
        self._target    = 0.
        self._v_max     = max_vel
        self._accel     = max_accel
        self._lag_spike = 0.

    def move_to(self, target): self._target = target
    def inject_lag_spike(self, mm): self._lag_spike = mm

    def step(self, dt):
        dist = self._target - self.pos
        if abs(dist) < 0.01:
            self.velocity = 0.; self.pos = self._target
            lag = self._lag_spike; self._lag_spike = max(0., self._lag_spike - 0.5*dt)
            return self.pos, self.pos - lag, 0.

        direction      = math.copysign(1, dist)
        self.velocity += direction * self._accel * dt
        self.velocity  = max(-self._v_max, min(self._v_max, self.velocity))

        stop_dist = self.velocity**2 / (2 * self._accel)
        if abs(dist) < stop_dist:
            self.velocity -= direction * self._accel * dt

        step = self.velocity * dt
        if abs(step) > abs(dist): step = dist

        self.pos = round(self.pos + step, 4)
        lag      = abs(self.velocity) * 0.018 + self._lag_spike
        self._lag_spike = max(0., self._lag_spike - 0.5 * dt)
        live_pos = round(self.pos - math.copysign(lag, self.velocity) if self.velocity else self.pos, 4)
        return self.pos, live_pos, round(abs(self.velocity), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Main simulator
# ─────────────────────────────────────────────────────────────────────────────
class SimulatedTelemetryWorker:

    def __init__(self):
        self._last_segment_distance = 0.0

        self.latest: dict          = {
            "online": True,
            "sim": True,
            "print_state": "standby",
            "cmd_x": 110.0, "cmd_y": 110.0, "cmd_z": 5.0, "cmd_e": 0.0,
            "live_x": 110.0, "live_y": 110.0, "live_z": 5.0,
            "ext_temp": 24.0, "ext_target": 0.0, "ext_pwm": 0.0,
            "bed_temp": 24.0, "bed_target": 0.0,
            "progress": 0.0,
            "quality": {"active": quality_controller.active, "corrections": []},
            "kinematics": {},
            "thermals": {},
            "extrusion": {},
            "vibration": {},
            "power": {"voltage": 0., "current": 0., "power": 0.},
            "environment": {"temperature": 24., "humidity": 45.},
            "gcode_feed": [],
            "maintenance_hints": [],
        }
        self.power                 = {"voltage": 0., "current": 0., "power": 0.}
        self.environment           = {"temperature": 24., "humidity": 45.}
        self.gcode_feed: deque     = deque(maxlen=10)
        self.print_history: list   = []
        self.maintenance_hints: list = []
        self.excluded_objects: set = set()
        self.maintenance_status: list = []

        self.shape      = _shape
        self.gcode_str  = ""
        self._waypoints: list = []
        self._wp_idx    = 0
        self._wp_time_debt = 0.0  # seconds of real-print-time still owed this tick

        self._running      = True
        self._t            = 0.
        self._print_count  = 0
        self._thread       = threading.Thread(target=self._loop, daemon=True)

        profile  = get_profile()
        m        = profile.get("motion", {})
        b        = profile.get("bed", {})
        h        = profile.get("hotend", {})
        bh       = profile.get("bed_heater", {})

        self._bed_cx = b.get("size_x_mm", 235) / 2
        self._bed_cy = b.get("size_y_mm", 235) / 2

        self._ext_target = h.get("max_temp_c",  260) * 0.83
        self._bed_target = bh.get("max_temp_c", 110) * 0.55

        self._ext = _HeaterSim()
        self._bed = _HeaterSim()

        self._ax = _AxisSim(m.get("max_velocity_mm_s", 200), m.get("max_accel_mm_s2", 1500))
        self._ay = _AxisSim(m.get("max_velocity_mm_s", 200), m.get("max_accel_mm_s2", 1500))
        self._az = _AxisSim(10., 100.)

        # Start at bed centre so nozzle is visible immediately
        for ax in (self._ax, self._ay):
            ax.pos = self._bed_cx if ax is self._ax else self._bed_cy
            ax._target = ax.pos
        self._az.pos = 5.; self._az._target = 5.

        self._ae              = 0.
        self._ae_multiplier   = 1.
        # The simulator teleports through several waypoints each tick.  Keep a
        # physical velocity derived from those moves rather than reporting the
        # axis simulator's post-teleport zero.  The extrusion model depends on
        # it for a meaningful expected flow calculation.
        self._motion_velocity = 0.
        # _start_print changes the state before the first print-tick advances
        # a waypoint. Keep this defined for that transition frame as well.
        self._tick_extruding_distance = 0.
        nozzle = h.get("nozzle_diameter_mm", 0.4)
        filament = h.get("filament_diameter_mm", 1.75)
        line_w = profile.get("print", {}).get("line_width_mm", nozzle)
        layer_h = profile.get("print", {}).get("layer_height_mm", 0.2)
        bead_area = max(0.001, (line_w - layer_h) * layer_h + math.pi * (layer_h / 2) ** 2)
        self._e_per_mm = bead_area / (math.pi * (filament / 2) ** 2)
        self._state           = "idle"
        self._pending_gcodes  = []

        # TEST macro
        self._test_wp      = []
        self._test_wp_idx  = 0

        # Fault schedule
        self._faults_fired    = set()
        self._fault_schedule  = {
            60:  ("thermal_runaway", 3., 10.),
            120: ("under_extrusion", 0.4, 8.),
            180: ("lag_spike",       3.5, 6.),
            240: ("over_extrusion",  1.6, 8.),
        }
        self._active_faults = {}

        # Pre-build G-code immediately — endpoint will serve it on first request
        logging.info(f"🖨️  Pre-building sim G-code: {self.shape}, {_layers} layers…")
        import os
        # Robust path resolution relative to backend/ directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Check both backend/ and root folder just in case
        gcode_path = os.path.join(base_dir, "3dbenchy(3)_1h58m.gcode")
        if not os.path.exists(gcode_path):
            gcode_path = os.path.join(os.path.dirname(base_dir), "3dbenchy(3)_1h58m.gcode")

        if self.shape == "benchy" and os.path.exists(gcode_path):
            with open(gcode_path, "r") as f:
                self.gcode_str = f.read()
            self._waypoints = self._parse_real_gcode(self.gcode_str)
        else:
            self.gcode_str, self._waypoints = get_shape_gcode(self.shape, _layers)

        logging.info(f"✅ Sim G-code ready: {len(self._waypoints)} waypoints, "
              f"{len(self.gcode_str)} bytes")

        self.gcode_feed.append({"byte": 0, "text": f"; Indus3D Sim — {self.shape.upper()}"})
        self.gcode_feed.append({"byte": 0, "text": f"; {len(self._waypoints)} waypoints ready"})
        self.gcode_feed.append({"byte": 0, "text": "G28 ; Home"})
        self._print_start_time = time.time()
        self.gcode_feed.append({
            "byte": 0,
            "text": f"G1 X{self._bed_cx:.1f} Y{self._bed_cy:.1f} F6000 ; Move to centre"
        })

    def start(self):
        self._thread.start()
        logging.info("📡 SimulatedTelemetryWorker started")
        logging.info(f"   Will start printing in ~5 seconds")

    def stop(self): self._running = False

    def inject_gcode(self, gcode: str):
        """Called by control route when user sends from terminal."""
        self._pending_gcodes.append(gcode.strip().upper())

    def home(self):
        """Mainsail-style home action for the offline dashboard."""
        self._ax.move_to(self._bed_cx)
        self._ay.move_to(self._bed_cy)
        self._az.move_to(5.0)
        self.gcode_feed.append({"byte": 0, "text": "[INDUS] G28 ; Sim homed"})

    def jog(self, x=0.0, y=0.0, z=0.0, e=0.0):
        """Bounded relative motion with bed screw and exclusion zone collision checking."""
        cur_x, cur_y, cur_z = self._ax.pos, self._ay.pos, self._az.pos
        target_x = max(bed_safety.min_x, min(bed_safety.max_x, cur_x + x))
        target_y = max(bed_safety.min_y, min(bed_safety.max_y, cur_y + y))
        target_z = max(bed_safety.min_z, min(bed_safety.max_z, cur_z + z))

        # Check exclusion zone collision (bed screws, clamps, clips)
        is_safe, reason = bed_safety.validate_move(cur_x, cur_y, cur_z, target_x, target_y, target_z)
        if not is_safe:
            self.gcode_feed.append({"byte": 0, "text": f"[SAFETY BLOCKED] {reason}"})
            logging.warning(f"🛡️ Jog blocked: {reason}")
            return False

        self._ax.move_to(target_x)
        self._ay.move_to(target_y)
        self._az.move_to(target_z)
        if e != 0.0:
            self._ae += e
        terms = " ".join(f"{axis}{value:+.1f}" for axis, value in (("X", x), ("Y", y), ("Z", z), ("E", e)) if value)
        self.gcode_feed.append({"byte": 0, "text": f"[INDUS] Jog {terms}"})
        return True

    def inject_quality_command(self, cmd: str):
        """Called by quality_controller to show M221/M220 in terminal."""
        self.gcode_feed.append({"byte": 0, "text": f"[QC] {cmd}"})

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _loop(self):
        while self._running:
            t0 = time.time()
            try:    self._tick()
            except Exception as e: logging.info(f"⚠️ Sim: {e}")
            time.sleep(max(0., _DT - (time.time() - t0)))

    def _tick(self):
        self._t += _DT

        # Handle terminal commands
        if self._pending_gcodes:
            self._handle_cmd(self._pending_gcodes.pop(0))

        # ── State machine ──────────────────────────────────────────────────────
        if self._state == "idle" and self._t > 5.:
            self._start_print()

        elif self._state == "printing":
            self._tick_extruding_distance = 0.0
            # Real-time simulation: advance waypoints using their actual durations
            # (distance / feedrate). Each tick has _DT seconds of real print time
            # to spend. This means a 1h58m G-code file runs in ~1h58m.
            time_budget = _DT + self._wp_time_debt
            while time_budget > 0:
                self._advance_waypoint()
                if self._wp_idx >= len(self._waypoints):
                    self._finish_print()
                    break
                wp = self._waypoints[self._wp_idx]
                dur = wp.get("duration", 0.0)
                if dur <= 0:
                    # Instant move (pure Z-hop or zero-distance); consume no time
                    time_budget -= 0.0
                    break  # avoid infinite loop on zero-duration waypoints
                time_budget -= dur
            # Carry over any unused budget (negative = overspent, positive = underspent)
            self._wp_time_debt = time_budget if time_budget > 0 else 0.0
            # The extrusion model observes E once per tick, so its comparison
            # velocity must represent the same set of moves—not just the last
            # contour segment processed above.
            # Simulation runs faster than the emitted G-code's physical feed
            # rate.  Use its actual visual-time path speed here so commanded
            # E and expected bead flow remain on the same time basis.
            self._motion_velocity = self._tick_extruding_distance / _DT

            # ── Synthetic ADXL injection ──────────────────────────────────
            # Feed 32 samples per tick (~320 Hz effective) into the DSP
            # bridge as binary IDX packets. Base Gaussian noise + 45 Hz
            # resonance when moving fast.
            if dsp_bridge.available:
                import random as _rand
                vel_proxy = getattr(self, "_motion_velocity", 0.0)
                res_amp   = min(0.5, vel_proxy / 200.0)   # scale with speed, cap 0.5g
                t0 = self._t
                for s in range(32):
                    st = t0 + s * (_DT / 32)
                    noise_x = _rand.gauss(0, 0.03)
                    noise_y = _rand.gauss(0, 0.03)
                    noise_z = _rand.gauss(0, 0.02)
                    # Inject printer resonance (X/Y in-plane ~45 Hz)
                    res = res_amp * math.sin(2 * math.pi * 45.0 * st)
                    dsp_bridge.send_adxl_binary(noise_x + res, noise_y + res, noise_z, st)
                # Push velocity metadata so the Rust notch filter can mask motor artefacts
                dsp_bridge.send_velocity_meta(self._ax.velocity, self._ay.velocity)


        elif self._state == "test":
            self._advance_test()

        elif self._state == "cooling":
            if self._ext.temp < 35 and self._bed.temp < 35:
                self._state = "idle"; self._t = 0.
                self._faults_fired.clear()

        # ── Physics ────────────────────────────────────────────────────────────
        self._ext.step(_DT); self._bed.step(_DT)
        cmd_x, live_x, vx = self._ax.step(_DT)
        cmd_y, live_y, vy = self._ay.step(_DT)
        cmd_z, live_z, vz = self._az.step(_DT)
        axis_velocity = math.sqrt(vx**2 + vy**2 + vz**2)
        velocity = round(max(axis_velocity, self._motion_velocity), 3)

        self._process_faults()

        # ── Power model ────────────────────────────────────────────────────────
        total_w = round(15. + self._ext.pwm * 40. + self._bed.pwm * 60.
                        + velocity * 0.05 + random.gauss(0, .3), 2)
        voltage = round(random.gauss(24., .05), 2)
        self.power = {"voltage": voltage,
                      "current": round(total_w / max(voltage, 1), 3),
                      "power":   total_w}

        # ── Chamber environment ────────────────────────────────────────────────
        if self._state == "printing":
            self.environment["temperature"] = round(
                min(35., self.environment["temperature"] + 0.003 * _DT), 2)
        else:
            self.environment["temperature"] = round(
                max(24., self.environment["temperature"] - 0.01 * _DT), 2)
        self.environment["humidity"] = round(
            max(30, min(70, self.environment["humidity"] + random.gauss(0, .03))), 1)

        # ── File position — ALWAYS from current waypoint byte, never 0 ─────────
        current_byte = 0
        if self._waypoints:
            idx         = min(self._wp_idx, len(self._waypoints) - 1)
            current_byte = self._waypoints[idx]["byte"]

        # Progress
        progress  = self._wp_idx / max(len(self._waypoints), 1) \
                    if self._state == "printing" else 0.
        time_rem  = int((self._t / max(progress, 0.001)) * (1. - progress)) \
                    if progress > 0.01 else 0

        is_active  = self._state in ("printing", "test")

        # ── Area 4: Physical-to-Virtual Coordinate Linear Mapping ───────────
        # Based on research paper: converts raw mechanical position to virtual coordinate
        virtual_x = round(-0.8935 * live_x + 295.0, 3)
        virtual_y = round( 1.0113 * live_y +   3.587, 3)
        virtual_z = round(-0.8544 * live_z + 299.85, 3)

        in_screw_zone, zone_idx = bed_safety.is_in_exclusion_zone(live_x, live_y, live_z)

        snap = {
            "online":        True,
            "sim":           True,
            "cmd_x":         cmd_x,  "cmd_y":   cmd_y,   "cmd_z":  cmd_z,
            "cmd_e":         round(self._ae * self._ae_multiplier, 4),
            "live_x":        live_x, "live_y":  live_y,  "live_z": live_z,
            "virtual_x":     virtual_x, "virtual_y": virtual_y, "virtual_z": virtual_z,
            "bed_collision_hazard": in_screw_zone,
            "bed_collision_zone": zone_idx,
            "velocity":      velocity,
            "ext_temp":      self._ext.temp,   "ext_target": self._ext.target,
            "ext_pwm":       self._ext.pwm,
            "bed_temp":      self._bed.temp,   "bed_target": self._bed.target,
            "print_state":   "printing" if is_active else "standby",
            "filename":      f"sim_{self.shape}.gcode",
            "file_position": current_byte,
            "progress":      round(progress, 4),
            "segment_distance": self._last_segment_distance,
            "print_duration": int(self._t),
            "time_remaining": time_rem,
            "speed_factor":  100,
            "flow_factor":   100,
        }

        printer_state.update(snap)
        kin  = kinematic_model.update(snap)
        thm  = thermal_model.update(snap)
        ext_ = extrusion_model.update(snap)

        # The simulation deliberately time-compresses a full G-code file. The
        # wall-clock delta used by the general extrusion model is therefore
        # susceptible to scheduler jitter, which used to fabricate M221
        # corrections on a healthy simulated print.  In sim mode the known
        # source of flow deviation is _ae_multiplier, so expose that ground
        # truth while retaining the model's live-mode calculations unchanged.
        sim_extruding = self._tick_extruding_distance > 0 if self._state == "printing" else False
        sim_ratio = self._ae_multiplier if sim_extruding else 1.0
        ext_["flow_ratio"] = round(sim_ratio, 3)
        ext_["is_extruding"] = sim_extruding
        ext_["under_extrusion_flag"] = sim_extruding and sim_ratio < 0.80
        ext_["over_extrusion_flag"] = sim_extruding and sim_ratio > 1.25

        # Quality controller — log commands to terminal in sim
        if is_active:
            cmds = quality_controller.update(snap, kin, thm, ext_)
            for cmd in cmds:
                self.inject_quality_command(cmd)   # show in terminal

        if snap["print_state"] == "printing":
            log_snapshot(snap, kin, thm, ext_)

        self._update_maintenance(kin, thm)

        # Vibration monitor — reads latest DSP result and raises alerts
        vib_dict, _vib_alerts = vibration_monitor.update(
            dsp_bridge.latest, snap["print_state"]
        )

        self.latest = {
            **snap,
            "kinematics":        kin,
            "thermals":          thm,
            "extrusion":         ext_,
            "vibration":         vib_dict,
            "exclude_object": self._get_exclude_payload(),
            "power":             self.power,
            "environment":       self.environment,
            "gcode_feed":        list(self.gcode_feed),
            "maintenance_hints": self.maintenance_hints,
            "quality": {
                "active":      quality_controller.active,
                "corrections": quality_controller.corrections[:10],
            },
        }

    # ── Print lifecycle ───────────────────────────────────────────────────────
    def _start_print(self):
        self._print_count += 1
        self._state  = "printing"
        self._wp_idx = 0
        self._wp_time_debt = 0.0
        self._ae     = 0.
        vibration_monitor.reset_baseline()

        # Set temps INSTANTLY — no heating delay in sim
        self._ext.set_target(self._ext_target, instant=True)
        self._bed.set_target(self._bed_target, instant=True)

        # Move to first waypoint immediately
        if self._waypoints:
            wp = self._waypoints[0]
            self._ax.move_to(wp["x"])
            self._ay.move_to(wp["y"])
            self._az.move_to(wp["z"])

        self.gcode_feed.append({"byte": 0, "text": f"; === Print #{self._print_count} — {self.shape.upper()} ==="})
        self.gcode_feed.append({"byte": 0, "text": f"M104 S{int(self._ext_target)} ; Extruder {int(self._ext_target)}°C (instant)"})
        self.gcode_feed.append({"byte": 0, "text": f"M140 S{int(self._bed_target)} ; Bed {int(self._bed_target)}°C (instant)"})
        self.gcode_feed.append({"byte": 0, "text": "G28 ; Home"})
        self._print_start_time = time.time()
        logging.info(f"🟢 Sim: print #{self._print_count} started ({self.shape}, "
              f"{len(self._waypoints)} waypoints, {WAYPOINTS_PER_TICK} WP/tick)")

    def _get_exclude_payload(self):
        if hasattr(self, "_cached_exclude_payload"):
            return {"objects": self._cached_exclude_payload, "excluded_objects": list(self.excluded_objects)}

        objects = []
        import re, json
        for line in self.gcode_str.split("\n"):
            if line.startswith("EXCLUDE_OBJECT_DEFINE"):
                name = re.search(r"NAME=([^ ]+)", line)
                poly = re.search(r"POLYGON=(\[.*\])", line)
                if name and poly:
                    try:
                        polygon = json.loads(poly.group(1))
                        center = re.search(r"CENTER=([0-9.-]+,[0-9.-]+)", line)
                        if center:
                            cx, cy = map(float, center.group(1).split(","))
                        else:
                            cx = sum(p[0] for p in polygon) / len(polygon)
                            cy = sum(p[1] for p in polygon) / len(polygon)
                        objects.append({
                            "name": name.group(1),
                            "center": [cx, cy],
                            "polygon": polygon
                        })
                    except: pass
        self._cached_exclude_payload = objects
        return {"objects": objects, "excluded_objects": list(self.excluded_objects)}

    def _finish_print(self):
        self._state = "cooling"
        self._motion_velocity = 0.0
        self._ext.set_target(0); self._bed.set_target(0)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.print_history.append({
            "filename":  f"sim_{self.shape}.gcode",
            "status":    "completed",
            "timestamp": ts,
        })
        try:
            from db.models import get_connection
            conn = get_connection(); c = conn.cursor()
            c.execute("INSERT INTO print_history (filename,status,print_time_seconds,filament_used_g,power_used_wh,cost_usd) VALUES (?,?,?,?,?,?)",
                      (f"sim_{self.shape}.gcode", "completed", self._t, self._ext.pos * 3.0, 5.0, 0.5))
            history_id = c.lastrowid
            # Virtual Spool tracking
            c.execute("SELECT id FROM spools WHERE is_active = 1 LIMIT 1")
            spool = c.fetchone()
            if spool:
                # 3.0g per meter of extrusion used in sim
                used_g = self._ext.pos * 3.0
                c.execute("UPDATE spools SET used_weight_g = used_weight_g + ? WHERE id = ?", (used_g, spool[0]))

            conn.commit(); conn.close()

            from services.qa_reporter import trigger_qa_report
            report_filename = f"qa_report_{history_id}_{int(time.time())}.pdf"
            annotated_filename = f"annotated_gcode_{history_id}_{int(time.time())}.pdf"
            self.print_history[-1]["report_path"] = report_filename
            self.print_history[-1]["annotated_gcode_path"] = annotated_filename

            # trigger_qa_report handles updating the DB for the QA report
            trigger_qa_report(history_id, self._print_start_time, time.time(), f"sim_{self.shape}.gcode")
        except Exception as e:
            logging.error(f"Failed QA trigger: {e}")
        self.gcode_feed.append({"byte": 0, "text": f"; Print #{self._print_count} complete ✓"})
        self.gcode_feed.append({"byte": 0, "text": "M104 S0 ; Extruder off"})
        self.gcode_feed.append({"byte": 0, "text": "M140 S0 ; Bed off"})
        logging.info(f"✅ Sim: print #{self._print_count} complete")

    # ── Waypoint advance ──────────────────────────────────────────────────────
    def _advance_waypoint(self):
        """
        Advance through waypoints.
        Called WAYPOINTS_PER_TICK times per tick so the print
        completes visually in ~60-90 seconds.
        Each call checks if the current waypoint is "done" and moves on.
        The axis positions jump to each waypoint directly for fast sim.
        """
        if self._wp_idx >= len(self._waypoints):
            return

        wp = self._waypoints[self._wp_idx]
        while wp.get("object") in self.excluded_objects:
            self._wp_idx += 1
            if self._wp_idx >= len(self._waypoints):
                self._finish_print()
                return
            wp = self._waypoints[self._wp_idx]

        # In sim mode, teleport to waypoint position for speed
        # (the lerp in the frontend still gives smooth visual movement)
        self._ax.pos     = wp["x"]; self._ax._target = wp["x"]
        self._ay.pos     = wp["y"]; self._ay._target = wp["y"]
        self._az.pos     = wp["z"]; self._az._target = wp["z"]

        if wp["extruding"]:
            prev_wp = self._waypoints[self._wp_idx - 1] if self._wp_idx > 0 else wp
            dist = math.sqrt((wp["x"] - prev_wp["x"])**2 + (wp["y"] - prev_wp["y"])**2)
            self._ae += dist * self._e_per_mm
            self._tick_extruding_distance += dist
            self._last_segment_distance = dist


        # Log every 50th waypoint in the terminal
        if self._wp_idx % 50 == 0:
            ext_str = f" E{self._ae:.2f}" if wp["extruding"] else " ; travel"
            self.gcode_feed.append({
                "byte": wp["byte"],
                "text": f"G1 X{wp['x']:.2f} Y{wp['y']:.2f} Z{wp['z']:.3f}{ext_str}"
            })

        self._wp_idx += 1

    # ── TEST macro ────────────────────────────────────────────────────────────
    _TEST_WP = [
        (20, 20, 5), (200, 20, 5), (200, 200, 5), (20, 200, 5), (20, 20, 5),
        (110, 110, 5), (20, 20, 5), (200, 200, 5),
        (200, 20, 5), (20, 200, 5), (110, 110, 5), (110, 110, 50),
    ]

    def _handle_cmd(self, cmd: str):
        self.gcode_feed.append({"byte": 0, "text": f">>> {cmd}"})
        if cmd == "M112":
            self._state = "error"
            self.fault = "Klipper reported: SHUTDOWN\nEmergency Stop Requested"
            self._ext.set_target(0, instant=True)
            self._bed.set_target(0, instant=True)
            self.gcode_feed.append({"byte": 0, "text": "!!! M112 EMERGENCY STOP !!!"})
            import logging
            logging.info("💥 Sim: M112 Emergency Stop")
        elif cmd == "RESTART" or cmd == "FIRMWARE_RESTART":
            self._state = "idle"
            self.fault = None
            self._ext.set_target(0, instant=True)
            self._bed.set_target(0, instant=True)
            self._ax.pos = self._bed_cx; self._ax._target = self._bed_cx
            self._ay.pos = self._bed_cy; self._ay._target = self._bed_cy
            self._az.pos = 5.0;          self._az._target = 5.0
            self.gcode_feed.append({"byte": 0, "text": f"; {cmd} completed"})
        elif cmd == "TEST":
            self._state       = "test"
            self._test_wp     = list(self._TEST_WP)
            self._test_wp_idx = 0
            self._ext.set_target(210, instant=True)
            self._bed.set_target(60,  instant=True)
            for line in [
                "; TEST — nozzle demo",
                f"G1 X20 Y20 Z5 F6000",
                f"G1 X200 Y20 Z5",
                f"G1 X200 Y200 Z5",
            ]:
                self.gcode_feed.append({"byte": 0, "text": line})
        elif cmd.startswith("G28"):
            self._ax.pos = self._bed_cx; self._ax._target = self._bed_cx
            self._ay.pos = self._bed_cy; self._ay._target = self._bed_cy
            self._az.pos = 5.;           self._az._target = 5.
            self.gcode_feed.append({"byte": 0, "text": "G28 ; Homed"})
        elif cmd.startswith("G1"):
            import re
            mx = re.search(r'X([0-9.-]+)', cmd)
            my = re.search(r'Y([0-9.-]+)', cmd)
            mz = re.search(r'Z([0-9.-]+)', cmd)
            if mx: self._ax.move_to(float(mx.group(1)))
            if my: self._ay.move_to(float(my.group(1)))
            if mz: self._az.move_to(float(mz.group(1)))

    def _advance_test(self):
        if self._test_wp_idx >= len(self._test_wp):
            self._state = "idle"; self._t = 3.
            self._ext.set_target(0); self._bed.set_target(0)
            self.gcode_feed.append({"byte": 0, "text": "TEST COMPLETE ✓"})
            return
        tx, ty, tz = self._test_wp[self._test_wp_idx]
        dist = math.sqrt((self._ax.pos - tx)**2 + (self._ay.pos - ty)**2)
        if dist < 2.:
            self._test_wp_idx += 1
            if self._test_wp_idx < len(self._test_wp):
                nx, ny, nz = self._test_wp[self._test_wp_idx]
                self._ax.move_to(nx); self._ay.move_to(ny); self._az.move_to(nz)
        else:
            self._ax.move_to(tx); self._ay.move_to(ty); self._az.move_to(tz)

    # ── Maintenance ───────────────────────────────────────────────────────────
    def _update_maintenance(self, kin, thm):
        hints  = []
        status = []
        odo    = kin.get("odometry_m", {})
        stress = kin.get("stress_score", {})
        checks = {
            "odometry_x_m":    odo.get("X", 0),
            "odometry_y_m":    odo.get("Y", 0),
            "odometry_z_m":    odo.get("Z", 0),
            "ext_heat_cycles": thm.get("ext_heat_cycles", 0),
            "bed_heat_cycles": thm.get("bed_heat_cycles", 0),
            "stress_x":        stress.get("X", 0),
            "stress_y":        stress.get("Y", 0),
        }
        for rule in MAINTENANCE_RULES:
            val = checks.get(rule["metric"], 0)
            status.append({
                "metric": rule["metric"],
                "value": val,
                "threshold": rule["threshold"],
                "msg": rule["msg"]
            })
            if val >= rule["threshold"]:
                hints.append(rule["msg"])
        self.maintenance_hints = hints
        self.maintenance_status = status
    # ── Faults ────────────────────────────────────────────────────────────────
    def _process_faults(self):
        for trigger_t, (name, param, dur) in self._fault_schedule.items():
            if (self._t >= trigger_t and name not in self._faults_fired
                    and self._state == "printing"):
                self._faults_fired.add(name)
                self._active_faults[name] = self._t + dur
                self._inject_fault(name, param)
                self.gcode_feed.append({"byte": 0, "text": f"; ⚠️ FAULT: {name}"})
                logging.info(f"💥 Sim fault: {name} for {dur}s")
        for name, recover_at in list(self._active_faults.items()):
            if self._t >= recover_at:
                del self._active_faults[name]
                self._recover_fault(name)
                self.gcode_feed.append({"byte": 0, "text": f"; ✅ RECOVERED: {name}"})

    def _inject_fault(self, name, param):
        if   name == "thermal_runaway":               self._ext.inject_runaway(param)
        elif name in ("under_extrusion", "over_extrusion"): self._ae_multiplier = param
        elif name == "lag_spike":
            self._ax.inject_lag_spike(param); self._ay.inject_lag_spike(param)

    def _recover_fault(self, name):
        if   name == "thermal_runaway":               self._ext.clear_fault()
        elif name in ("under_extrusion", "over_extrusion"): self._ae_multiplier = 1.


# Module-level singleton

    def _parse_real_gcode(self, gcode_str: str):
        """Parse G-code into waypoints with real durations.

        Durations account for:
        - Actual arc length (not chord) for G2/G3 moves
        - A 2x firmware scaling factor: Klipper's acceleration planning,
          pressure advance and look-ahead mean the real printer takes ~2x
          longer than feedrate-only math predicts (measured: feedrate math
          gives 58min, real file is 1h58m).
        """
        FIRMWARE_SCALE = 2.0
        waypoints = []
        byte = 0
        x, y, z = 0.0, 0.0, 0.0
        feedrate = 3000.0  # mm/min default
        current_obj = None

        import re, math
        for line in gcode_str.split("\n"):
            line_bytes = len((line + "\n").encode("utf-8"))
            if line.startswith("EXCLUDE_OBJECT_START"):
                if "NAME=" in line:
                    current_obj = line.split("NAME=")[1].strip()
            elif line.startswith("EXCLUDE_OBJECT_END"):
                current_obj = None

            is_arc  = line.startswith("G2 ") or line.startswith("G3 ")
            is_move = is_arc or line.startswith("G1 ") or line.startswith("G0 ")
            if is_move:
                mx_ = re.search(r"X([0-9.-]+)", line)
                my_ = re.search(r"Y([0-9.-]+)", line)
                mz_ = re.search(r"Z([0-9.-]+)", line)
                me_ = re.search(r"E([0-9.-]+)", line)
                mf_ = re.search(r"F([0-9.-]+)", line)
                mi_ = re.search(r"I([0-9.-]+)", line)
                mj_ = re.search(r"J([0-9.-]+)", line)

                if mf_:
                    feedrate = float(mf_.group(1))

                prev_x, prev_y, prev_z = x, y, z
                changed = False
                if mx_: x = float(mx_.group(1)); changed = True
                if my_: y = float(my_.group(1)); changed = True
                if mz_: z = float(mz_.group(1)); changed = True

                if changed:
                    if is_arc and mi_ and mj_:
                        # Use true arc length, not chord length
                        i = float(mi_.group(1)); j = float(mj_.group(1))
                        cx, cy = prev_x + i, prev_y + j
                        radius = math.sqrt(i*i + j*j)
                        sa = math.atan2(prev_y - cy, prev_x - cx)
                        ea = math.atan2(y - cy, x - cx)
                        isCW = line.startswith("G2")
                        if isCW and ea > sa: ea -= 2 * math.pi
                        if not isCW and ea < sa: ea += 2 * math.pi
                        dist = radius * abs(ea - sa)
                    else:
                        dist = math.sqrt((x - prev_x)**2 + (y - prev_y)**2 + (z - prev_z)**2)

                    # duration = distance / feedrate * 60s, scaled for firmware overhead
                    dur = (dist / feedrate * 60.0 * FIRMWARE_SCALE) if feedrate > 0 and dist > 0 else 0.0
                    waypoints.append({
                        "byte": byte,
                        "x": x, "y": y, "z": z,
                        "extruding": (me_ is not None),
                        "object": current_obj,
                        "duration": dur,
                    })
            byte += line_bytes

        total = sum(w["duration"] for w in waypoints)
        import logging
        logging.info(f"📏 Sim G-code duration estimate: {total:.0f}s = {total/60:.1f}min")
        return waypoints
