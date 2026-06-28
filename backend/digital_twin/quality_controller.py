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


class QualityController:

    def __init__(self):
        # Current commanded values (track what we last sent)
        self._flow_cmd   = 100.0   # current M221 value
        self._speed_cmd  = 100.0   # current M220 value

        # Timestamps of last command
        self._last_flow_t   = 0.0
        self._last_speed_t  = 0.0
        self._last_shaper_t = 0.0

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
            "enabled":    False,
        }

    # ── Main entry ────────────────────────────────────────────────────────────
    def update(self, snap: dict, kin: dict, thm: dict, ext: dict) -> list:
        """
        Call on every telemetry tick during printing.
        Returns a list of G-code strings to send this tick (may be empty).
        """
        if snap.get("print_state") != "printing":
            # Reset commanded values when not printing
            self._flow_cmd  = 100.0
            self._speed_cmd = 100.0
            self.active["enabled"] = False
            return []

        self.active["enabled"] = True
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

        return commands

    # ── Flow control ──────────────────────────────────────────────────────────
    def _flow_control(self, ext: dict, now: float):
        flow_ratio = ext.get("flow_ratio", 1.0)
        velocity   = ext.get("expected_flow_mm3_s", 0.0)

        # Only correct when actually extruding at meaningful speed
        if velocity < 0.5:
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
        new_flow   = round(
            max(FLOW_MIN, min(FLOW_MAX, self._flow_cmd + correction)), 1
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

        if abs(f_new - self._active["shaper_hz"]) < SHAPER_MIN_CHANGE:
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
                print(f"✅ QualityController: Y resonance baseline "
                      f"{self._f_baseline_y} Hz, bed mass {self._m_baseline_g}g")
            else:
                print("ℹ️  QualityController: no shaper baseline — "
                      "add y_resonance_hz and bed_mass_g to indus_overrides.cfg")

            self._shaper_loaded = True
        except Exception as e:
            print(f"⚠️  QualityController baseline load: {e}")
            self._shaper_loaded = True   # Don't retry

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
        print(f"🎯 QualityCtrl [{correction_type}] {value} — {reason}")


# Module-level singleton
quality_controller = QualityController()
