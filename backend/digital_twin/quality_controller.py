"""
digital_twin/quality_controller.py
------------------------------------
Closed-loop print quality controller.

Three independent control loops run every tick during active printing:

1. FLOW CONTROL (M221)
   Monitors flow_ratio from extrusion_model.
   If actual flow diverges from expected, sends M221 to correct.
   Acts like a software outer loop around Klipper's extruder stepper.

2. SPEED-LAG FEEDBACK (M220)
   Monitors lag_magnitude from kinematic_model.
   If the printer can't keep up with commanded position, reduces speed.
   Restores speed gradually as lag recovers.

3. VARIABLE INPUT SHAPING (SET_INPUT_SHAPER)
   Only for bed-slinger kinematics (cartesian).
   As filament accumulates mass on the bed, Y-axis resonance frequency
   drops. Corrects in real time using:
       f_new = f_baseline * sqrt(m_baseline / m_total)

All commands are rate-limited and clamped to safe ranges.
All corrections are logged and exposed via .corrections dict.
"""

import logging
import time
import math
from config.loader import get_profile

# ── Safe command ranges ───────────────────────────────────────────────────────
FLOW_MIN        = 85      # M221 lower bound (%)
FLOW_MAX        = 115     # M221 upper bound (%)
SPEED_MIN       = 50      # M220 lower bound (%)
SPEED_MAX       = 100     # M220 upper bound (%)

# ── Control gains ─────────────────────────────────────────────────────────────
FLOW_KP         = 8.0     # Proportional gain for flow correction
FLOW_DEADBAND   = 0.04    # Flow ratio deadband (±4% = no action)
FLOW_MIN_INTERVAL  = 8.0  # Seconds between M221 commands

SPEED_KP        = 15.0    # Gain: mm of lag → % speed reduction
SPEED_DEADBAND  = 0.3     # mm lag before speed control activates
SPEED_RESTORE   = 2.0     # % speed restored per second when lag clears
SPEED_MIN_INTERVAL = 3.0  # Seconds between M220 commands

SHAPER_INTERVAL = 30.0    # Seconds between SET_INPUT_SHAPER commands
SHAPER_MIN_CHANGE = 0.5   # Hz change threshold before updating

# ── Dynamic Control Models ──────────────────────────────────────────────────
import digital_twin.control_models as control_models
from digital_twin.bed_safety import bed_safety


