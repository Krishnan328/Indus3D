from __future__ import annotations

"""
digital_twin/quality_controller.py
------------------------------------
Closed-loop print quality controller.

Seven independent control loops run every tick during active printing:

1. FLOW CONTROL (M221)
   Monitors flow_ratio from extrusion_model.
   If actual flow diverges from expected, sends M221 to correct.
   Acts like a software outer loop around Klipper's extruder stepper.

2. SPEED-LAG FEEDBACK (M220)
   Monitors lag_magnitude from kinematic_model.
   If the printer can't keep up with commanded position, reduces speed.
   Restores speed gradually as lag recovers.

3. VARIABLE INPUT SHAPING (SET_INPUT_SHAPER) [mass-adaptive, TVIST model]
   Only for bed-slinger kinematics (cartesian).
   As filament accumulates mass on the bed, Y-axis resonance frequency
   drops. Corrects in real time using calc_mass_adaptive_shaper_frequency()
   which tracks both frequency and damping ratio (zeta).

4. DYNAMIC PARAMS (PA, Temp, Fan, Accel, SCV, Retraction, Z-offset)
   Physics-based feedforward loop for pressure advance, thermal lag,
   interlayer cooling, kinematic velocity, and firmware retraction.

5. SINTERING / ADHESION CONTROL (M106 fan trim)
   Monitors inter-filament healing degree D_h via Costa cooling model
   + Gauss-Legendre diffusion integral (calc_sintering_healing_degree).
   Reduces fan if D_h < 0.95 to improve weld strength.

6. GRAETZ UNDERCOOLING CONTROL (M104 nozzle temp feedforward)
   Computes thermal deficit at nozzle exit using Graetz number.
   Adds ΔT feedforward to nozzle setpoint when Gz > 1.

7. SURFACE ROUGHNESS CONTROL (M220 perimeter speed trim)
   Estimates arithmetic Ra (µm) via kinematic scallop + empirical model.
   Trims outer wall speed if Ra exceeds target_ra_um threshold.

Additionally monitors:
- Nozzle clog / filament stripping via TMC current ratio
- Part warpage via ADXL Z-axis proxy → Z-hop correction

All commands are rate-limited and clamped to safe ranges.
All corrections are logged and exposed via .corrections dict.
"""

import logging

import time
import math
from config.loader import get_overrides_path, get_profile

# ── Safe command ranges ───────────────────────────────────────────────────────
FLOW_MIN        = 85      # M221 lower bound (%)
FLOW_MAX        = 115     # M221 upper bound (%)
SPEED_MIN       = 50      # M220 lower bound (%)
SPEED_MAX       = 100     # M220 upper bound (%)

# ── Control gains ─────────────────────────────────────────────────────────────
FLOW_KP         = 0.5     # Gain: flow-ratio error → fractional flow trim (0.5 = 5% per 0.10 error)
FLOW_MAX_STEP   = 5.0     # Max M221 change (percentage points) per correction
FLOW_DEADBAND   = 0.04    # Flow ratio deadband (±4% = no action)
FLOW_MIN_INTERVAL  = 8.0  # Seconds between M221 commands

SPEED_KP        = 15.0    # Gain: mm of lag → % speed reduction
SPEED_DEADBAND  = 0.3     # mm lag before speed control activates
SPEED_RESTORE   = 2.0     # % speed restored per second when lag clears
SPEED_MIN_INTERVAL = 3.0  # Seconds between M220 commands

SHAPER_INTERVAL = 30.0    # Seconds between SET_INPUT_SHAPER commands
SHAPER_MIN_CHANGE = 0.5   # Hz change threshold before updating

# ── Research model thresholds ─────────────────────────────────────────────────
SINTERING_INTERVAL   = 10.0   # Seconds between adhesion/fan sintering checks
GRAETZ_INTERVAL      = 5.0    # Seconds between Graetz undercooling temp checks
ROUGHNESS_INTERVAL   = 15.0   # Seconds between surface Ra / perimeter speed checks
WARPAGE_INTERVAL     = 5.0    # Seconds between warpage checks
THERMAL_CLOG_INTERVAL = 5.0    # Seconds between thermodynamic PWM clog checks

