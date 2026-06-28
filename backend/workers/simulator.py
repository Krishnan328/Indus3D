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
from config.loader import get_profile
from workers.gcode_shapes import get_shape_gcode

POLL_HZ          = 10
_DT              = 1.0 / POLL_HZ
WAYPOINTS_PER_TICK = 5      # advance this many waypoints each tick for visible speed

# CLI flags
_shape  = "benchy"
_layers = 30       # fewer layers = faster visual completion
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
        self.latest: dict          = {}
        self.power                 = {"voltage": 0., "current": 0., "power": 0.}
        self.environment           = {"temperature": 24., "humidity": 45.}
        self.gcode_feed: deque     = deque(maxlen=10)
        self.print_history: list   = []
        self.maintenance_hints: list = []

        self.shape      = _shape
        self.gcode_str  = ""
        self._waypoints: list = []
        self._wp_idx    = 0

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
        print(f"🖨️  Pre-building sim G-code: {self.shape}, {_layers} layers…")
        self.gcode_str, self._waypoints = get_shape_gcode(self.shape, _layers)
        print(f"✅ Sim G-code ready: {len(self._waypoints)} waypoints, "
              f"{len(self.gcode_str)} bytes")

        self.gcode_feed.append({"byte": 0, "text": f"; Indus3D Sim — {self.shape.upper()}"})
        self.gcode_feed.append({"byte": 0, "text": f"; {len(self._waypoints)} waypoints ready"})
        self.gcode_feed.append({"byte": 0, "text": "G28 ; Home"})
        self.gcode_feed.append({
            "byte": 0,
            "text": f"G1 X{self._bed_cx:.1f} Y{self._bed_cy:.1f} F6000 ; Move to centre"
        })

    def start(self):
        self._thread.start()
        print("📡 SimulatedTelemetryWorker started")
        print(f"   Will start printing in ~5 seconds")

    def stop(self): self._running = False

    def inject_gcode(self, gcode: str):
        """Called by control route when user sends from terminal."""
        self._pending_gcodes.append(gcode.strip().upper())

    def inject_quality_command(self, cmd: str):
        """Called by quality_controller to show M221/M220 in terminal."""
        self.gcode_feed.append({"byte": 0, "text": f"[QC] {cmd}"})

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _loop(self):
        while self._running:
            t0 = time.time()
            try:    self._tick()
            except Exception as e: print(f"⚠️ Sim: {e}")
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
            for _ in range(WAYPOINTS_PER_TICK):   # advance multiple WPs per tick
                self._advance_waypoint()
                if self._wp_idx >= len(self._waypoints):
                    self._finish_print()
                    break

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
        velocity = round(math.sqrt(vx**2 + vy**2 + vz**2), 3)

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

        snap = {
            "online":        True,
            "sim":           True,
            "cmd_x":         cmd_x,  "cmd_y":   cmd_y,   "cmd_z":  cmd_z,
            "cmd_e":         round(self._ae * self._ae_multiplier, 4),
            "live_x":        live_x, "live_y":  live_y,  "live_z": live_z,
            "velocity":      velocity,
            "ext_temp":      self._ext.temp,   "ext_target": self._ext.target,
            "ext_pwm":       self._ext.pwm,
            "bed_temp":      self._bed.temp,   "bed_target": self._bed.target,
            "print_state":   "printing" if is_active else "standby",
            "filename":      f"sim_{self.shape}.gcode" if is_active else "",
            "file_position": current_byte if is_active else 0,
            "progress":      round(progress, 4),
            "print_duration": int(self._t),
            "time_remaining": time_rem,
            "speed_factor":  100,
            "flow_factor":   100,
        }

        printer_state.update(snap)
        kin  = kinematic_model.update(snap)
        thm  = thermal_model.update(snap)
        ext_ = extrusion_model.update(snap)

        # Quality controller — log commands to terminal in sim
        if is_active:
            cmds = quality_controller.update(snap, kin, thm, ext_)
            for cmd in cmds:
                self.inject_quality_command(cmd)   # show in terminal

        if snap["print_state"] == "printing":
            log_snapshot(snap, kin, thm, ext_)

        self._update_maintenance(kin, thm)

        self.latest = {
            **snap,
            "kinematics":        kin,
            "thermals":          thm,
            "extrusion":         ext_,
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
        self._ae     = 0.

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
        print(f"🟢 Sim: print #{self._print_count} started ({self.shape}, "
              f"{len(self._waypoints)} waypoints, {WAYPOINTS_PER_TICK} WP/tick)")

    def _finish_print(self):
        self._state = "cooling"
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
            c.execute("INSERT INTO print_history (filename,status) VALUES (?,?)",
                      (f"sim_{self.shape}.gcode", "completed"))
            conn.commit(); conn.close()
        except: pass
        self.gcode_feed.append({"byte": 0, "text": f"; Print #{self._print_count} complete ✓"})
        self.gcode_feed.append({"byte": 0, "text": "M104 S0 ; Extruder off"})
        self.gcode_feed.append({"byte": 0, "text": "M140 S0 ; Bed off"})
        print(f"✅ Sim: print #{self._print_count} complete")

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

        # In sim mode, teleport to waypoint position for speed
        # (the lerp in the frontend still gives smooth visual movement)
        self._ax.pos     = wp["x"]; self._ax._target = wp["x"]
        self._ay.pos     = wp["y"]; self._ay._target = wp["y"]
        self._az.pos     = wp["z"]; self._az._target = wp["z"]

        if wp["extruding"]:
            prev_wp = self._waypoints[self._wp_idx - 1] if self._wp_idx > 0 else wp
            dist = math.sqrt((wp["x"] - prev_wp["x"])**2 + (wp["y"] - prev_wp["y"])**2)
            self._ae += dist * 0.045

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
        if cmd == "TEST":
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
            if checks.get(rule["metric"], 0) >= rule["threshold"]:
                hints.append(rule["msg"])
        self.maintenance_hints = hints

    # ── Faults ────────────────────────────────────────────────────────────────
    def _process_faults(self):
        for trigger_t, (name, param, dur) in self._fault_schedule.items():
            if (self._t >= trigger_t and name not in self._faults_fired
                    and self._state == "printing"):
                self._faults_fired.add(name)
                self._active_faults[name] = self._t + dur
                self._inject_fault(name, param)
                self.gcode_feed.append({"byte": 0, "text": f"; ⚠️ FAULT: {name}"})
                print(f"💥 Sim fault: {name} for {dur}s")
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
telemetry_worker = SimulatedTelemetryWorker()