class QualityController:

    def __init__(self):
        # Auto-pilot mode: If False, twin does math but sends NO commands
        self._auto_pilot = self._load_persisted_autopilot()

        # Dynamic settings live in the profile's print section. Keep a
        # complete fallback so a partially populated printer profile cannot
        # make the control loop crash during an active print.
        profile = get_profile() or {}
        self._profile = profile.get("print", profile)

        # Current commanded values (track what we last sent)
        self._flow_cmd   = 100.0   # current M221 value
        self._speed_cmd  = 100.0   # current M220 value

        self._pa_cmd       = None
        self._temp_cmd     = None
        self._fan_cmd      = None
        self._accel_cmd    = None
        self._z_offset_cmd = None
        self._velocity_cmd = None
        self._scv_cmd      = None
        self._retract_cmd  = None

        # Timestamps of last command
        self._last_flow_t   = 0.0
        self._last_speed_t  = 0.0
        self._last_shaper_t = 0.0
        self._last_dynamic_t = 0.0
        self._temp_err_int = 0.0
        self._z_err_int = 0.0
        self._last_layer_z = 0.0
        self._last_layer_t = 0.0
        self._flow_err_int = 0.0

        # Input shaper baseline (loaded from profile on first run)
        self._shaper_loaded      = False
        self._f_baseline_y       = 0.0
        self._m_baseline_g       = 0.0
        self._kinematics         = "cartesian"
        self._shaper_type_y      = "mzv"

        # Corrections log (shown in frontend)
        self.corrections: list = []   # [{ts, type, value, reason}]
        self.active: dict = {
            "flow_pct":   100,
            "speed_pct":  100,
            "shaper_hz":  0,
            "pa": 0.04,
            "temp": 220,
            "fan": 0,
            "z_offset": 0.0,
            "accel": 3000,
            "velocity": 300,
            "scv": 5.0,
            "retraction": 1.0,
            "pressure": 0.0,
            "enabled":    self._auto_pilot,
        }

    def _load_persisted_autopilot(self) -> bool:
        try:
            from db.models import get_connection
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT value FROM printer_config WHERE key = 'auto_pilot_enabled'")
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                return row[0].lower() in ("true", "1", "yes")
        except Exception:
            pass
        return False

    # ── Main entry ────────────────────────────────────────────────────────────
    @property
    def auto_pilot(self):
        return self._auto_pilot

    @auto_pilot.setter
    def auto_pilot(self, value):
        self._auto_pilot = bool(value)
        if hasattr(self, 'active'):
            self.active["enabled"] = self._auto_pilot
        try:
            from db.models import get_connection
            conn = get_connection()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO printer_config (key, value) VALUES ('auto_pilot_enabled', ?)",
                      ("true" if self._auto_pilot else "false",))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def update(self, snap: dict, kin: dict, thm: dict, ext: dict) -> list:
        """
        Call on every telemetry tick during printing.
        Returns a list of G-code strings to send this tick (may be empty).
        """
        if snap.get("print_state") != "printing":
            # Reset commanded values when not printing
            self._flow_cmd  = 100.0
            self._speed_cmd = 100.0
            return []

        # Autopilot is deliberately opt-in. Besides returning G-code, the
        # dynamic path can pause a printer for a predicted clog, so it must
        # not run merely because the dashboard is observing a print.
        if not self.auto_pilot:
            return []

        commands = []
        now      = time.time()

        # Load shaper baseline once per session
        if not self._shaper_loaded:
            self._load_shaper_baseline()

        # ── 1. Flow control ──────────────────────────────────────────────────
        flow_cmd = self._flow_control(ext, now)
        if flow_cmd:
            commands.append(flow_cmd)

        # ── 2. Speed-lag feedback ────────────────────────────────────────────
        speed_cmd = self._speed_control(kin, now)
        if speed_cmd:
            commands.append(speed_cmd)

        # ── 3. Variable input shaping (bed slingers only) ────────────────────
        shaper_cmd = self._shaper_control(ext, now)
        if shaper_cmd:
            commands.append(shaper_cmd)

        # ── 4. Dynamic Control Models (PA, Temp, Fan, Accel, Z) ──────────────
        dynamic_cmds = self._dynamic_params(ext, snap, thm, kin, now)
        if dynamic_cmds:
            commands.extend(dynamic_cmds)

        return commands

    # ── Flow control ──────────────────────────────────────────────────────────
    def _flow_control(self, ext: dict, now: float):
        flow_ratio = ext.get("flow_ratio", 1.0)
        velocity   = ext.get("expected_flow_mm3_s", 0.0)

        # Only correct when actually extruding at meaningful speed
        if not ext.get("is_extruding", False) or velocity < 0.5:
            return None

        error = 1.0 - flow_ratio   # positive = under-extruding

        # Deadband
        if abs(error) < FLOW_DEADBAND:
            return None

        # Rate limit
        if now - self._last_flow_t < FLOW_MIN_INTERVAL:
            return None

        # Proportional correction
        correction = error * FLOW_KP * 100

        # ── Area 1: Curved Toolpath Over-extrusion Compensation ─────────────
        # If the extruder is traversing a curve (theta > 0), the inner radius
        # accumulates material. We dampen the target flow.
        curvature_theta = ext.get("curvature_theta", 0.0) # Placeholder from kin
        curve_multiplier = control_models.calc_curved_toolpath_flow(
            h=ext.get("layer_height_mm", 0.2),
            d=ext.get("filament_dia_mm", 1.75),
            theta=curvature_theta
        )

        base_target = self._flow_cmd + correction
        adjusted_target = base_target * curve_multiplier

        new_flow = round(
            max(FLOW_MIN, min(FLOW_MAX, adjusted_target)), 1
        )

        if abs(new_flow - self._flow_cmd) < 0.5:
            return None

        self._flow_cmd    = new_flow
        self._last_flow_t = now
        self.active["flow_pct"] = int(new_flow)

        reason = (
            f"flow_ratio={flow_ratio:.3f} → "
            f"{'under' if error > 0 else 'over'}-extrusion correction"
        )
        self._log("flow", new_flow, reason)
        return f"M221 S{int(new_flow)}"

    # ── Speed-lag feedback ────────────────────────────────────────────────────
    def _speed_control(self, kin: dict, now: float):
        lag = kin.get("lag_magnitude_mm", 0.0)

        # Rate limit
        if now - self._last_speed_t < SPEED_MIN_INTERVAL:
            return None

        if lag > SPEED_DEADBAND:
            # Reduce speed proportional to lag
            reduction  = lag * SPEED_KP
            new_speed  = round(
                max(SPEED_MIN, self._speed_cmd - reduction), 1
            )
        else:
            # Gradually restore speed
            restore    = SPEED_RESTORE * SPEED_MIN_INTERVAL
            new_speed  = round(
                min(SPEED_MAX, self._speed_cmd + restore), 1
            )

        if abs(new_speed - self._speed_cmd) < 1.0:
            return None

        self._speed_cmd    = new_speed
        self._last_speed_t = now
        self.active["speed_pct"] = int(new_speed)

        reason = f"lag={lag:.3f}mm → speed {'reduced' if lag > SPEED_DEADBAND else 'restored'}"
        self._log("speed", new_speed, reason)
        return f"M220 S{int(new_speed)}"

    # ── Variable input shaping ────────────────────────────────────────────────
    def _shaper_control(self, ext: dict, now: float):
        # Only for cartesian bed slingers
        if self._kinematics != "cartesian":
            return None

        # Need baseline values
        if self._f_baseline_y <= 0 or self._m_baseline_g <= 0:
            return None

        # Rate limit
        if now - self._last_shaper_t < SHAPER_INTERVAL:
            return None

        # Calculate part mass from filament consumed
        filament_m      = ext.get("filament_consumed_m", 0.0) * 1000   # → mm
        fil_dia         = ext.get("filament_dia_mm", 1.75)
        fil_area        = math.pi * (fil_dia / 2) ** 2                  # mm²
        filament_vol    = filament_m * fil_area                         # mm³
        part_mass_g     = filament_vol * 1.24 / 1000                   # g (PLA density)

        m_total = self._m_baseline_g + part_mass_g

        # New Y resonance frequency
        f_new = round(
            self._f_baseline_y * math.sqrt(self._m_baseline_g / m_total), 2
        )

        if abs(f_new - self.active["shaper_hz"]) < SHAPER_MIN_CHANGE:
            return None

        self._last_shaper_t = now
        self.active["shaper_hz"] = f_new

        reason = (
            f"part_mass={part_mass_g:.1f}g, "
            f"m_total={m_total:.0f}g → "
            f"f_Y: {self._f_baseline_y:.1f}→{f_new:.1f} Hz"
        )
        self._log("shaper", f_new, reason)
        return f"SET_INPUT_SHAPER SHAPER_FREQ_Y={f_new} SHAPER_TYPE_Y={self._shaper_type_y}"

    # ── Baseline loader ───────────────────────────────────────────────────────
    def _load_shaper_baseline(self):
        try:
            import configparser, os
            profile = get_profile()
            self._kinematics = profile.get("kinematics", "cartesian")

            # Read from indus_overrides.cfg
            cfg_path = os.path.join(
                os.path.dirname(__file__), "..", "config", "indus_overrides.cfg"
            )
            cfg = configparser.ConfigParser()
            cfg.optionxform = str
            cfg.read(cfg_path)
            sec = dict(cfg["indus3d"]) if "indus3d" in cfg else {}

            self._f_baseline_y  = float(sec.get("y_resonance_hz",  "0"))
            self._m_baseline_g  = float(sec.get("bed_mass_g",       "0"))
            self._shaper_type_y = sec.get("y_shaper_type", "mzv")

            if self._f_baseline_y > 0:
                self.active["shaper_hz"] = self._f_baseline_y
                logging.info(f"✅ QualityController: Y resonance baseline "
                      f"{self._f_baseline_y} Hz, bed mass {self._m_baseline_g}g")
            else:
                logging.info("ℹ️  QualityController: no shaper baseline — "
                      "add y_resonance_hz and bed_mass_g to indus_overrides.cfg")

            self._shaper_loaded = True
        except Exception as e:
            logging.info(f"⚠️  QualityController baseline load: {e}")
            self._shaper_loaded = True   # Don't retry

    def reload_shaper_baseline(self):
        """Re-read a newly saved shaper baseline without restarting Indus3D."""
        self._shaper_loaded = False
        self._load_shaper_baseline()

    # ── Logging ───────────────────────────────────────────────────────────────
    def _log(self, correction_type: str, value: float, reason: str):
        entry = {
            "ts":     time.time(),
            "type":   correction_type,
            "value":  value,
            "reason": reason,
        }
        self.corrections.insert(0, entry)
        self.corrections = self.corrections[:50]   # keep last 50
        logging.info(f"🎯 QualityCtrl [{correction_type}] {value} — {reason}")


    # ── Dynamic Mathematical Models ───────────────────────────────────────────
    def _dynamic_params(self, ext: dict, snap: dict, thm: dict, kin: dict, now: float) -> list:
        commands = []
        dt = 5.0
        # Run every 5 seconds to avoid spamming commands
        if now - self._last_dynamic_t < dt:
            return commands

        self._last_dynamic_t = now
        q_current = ext.get("avg_flow_mm3_s", 0.0)

        # ── Data & Variables ──
        filament_dia = 1.75
        nozzle_dia = ext.get("nozzle_dia_mm", 0.4)
        layer_height = ext.get("layer_height_mm", 0.2)
        segment_dist = snap.get("segment_distance", 10.0)
        machine_accel = snap.get("machine_accel", 3000.0)
        z_height = snap.get("live_z", 0.0)
        feed_velocity = snap.get("velocity", 60.0)

        # ── Group A: Bead Geometry ──
        fil_area = math.pi * (filament_dia / 2.0) ** 2
        feed_mm_s = (q_current / fil_area) if fil_area > 0 else 0.0
        predicted_width = control_models.calc_analytical_bead_width(filament_dia, layer_height, feed_mm_s, feed_velocity)
        # Use true stadium bead cross section
        bead_area = control_models.calc_bead_cross_section(predicted_width, layer_height)

        # 1. Pressure Advance (Using Volumetric Flow with bounds)
        pa_base = float(self._profile.get("linear_advance_k", 0.04))
        raw_pa = control_models.calc_pressure_advance(q_current, 10.0, pa_base)
        new_pa = round(max(0.0, min(0.20, raw_pa)), 4)
        if self._pa_cmd != new_pa:
            self._pa_cmd = new_pa
            self.active["pa"] = new_pa
            commands.append(f"SET_PRESSURE_ADVANCE ADVANCE={new_pa}")
            self._log("pa", new_pa, f"flow={q_current:.1f}mm3/s")

        # 2. Thermal Dynamics & Cooling with Integral Control (Group E)
        t_base = float(snap.get("ext_target", 220.0))
        current_temp = float(snap.get("ext_temp", t_base))

        # First-Order Thermal Lag: predict true melt zone temp
        predicted_temp = control_models.calc_thermal_lag(current_temp, t_base, dt=dt)

        # Group E: Integral tracking error for temperature (with anti-windup clamp)
        temp_error = t_base - predicted_temp
        self._temp_err_int = max(-40.0, min(40.0, self._temp_err_int + temp_error * dt))

        # Frenkel-Bellehumeur Droplet Coalescence: if rate is too low, beads won't fuse
        coalescence_rate = control_models.calc_droplet_coalescence_rate(predicted_temp)

        if t_base > 0:
            max_temp_profile = float(self._profile.get("max_temp_c", 280.0))
            new_temp = control_models.calc_dynamic_temp(q_current, 10.0, t_base)
            # Add integral correction (PI control, max ±2°C from integral term)
            integral_adj = max(-2.0, min(2.0, 0.05 * self._temp_err_int))
            new_temp += integral_adj

            if coalescence_rate < 0.05 and q_current > 5.0:
                new_temp += 2.0  # Boost to help sintering

            # Safe physical clamp: never deviate by more than ±12°C from slicer target,
            # and never exceed machine max_temp_c - 5°C
            safe_temp_ceiling = min(max_temp_profile - 5.0, t_base + 12.0)
            safe_temp_floor = max(160.0, t_base - 10.0)
            new_temp = round(max(safe_temp_floor, min(safe_temp_ceiling, new_temp)), 1)

            if self._temp_cmd != new_temp and abs(new_temp - t_base) > 1.0:
                self._temp_cmd = new_temp
                self.active["temp"] = new_temp
                commands.append(f"M104 S{new_temp}")
                self._log("temp", new_temp, f"flow={q_current:.1f}mm3/s, coal={coalescence_rate:.3f}")

        # 4. Thermal Expansion & Layer Error Z-Offset (Group D)
        # Closed-loop layer error & layer time tracking
        bed_temp = thm.get("bed_temp", snap.get("bed_temp", 0.0))
        chamber_temp = snap.get("chamber_temp", 25.0)

        # Calculate elapsed layer time FIRST so it's available for integral accumulation
        if self._last_layer_t > 0:
            actual_layer_time = now - self._last_layer_t
        else:
            actual_layer_time = 30.0  # fallback on first layer

        if z_height - self._last_layer_z > (layer_height * 0.5):
            layer_error = (z_height - self._last_layer_z) - layer_height
            # Ignore huge jumps (travel moves / Z-hop)
            if abs(layer_error) < 1.0:
                # Ki = 0.002 → ~0.06 mm correction per 30s of 1mm layer error (gentle)
                _KI_Z = 0.002
                self._z_err_int = max(-0.25, min(0.25, self._z_err_int + layer_error * actual_layer_time * _KI_Z))

            self._last_layer_t = now
            self._last_layer_z = z_height
        else:
            actual_layer_time = max(0.1, now - self._last_layer_t) if self._last_layer_t > 0 else 30.0

        # 3. Dynamic Fan Speed & Thermal History Twin (Option 1)
        # Use lumped-capacitance model to estimate interface temperature of the previous layer
        interface_temp = control_models.calc_interlayer_cooling(predicted_temp, bed_temp, chamber_temp, actual_layer_time)

        # Base fan speed from kinematics
        new_fan = control_models.calc_dynamic_cooling(actual_layer_time)

        # Adaptive Thermal Twin: If interface cooled too much (approaching Tg), slash fan
        # If it's too hot (slump risk), boost fan.
        if interface_temp < 70.0:
            new_fan = int(new_fan * 0.2) # drastic cut to save interlayer bonding
        elif interface_temp > 130.0:
            new_fan = int(new_fan * 1.5) # boost cooling

        if coalescence_rate < 0.02:
            new_fan = int(new_fan * 0.5)

        new_fan = max(0, min(255, new_fan))

        if self._fan_cmd != new_fan:
            self._fan_cmd = new_fan
            self.active["fan"] = new_fan
            commands.append(f"M106 S{new_fan}")
            self._log("fan", new_fan, f"t_interface={interface_temp:.1f}C")

        chamber_temp = snap.get("chamber_temp", 25.0)
        thermal_z = control_models.calc_z_offset(max(0, bed_temp - 60.0), max(0, chamber_temp - 25.0))

        # Combine thermal expansion + closed-loop layer error correction
        desired_total_z = round(thermal_z - self._z_err_int, 3)
        cur_offset = self._z_offset_cmd if self._z_offset_cmd is not None else 0.0
        desired_adj = round(desired_total_z - cur_offset, 3)

        cur_x = kin.get("live_x", snap.get("cmd_x", 0.0))
        cur_y = kin.get("live_y", snap.get("cmd_y", 0.0))

        # Clamp against physical runaway crash & bed screw zones
        safe_adj = bed_safety.clamp_z_offset(cur_offset, desired_adj, x=cur_x, y=cur_y)

        if abs(safe_adj) >= 0.01:
            new_total = round(cur_offset + safe_adj, 3)
            self._z_offset_cmd = new_total
            self.active["z_offset"] = new_total
            commands.append(f"SET_GCODE_OFFSET Z_ADJUST={safe_adj} MOVE=0")
            self._log("z_offset", new_total, f"adj={safe_adj:+.3f} (thermal + closed-loop)")

        # 5. Dynamic Velocity & Jerk (SCV) with Kinematic Models
        new_v = control_models.calc_dynamic_velocity(300.0, ext.get("max_volumetric_flow", 24.0), bead_area, z_height)

        # Kinematic: Thin wall thermal limit
        new_v = control_models.calc_thin_wall_feed_rate(new_v, predicted_width)

        # Kinematic: Distance-to-speed scaling for short segments
        new_v = control_models.calc_distance_speed_scaling(segment_dist, new_v, machine_accel)
        new_v = round(new_v, 1)

        # SCV based on vibration feedback from DSP pipeline / belt stress
        stress_scores = kin.get("stress_score", {"X": 0.0, "Y": 0.0, "Z": 0.0})
        # Use the maximum stress across X and Y as the proxy for vibration/jerk
        vib_actual = max(stress_scores.get("X", 0.0), stress_scores.get("Y", 0.0))
        # Keep vib_actual within physical sensor bounds [0.1, 1.0]
        vib_actual = max(0.1, min(1.0, vib_actual))

        # calc_dynamic_jerk(vib_actual, vib_target, scv_base)
        # We target a stress of 0.3. If it hits 0.6, SCV drops.
        new_scv = round(control_models.calc_dynamic_jerk(vib_actual, 0.3, 5.0), 1)

        # Dynamic Acceleration
        new_accel = int(control_models.calc_dynamic_accel(vib_actual, 0.3, 3000.0, 500.0))

        if self._velocity_cmd != new_v or self._scv_cmd != new_scv or self._accel_cmd != new_accel:
            self._velocity_cmd = new_v
            self._scv_cmd = new_scv
            self.active["velocity"] = new_v
            self.active["scv"] = new_scv
            self._accel_cmd = new_accel
            self.active["accel"] = new_accel
            commands.append(f"SET_VELOCITY_LIMIT VELOCITY={new_v} SQUARE_CORNER_VELOCITY={new_scv} ACCEL={new_accel}")
            self._log("velocity_scv", f"V:{new_v} SCV:{new_scv} ACC:{new_accel}", f"Stress:{vib_actual:.2f}")

        # 6. Dynamic Firmware Retraction (Ooze & Stringing Compensation)
        base_retract = float(self._profile.get("base_retract_length", 1.0))
        base_retract_speed = int(self._profile.get("base_retract_speed", 35))
        new_retract = control_models.calc_dynamic_retraction(current_temp, t_base, q_current, base_retract)

        if self._retract_cmd != new_retract:
            self._retract_cmd = new_retract
            self.active["retraction"] = new_retract
            commands.append(f"SET_RETRACTION RETRACT_LENGTH={new_retract} RETRACT_SPEED={base_retract_speed}")
            self._log("retraction", new_retract, f"q={q_current:.1f}, t={current_temp:.1f}")

        # 7. Feature 4: Predictive Acoustic Clog & Jam Detection
        # If the theoretical pressure required to push the filament exceeds 100 units (arbitrary threshold for a standard stepper)
        predicted_pressure = control_models.calc_extrusion_pressure(q_current, current_temp, t_base)
        self.active["pressure"] = round(predicted_pressure, 1)
        if predicted_pressure > 100.0:
            import requests
            from config.settings import settings
            from core.alert_actions import _log_action, _flash_led_for_alert
            from core.notifications import notify
            import time
            try:
                requests.post(f"{settings.moonraker_url}/printer/print/pause", timeout=5)
                description = f"Predictive Clog Detection: Volumetric flow ({q_current:.1f} mm³/s) is too high for current nozzle temp ({current_temp:.1f}°C). Extruder motor is likely grinding/clicking. Print paused to save part."
                _log_action({"timestamp": time.time(), "alert_id": "clog_detection", "gcode": "PAUSE", "description": description, "status": "executed"})
                notify(f"⚠️ Indus3D Quality: {description}")
                _flash_led_for_alert("critical", restore_key="paused")
            except Exception as e:
                pass

        return commands

# Module-level singleton
quality_controller = QualityController()