SINTERING_D_H_WARN   = 0.95   # D_h below this → trim fan to improve sintering
SINTERING_FAN_TRIM   = 0.30   # Fraction of current fan to subtract (max 30%)
GRAETZ_MAX_BOOST_C   = 10.0   # Max nozzle temp boost from Graetz undercooling
WARPAGE_THRESHOLD_MM = 0.35   # Warpage above this → emit Z-hop
ROUGHNESS_TARGET_UM  = 12.0   # Target surface roughness Ra in µm

# ── Dynamic Control Models ──────────────────────────────────────────────────
import digital_twin.control_models as control_models
from digital_twin.bed_safety import bed_safety


class QualityController:

    def __init__(self, shadow: bool = False):
        # Shadow instances never send or persist anything: they run the same
        # math as the real controller (auto-pilot forced on, side effects such
        # as the clog pause suppressed) so a plugin can report what the real
        # one *would* have sent while the auto-pilot is off.
        self._dry_run = shadow
        self.shadow_enabled = False
        self._shadow_instance = None
        self.last_shadow = None          # {"ts", "commands", "corrections"} of the last tick
        self._tick_corrections: list = []
        self.last_corrections: list = [] # corrections logged by the last update()

        # Auto-pilot mode: If False, twin does math but sends NO commands
        self._auto_pilot = True if shadow else self._load_persisted_autopilot()

        # Dynamic settings live in the profile's print section. Keep a
        # complete fallback so a partially populated printer profile cannot
        # make the control loop crash during an active print.
        profile = get_profile() or {}
        self._profile = profile.get("print", profile)

        # Current commanded values (track what we last sent)
        self._flow_cmd   = 100.0   # current M221 value
        self._flow_trim  = 100.0   # feedback-only flow trim (before curve factor)
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
        self._last_sintering_t = 0.0
        self._last_graetz_t  = 0.0
        self._last_roughness_t = 0.0
        self._last_warpage_t = 0.0
        self._last_thermal_clog_t = 0.0
        self._last_autoz_t = 0.0
        self._cumulative_autoz_trim = 0.0
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
            # ── Research-model metrics ──────────────────────────────────────
            "adhesion_score":  1.0,    # D_h sintering healing degree (0–1)
            "undercooling_c":  0.0,    # Graetz-driven nozzle exit ΔT (°C)
            "warpage_mm":      0.0,    # Compliance observer warpage height (mm)
            "nozzle_status":   "NORMAL",  # NORMAL | CLOG_WARNING | STRIPPING_WARNING | DUAL_CLOG_WARNING
            "thermal_ratio":   1.0,       # thermodynamic m_dot ratio (1.0 = healthy)
            "ra_predicted_um": 0.0,    # Predicted surface roughness Ra (µm)
            "zeta":            0.08,   # Damping ratio from TVIST shaper model
            # ── System ─────────────────────────────────────────────────────
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

    def notify_vetoed(self, command: str) -> None:
        """A plugin dropped ``command`` before it reached the printer.

        The controller assumed it had been applied and would not resend an
        unchanged value, so a vetoed correction would be lost for good. Forget
        the assumed state for that parameter so the next cycle recomputes and
        proposes it again (flow/speed fall back to their 100 % baseline).
        """
        token = command.strip().split(None, 1)[0].upper() if command.strip() else ""
        if token == "M221":
            self._flow_cmd = self._flow_trim = 100.0
            self.active["flow_pct"] = 100
        elif token == "M220":
            self._speed_cmd = 100.0
            self.active["speed_pct"] = 100
        elif token == "SET_PRESSURE_ADVANCE":
            self._pa_cmd = None
        elif token == "M104":
            self._temp_cmd = None
        elif token == "M106":
            self._fan_cmd = None
        elif token == "SET_VELOCITY_LIMIT":
            self._velocity_cmd = self._scv_cmd = self._accel_cmd = None
        elif token == "SET_RETRACTION":
            self._retract_cmd = None
        elif token == "SET_INPUT_SHAPER":
            self.active["shaper_hz"] = 0
            self._last_shaper_t = 0.0

    def enable_shadow(self) -> None:
        """Compute (but never send) corrections while the auto-pilot is off."""
        self.shadow_enabled = True

    def update(self, snap: dict, kin: dict, thm: dict, ext: dict, autoz: dict | None = None) -> list:
        """
        Call on every telemetry tick during printing.
        Returns a list of G-code strings to send this tick (may be empty).

        With the auto-pilot off this still returns [] — nothing is ever sent —
        but if shadow mode is enabled the would-be commands are exposed in
        ``last_shadow`` for plugins to record.
        """
        self._tick_corrections = []
        self.last_shadow = None
        commands = self._update(snap, kin, thm, ext, autoz)
        self.last_corrections = self._tick_corrections

        if self.shadow_enabled and not self._dry_run and not self.auto_pilot:
            if self._shadow_instance is None:
                self._shadow_instance = QualityController(shadow=True)
            sh = self._shadow_instance
            would_send = sh.update(snap, kin, thm, ext, autoz)
            self.last_shadow = {
                "ts": time.time(),
                "commands": list(would_send),
                "corrections": list(sh.last_corrections),
            }
        return commands

    def _update(self, snap: dict, kin: dict, thm: dict, ext: dict, autoz: dict | None = None) -> list:
        if snap.get("print_state") != "printing":
            # Reset commanded values when not printing
            self._flow_cmd  = 100.0
            self._flow_trim = 100.0
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
        dynamic_cmds = self._dynamic_params(ext, snap, thm, kin, now, autoz=autoz)
        if dynamic_cmds:
            commands.extend(dynamic_cmds)

        # ── 5. Sintering / Adhesion healing (M106 fan trim) ──────────────────
        sintering_cmds = self._sintering_control(ext, snap, now)
        if sintering_cmds:
            commands.extend(sintering_cmds)

        # ── 6. Graetz undercooling feedforward (M104 nozzle boost) ───────────
        graetz_cmd = self._undercooling_control(ext, snap, now)
        if graetz_cmd:
            commands.append(graetz_cmd)

        # ── 7. Surface roughness / perimeter speed trim (M220) ───────────────
        roughness_cmd = self._roughness_control(ext, snap, now)
        if roughness_cmd:
            commands.append(roughness_cmd)

        # ── 8. Warpage observer (Z-hop if threshold exceeded) ─────────────────
        warpage_cmd = self._warpage_control(ext, snap, kin, now)
        if warpage_cmd:
            commands.append(warpage_cmd)

        # ── 9. Thermodynamic PWM clog observer (dual-evidence with TMC current) ──
        thermal_clog_cmd = self._thermal_clog_control(ext, snap, now)
        if thermal_clog_cmd:
            commands.append(thermal_clog_cmd)

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

        # Integrate the feedback trim on its own, then apply the curve factor
        # to the commanded value only. Multiplying the stored command (as
        # before) compounded cos(theta) on every correction and ratcheted
        # flow down on curves.
        correction = max(-FLOW_MAX_STEP, min(FLOW_MAX_STEP, correction))
        self._flow_trim = max(FLOW_MIN, min(FLOW_MAX, self._flow_trim + correction))
        new_flow = round(
            max(FLOW_MIN, min(FLOW_MAX, self._flow_trim * curve_multiplier)), 1
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

    # ── Variable input shaping (TVIST mass-adaptive model) ───────────────────
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

        # Use research model: calc_mass_adaptive_shaper_frequency (Paper 2.1.64)
        # Tracks both frequency shift AND damping ratio (zeta) for TVIST
        f_d_new, zeta_new, _delta2 = control_models.calc_mass_adaptive_shaper_frequency(
            f_baseline_hz=self._f_baseline_y,
            bed_mass_g=self._m_baseline_g,
            part_mass_g=part_mass_g,
        )
        f_new = round(f_d_new, 2)

        # Update damping ratio in active metrics regardless of command threshold
        self.active["zeta"] = round(zeta_new, 4)

        if abs(f_new - self.active["shaper_hz"]) < SHAPER_MIN_CHANGE:
            return None

        self._last_shaper_t = now
        self.active["shaper_hz"] = f_new

        reason = (
            f"part_mass={part_mass_g:.1f}g, "
            f"m_total={self._m_baseline_g + part_mass_g:.0f}g → "
            f"f_Y: {self._f_baseline_y:.1f}→{f_new:.1f} Hz, ζ={zeta_new:.4f}"
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
            cfg_path = get_overrides_path()
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
        self._tick_corrections.append(entry)
        if not self._dry_run:
            logging.info(f"🎯 QualityCtrl [{correction_type}] {value} — {reason}")


    # ── Dynamic Mathematical Models ───────────────────────────────────────────
    def _dynamic_params(self, ext: dict, snap: dict, thm: dict, kin: dict, now: float, autoz: dict | None = None) -> list:
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

        # Auto-Z First-Layer Tribo-Acoustic Bed Friction & Adhesion trimming
        # Actively adjusts nozzle-to-bed distance during layer 1 based on accelerometer HFFI
        autoz_trim = 0.0
        if autoz and z_height <= 0.35 and (now - self._last_autoz_t >= 2.0):
            regime = autoz.get("regime", "optimal")
            recommended = autoz.get("recommended_trim", 0.0)
            if regime in ("rubbing", "under_squish") and abs(recommended) > 0.005:
                # Limit cumulative trim to +/- 0.08 mm to guarantee physical safety
                new_cum = round(self._cumulative_autoz_trim + recommended, 3)
                if -0.08 <= new_cum <= 0.08:
                    autoz_trim = recommended
                    self._cumulative_autoz_trim = new_cum
                    self._last_autoz_t = now

        # Combine thermal expansion + closed-loop layer error correction + Auto-Z friction trim
        desired_total_z = round(thermal_z - self._z_err_int + self._cumulative_autoz_trim, 3)
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
            commands.append(f"SET_GCODE_OFFSET Z_ADJUST={safe_adj} MOVE=1")
            reason = f"adj={safe_adj:+.3f} (thermal + closed-loop"
            if autoz_trim != 0.0:
                reason += f" + auto_z={autoz_trim:+.3f} HFFI={autoz.get('hffi', 0.0):.2f}"
            reason += ")"
            self._log("z_offset", new_total, reason)

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
        # Full non-Newtonian pipeline: ΔP → predicted I → compare to TMC current
        # (Paper 2.1.27 — Tlegenov et al.)
        delta_p = control_models.calc_non_newtonian_melt_pressure(
            q_current_mm3_s=q_current,
            current_temp_c=current_temp,
            nozzle_dia_mm=nozzle_dia,
        )
        i_predicted = control_models.calc_extruder_motor_current(delta_p_pa=delta_p)
        # Measured extruder current. No component currently populates this key
        # (the telemetry worker does not read TMC data), so only run the
        # comparison when a real measurement exists. Defaulting to the
        # prediction made the ratio always 1.0 — a detector that looked active
        # but could never fire.
        i_measured = ext.get("tmc_extruder_current_a")
        if i_measured is None:
            nozzle_status, current_ratio = "NORMAL", 1.0
            i_measured = i_predicted
        else:
            nozzle_status, current_ratio = control_models.detect_nozzle_clog_or_strip(
                i_measured_a=i_measured,
                i_predicted_a=i_predicted,
            )
        self.active["nozzle_status"] = nozzle_status
        # Convert delta_p (Pa) to legacy pressure units (kPa) for display
        predicted_pressure = delta_p / 1000.0
        self.active["pressure"] = round(predicted_pressure, 1)

        if nozzle_status == "CLOG_WARNING" and self._dry_run:
            # Shadow run: report the pause instead of performing it.
            self._log("clog_pause", current_ratio,
                      f"would pause print: current ratio {current_ratio:.2f}")
            commands.append("PAUSE")
        elif nozzle_status == "CLOG_WARNING":
            import requests
            from config.settings import settings
            from core.alert_actions import _log_action, _flash_led_for_alert
            from core.notifications import notify
            import time as _time
            try:
                requests.post(f"{settings.moonraker_url}/printer/print/pause", timeout=5)
                description = (
                    f"Nozzle clog detected: motor current ratio {current_ratio:.2f} "
                    f"(measured={i_measured:.2f}A vs predicted={i_predicted:.2f}A). "
                    f"Melt pressure={delta_p/1e6:.2f} MPa. Print paused."
                )
                _log_action({"timestamp": _time.time(), "alert_id": "clog_detection",
                             "gcode": "PAUSE", "description": description, "status": "executed"})
                notify(f"⚠️ Indus3D Quality: {description}")
                _flash_led_for_alert("critical", restore_key="paused")
            except Exception:
                pass

        return commands

    # ── Sintering / Adhesion healing control ──────────────────────────────────
    def _sintering_control(self, ext: dict, snap: dict, now: float) -> list:
        """
        Trim fan PWM if inter-filament healing degree D_h < 0.95 (SINTERING_D_H_WARN).

        Uses Costa's lumped-capacitance cooling model + 5-point Gauss-Legendre
        diffusion integral (calc_sintering_healing_degree, Papers 2.1.69–71).
        Up to 30% of the current fan command is subtracted when healing is incomplete.

        Updates self.active["adhesion_score"].
        Returns list of M106 commands if fan needs trimming, otherwise [].
        """
        if now - self._last_sintering_t < SINTERING_INTERVAL:
            return []

        q_current = ext.get("avg_flow_mm3_s", 0.0)
        if not ext.get("is_extruding", False) or q_current < 0.5:
            return []

        hotend_temp  = float(snap.get("ext_temp", 220.0))
        bed_temp     = float(snap.get("bed_temp", 60.0))
        chamber_temp = float(snap.get("chamber_temp", 25.0))
        fan_pwm      = int(self._fan_cmd if self._fan_cmd is not None else 128)
        layer_height = float(ext.get("layer_height_mm", 0.2))
        bead_width   = float(ext.get("line_width_mm",
                             self._profile.get("line_width_mm", 0.45)))
        t_glass      = float(self._profile.get("filament_t_glass_c", 60.0))
        q_diff       = float(self._profile.get("filament_q_diffusion_j_mol", 220000.0))
        actual_layer_time = float(self._profile.get("estimated_layer_time_s", 30.0))

        _t_freeze, d_h, _strength = control_models.calc_sintering_healing_degree(
            t_bead_initial_c=hotend_temp,
            t_substrate_c=bed_temp,
            t_ambient_c=chamber_temp,
            actual_layer_time_s=actual_layer_time,
            fan_pwm=fan_pwm,
            bead_width_mm=bead_width,
            layer_height_mm=layer_height,
            t_glass_c=t_glass,
            q_diffusion_j_mol=q_diff,
        )

        self.active["adhesion_score"] = round(d_h, 3)
        self._last_sintering_t = now

        commands = []
        if d_h < SINTERING_D_H_WARN and fan_pwm > 10:
            trim    = int(fan_pwm * SINTERING_FAN_TRIM)
            new_fan = max(0, fan_pwm - trim)
            if new_fan != self._fan_cmd:
                self._fan_cmd = new_fan
                self.active["fan"] = new_fan
                commands.append(f"M106 S{new_fan}")
                self._log(
                    "sintering_fan",
                    new_fan,
                    f"D_h={d_h:.3f} < {SINTERING_D_H_WARN} → fan {fan_pwm}→{new_fan}"
                )
        return commands

    # ── Graetz undercooling feedforward ───────────────────────────────────────
    def _undercooling_control(self, ext: dict, snap: dict, now: float):
        """
        Feedforward nozzle temp boost to compensate Graetz-driven core undercooling.

        When Gz > 1, advection outpaces conduction and the polymer core exits
        the nozzle cooler than the block setpoint. The boost ΔT = k_gz * ln(Gz)
        is added to the current temp command (Paper 2.1.26 — Perez et al., 2022).

        Updates self.active["undercooling_c"].
        Returns M104 command if boost > 1°C, otherwise None.
        """
        if now - self._last_graetz_t < GRAETZ_INTERVAL:
            return None

        q_current = ext.get("avg_flow_mm3_s", 0.0)
        if not ext.get("is_extruding", False) or q_current < 0.5:
            return None

        thermal_diff = float(self._profile.get("thermal_diffusivity_mm2_s", 0.085))
        melt_length  = float(self._profile.get("melt_length_mm", 15.5))
        fil_dia      = float(ext.get("filament_dia_mm", 1.75))
        t_base       = float(snap.get("ext_target", 220.0))
        max_temp     = float(self._profile.get("max_temp_c", 280.0))

        _gz, delta_t = control_models.calc_graetz_undercooling(
            q_current_mm3_s=q_current,
            filament_dia_mm=fil_dia,
            melt_length_mm=melt_length,
            thermal_diffusivity_mm2_s=thermal_diff,
        )

        boost = min(GRAETZ_MAX_BOOST_C, delta_t)
        self.active["undercooling_c"] = round(delta_t, 2)
        self._last_graetz_t = now

        if boost < 1.0:
            return None

        # Merge with _temp_cmd set by _dynamic_params
        current_cmd = self._temp_cmd if self._temp_cmd is not None else t_base
        new_temp = round(min(max_temp - 5.0, current_cmd + boost), 1)

        if abs(new_temp - current_cmd) < 0.5:
            return None

        self._temp_cmd = new_temp
        self.active["temp"] = new_temp
        self._log(
            "graetz_temp",
            new_temp,
            f"Gz undercooling ΔT={delta_t:.2f}°C → boost +{boost:.1f}°C"
        )
        return f"M104 S{new_temp}"

    # ── Surface roughness / perimeter speed control ───────────────────────────
    def _roughness_control(self, ext: dict, snap: dict, now: float):
        """
        Trim outer wall speed when predicted Ra exceeds target_ra_um.

        Uses kinematic scallop + empirical response surface (Paper 2.1.15
        — Zhang et al., 2025). calc_optimal_perimeter_parameters finds the
        minimum-time speed that achieves target Ra. The result is applied as
        a global M220 speed override (same as speed-lag feedback).

        Updates self.active["ra_predicted_um"].
        Returns M220 command if speed trim ≥ 2%, otherwise None.
        """
        if now - self._last_roughness_t < ROUGHNESS_INTERVAL:
            return None

        layer_height = float(ext.get("layer_height_mm", 0.2))
        wall_speed   = float(snap.get("velocity", 60.0))
        current_temp = float(snap.get("ext_temp", 220.0))
        target_ra    = float(self._profile.get("target_ra_um", ROUGHNESS_TARGET_UM))

        ra = control_models.calc_surface_roughness_ra(
            layer_height_mm=layer_height,
            wall_speed_mm_s=wall_speed,
            nozzle_temp_c=current_temp,
        )
        self.active["ra_predicted_um"] = round(ra, 2)
        self._last_roughness_t = now

        if ra <= target_ra:
            return None

        v_opt, _t_opt, _ra_opt = control_models.calc_optimal_perimeter_parameters(
            layer_height_mm=layer_height,
            target_ra_um=target_ra,
            t_nominal_c=current_temp,
            v_nominal_mm_s=wall_speed,
        )

        if wall_speed <= 0:
            return None

        speed_pct = round(max(float(SPEED_MIN), min(100.0, (v_opt / wall_speed) * 100.0)))
        if abs(speed_pct - self._speed_cmd) < 2.0:
            return None

        self._speed_cmd = float(speed_pct)
        self.active["speed_pct"] = int(speed_pct)
        self._log(
            "roughness_speed",
            speed_pct,
            f"Ra={ra:.2f}µm > {target_ra}µm → v_opt={v_opt:.1f}mm/s ({speed_pct}%)"
        )
        return f"M220 S{int(speed_pct)}"

    # ── Warpage observer (Z-hop correction) ──────────────────────────────────
    def _warpage_control(self, ext: dict, snap: dict, kin: dict, now: float):
        """
        Detects part warpage via ADXL345 Z-axis acceleration proxy and emits
        a Z-hop babystep when warpage_mm exceeds WARPAGE_THRESHOLD_MM.

        The DSP pipeline's normalised Z stress_score (0–1) is scaled to an
        estimated F_z (assuming max ~20 N at stress=1.0). The compliance
        observer calc_repulsive_force_warpage then reconstructs warpage height
        (Paper 2.1.28 — Armillotta et al., 2022).

        Updates self.active["warpage_mm"].
        Returns Z-hop G-code string if warpage detected, otherwise None.
        """
        if now - self._last_warpage_t < WARPAGE_INTERVAL:
            return None

        stress_scores  = kin.get("stress_score", {})
        z_stress       = float(stress_scores.get("Z", 0.0))
        f_z_estimated  = z_stress * 20.0   # scale 0–1 → 0–20 N

        nominal_lh = float(ext.get("layer_height_mm", 0.2))
        warpage_mm, is_warning = control_models.calc_repulsive_force_warpage(
            f_z_measured_n=f_z_estimated,
            nominal_layer_height_mm=nominal_lh,
            warpage_warning_threshold_mm=WARPAGE_THRESHOLD_MM,
        )

        self.active["warpage_mm"] = round(warpage_mm, 3)
        self._last_warpage_t = now

        if not is_warning:
            return None

        self._log(
            "warpage_zhop",
            warpage_mm,
            f"Z_stress={z_stress:.2f} → F_z≈{f_z_estimated:.1f}N, "
            f"warpage={warpage_mm:.3f}mm > {WARPAGE_THRESHOLD_MM}mm → Z-hop"
        )
        return "G91\nG1 Z0.3 F600\nG90"

    # ── Thermodynamic PWM clog observer ───────────────────────────────────────
    def _thermal_clog_control(self, ext: dict, snap: dict, now: float):
        """
        Dual-evidence nozzle clog detection using heater PWM energy balance.

        Complements the existing TMC current-ratio detection (_dynamic_params).
        A clog is escalated to DUAL_CLOG_WARNING only when BOTH the
        thermodynamic observer AND the TMC current observer flag a clog
        simultaneously — greatly reducing false positives.

        Physics: calc_thermodynamic_mass_flow() (Group O, control_models.py)
            Q_melt = Q_heater - Q_loss
            m_dot_thermal = Q_melt / (c_p * ΔT + Δh_fusion)
            clog_suspected if m_dot_thermal / m_dot_cmd < 0.45
        """
        if now - self._last_thermal_clog_t < THERMAL_CLOG_INTERVAL:
            return None
        self._last_thermal_clog_t = now

        ext_pwm     = snap.get("ext_pwm", 0.0)          # 0.0–1.0 Moonraker extruder.power
        t_nozzle    = snap.get("ext_temp", 25.0)
        t_ambient   = float(self._profile.get("t_ambient_c", 25.0))
        heater_w    = float(self._profile.get("heater_rated_w", 40.0))
        vol_flow    = ext.get("expected_flow_mm3_s", 0.0)

        # Only check during active extrusion
        if not ext.get("is_extruding", False) or vol_flow < 1.0 or ext_pwm <= 0.0:
            return None

        m_dot, clog_thermal, thermal_ratio = control_models.calc_thermodynamic_mass_flow(
            extruder_power_frac=ext_pwm,
            heater_rated_w=heater_w,
            t_nozzle_c=t_nozzle,
            t_ambient_c=t_ambient,
            volumetric_flow_cmd_mm3_s=vol_flow,
        )

        # Update telemetry — always expose thermal ratio for dashboard
        self.active["thermal_ratio"] = thermal_ratio

        if not clog_thermal:
            return None

        # Dual-evidence gate: only escalate if TMC current also flagged clog
        tmc_nozzle_status = self.active.get("nozzle_status", "NORMAL")
        if tmc_nozzle_status != "CLOG_WARNING":
            # Single-source thermal clog — log a warning but don't pause
            self._log("thermal_clog_warn", thermal_ratio,
                      f"thermal_ratio={thermal_ratio:.2f} (TMC not alarmed — monitoring)")
            return None

        # Both observers agree — high-confidence clog → pause print
        self.active["nozzle_status"] = "DUAL_CLOG_WARNING"
        self._log("dual_clog_detected", thermal_ratio,
                  f"thermal_ratio={thermal_ratio:.2f} + TMC CLOG_WARNING → PAUSE")

        try:
            import requests
            from config.settings import settings
            from core.alert_actions import _log_action, _flash_led_for_alert
            from core.notifications import notify
            import time as _time
            requests.post(f"{settings.moonraker_url}/printer/print/pause", timeout=5)
            description = (
                f"DUAL-EVIDENCE CLOG: thermal_ratio={thermal_ratio:.2f} "
                f"(PWM={ext_pwm:.2f}, m_dot_est={m_dot*1e6:.2f} µg/s) "
                f"+ TMC current alarm. Print paused."
            )
            _log_action({"timestamp": _time.time(), "alert_id": "dual_clog",
                         "gcode": "PAUSE", "description": description, "status": "executed"})
            notify(f"⚠️ Indus3D: {description}")
            _flash_led_for_alert("critical", restore_key="paused")
        except Exception:
            pass

        return None


# Module-level singleton
quality_controller = QualityController()
