"""
digital_twin/kinematic_model.py
---------------------------------
All machine constants from config/printer_profile.json.
Deadband filtering on odometry to prevent floating-point noise accumulation.
"""

import math
import time
from collections import deque
from config.loader import motion, bed, alerts_cfg
from db.models import get_connection

_HISTORY_LEN       = 20
_ODOMETRY_DEADBAND = 0.05   # mm — ignore deltas smaller than this


class KinematicModel:
    def __init__(self):
        self._hist            = deque(maxlen=_HISTORY_LEN)
        self._prev_cmd        = {"x": 0.0, "y": 0.0, "z": 0.0, "e": 0.0}
        self._prev_live       = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._odometry        = {"X": 0.0, "Y": 0.0, "Z": 0.0, "E": 0.0}
        self._reversal_counts = {"X": 0, "Y": 0, "Z": 0}
        self._prev_direction  = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self._stress_score    = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        self._last_ts         = time.time()

    def _deadband(self, value: float) -> float:
        return value if abs(value) > _ODOMETRY_DEADBAND else 0.0

    def update(self, snap: dict) -> dict:
        now = time.time()
        dt  = max(now - self._last_ts, 1e-6)
        self._last_ts = now

        cx, cy, cz, ce = snap["cmd_x"], snap["cmd_y"], snap["cmd_z"], snap["cmd_e"]
        lx, ly, lz     = snap["live_x"], snap["live_y"], snap["live_z"]

        # Deadband-filtered deltas — float noise below 0.05mm is discarded
        dx = self._deadband(abs(cx - self._prev_cmd["x"]))
        dy = self._deadband(abs(cy - self._prev_cmd["y"]))
        dz = self._deadband(abs(cz - self._prev_cmd["z"]))
        de = self._deadband(abs(ce - self._prev_cmd["e"]))

        if dx or dy or dz:
            self._odometry["X"] += dx / 1000.0
            self._odometry["Y"] += dy / 1000.0
            self._odometry["Z"] += dz / 1000.0
            self._odometry["E"] += de / 1000.0
            self._persist_odometry(dx, dy, dz, de)

        # Direction reversals (belt stress indicator)
        for axis, delta in [("X", cx - self._prev_cmd["x"]),
                             ("Y", cy - self._prev_cmd["y"]),
                             ("Z", cz - self._prev_cmd["z"])]:
            if self._prev_direction[axis] != 0 and delta != 0:
                if math.copysign(1, delta) != math.copysign(1, self._prev_direction[axis]):
                    self._reversal_counts[axis] += 1
                    self._stress_score[axis]    += 0.001
            if delta != 0:
                self._prev_direction[axis] = delta

        # Positional lag
        lag_x         = round(cx - lx, 4)
        lag_y         = round(cy - ly, 4)
        lag_z         = round(cz - lz, 4)
        lag_magnitude = round(math.sqrt(lag_x**2 + lag_y**2 + lag_z**2), 4)

        # Derived velocity from finite difference of live position
        live_dx = lx - self._prev_live["x"]
        live_dy = ly - self._prev_live["y"]
        live_dz = lz - self._prev_live["z"]
        derived_velocity = round(
            math.sqrt(live_dx**2 + live_dy**2 + live_dz**2) / dt, 3
        )

        # Acceleration from velocity history
        self._hist.append({"t": now, "v": snap["velocity"]})
        accel = 0.0
        if len(self._hist) >= 2:
            h0, h1 = self._hist[-2], self._hist[-1]
            dv  = h1["v"] - h0["v"]
            dt2 = max(h1["t"] - h0["t"], 1e-6)
            accel = round(dv / dt2, 3)

        self._prev_cmd  = {"x": cx, "y": cy, "z": cz, "e": ce}
        self._prev_live = {"x": lx, "y": ly, "z": lz}

        return {
            "odometry_m":            dict(self._odometry),
            "lag_x_mm":              lag_x,
            "lag_y_mm":              lag_y,
            "lag_z_mm":              lag_z,
            "lag_magnitude_mm":      lag_magnitude,
            "derived_velocity_mm_s": derived_velocity,
            "accel_mm_s2":           accel,
            "reversal_counts":       dict(self._reversal_counts),
            "stress_score":          {k: round(v, 4) for k, v in self._stress_score.items()},
            "warn_lag_mm":           alerts_cfg["lag_magnitude_warn_mm"],
            "warn_stress":           alerts_cfg["stress_score_warn"],
            "max_velocity_mm_s":     motion["max_velocity_mm_s"],
            "bed_size":              {
                "x": bed["size_x_mm"],
                "y": bed["size_y_mm"],
                "z": bed["size_z_mm"],
            },
        }

    def _persist_odometry(self, dx, dy, dz, de):
        try:
            conn = get_connection()
            c    = conn.cursor()
            c.execute("UPDATE odometry SET travel_meters=travel_meters+? WHERE axis='X'", (dx/1000.0,))
            c.execute("UPDATE odometry SET travel_meters=travel_meters+? WHERE axis='Y'", (dy/1000.0,))
            c.execute("UPDATE odometry SET travel_meters=travel_meters+? WHERE axis='Z'", (dz/1000.0,))
            c.execute("UPDATE odometry SET travel_meters=travel_meters+? WHERE axis='E'", (de/1000.0,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️  Odometry DB: {e}")

    def get_lifetime_odometry(self) -> dict:
        try:
            conn = get_connection()
            c    = conn.cursor()
            c.execute("SELECT axis, travel_meters FROM odometry")
            rows = c.fetchall()
            conn.close()
            return {r[0]: round(r[1], 4) for r in rows}
        except Exception:
            return {}


kinematic_model = KinematicModel()
