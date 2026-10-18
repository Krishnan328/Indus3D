"""Vibration anomaly monitor — reads DSP bridge output and raises alerts.

Called once per tick by the simulator / telemetry worker.
Returns:
  (vib_dict, alert_list)

  vib_dict  — {x, y, z} axis metrics, suitable for inclusion in self.latest
  alert_list — list of {id, level, msg} dicts mirroring the frontend alert shape
"""

from __future__ import annotations

import time

from workers.dsp_bridge import dsp_bridge

# ── Thresholds (tunable) ─────────────────────────────────────────────────────
RMS_WARN      = 0.3   # g  — sustained vibration above this is high
RMS_CRIT      = 0.8   # g  — critical vibration level
KURTOSIS_WARN = 5.0   # dimensionless — impulsive events (knocks, layer separation)
FREQ_SHIFT    = 15.0  # Hz — resonance drift from baseline triggers an alert

_EMPTY_AXIS = {"rms": 0.0, "peak_hz": 0.0, "kurtosis": 0.0,
               "magnitude": 0.0, "stiffness": 0.0, "torque_ripple": 0.0}

_EMPTY_VIB = {
    "x": dict(_EMPTY_AXIS),
    "y": dict(_EMPTY_AXIS),
    "z": dict(_EMPTY_AXIS),
    "alerts": [],
    "available": False,
}


class VibrationMonitor:
    def __init__(self):
        self._baseline_hz: dict[str, float] = {}   # axis -> established peak_hz
        self._baseline_window: list[tuple[str, float]] = []  # recent (axis, hz) for warmup
        self._warmup_samples = 10   # number of samples before baseline is trusted
        self._last_collision_ts: float = 0.0  # timestamp of last processed collision event

    def update(self, dsp_latest: dict | None, print_state: str) -> tuple[dict, list]:
        """
        Args:
            dsp_latest:   DspBridge.latest or None
            print_state:  e.g. "printing", "standby"

        Returns:
            (vib_dict, alerts)
        """
        alerts: list[dict] = []

        # ── Fast-path: collision detection ─────────────────────────────────────
        collision = dsp_bridge.latest_collision
        if collision and isinstance(collision, dict):
            event_ts = float(collision.get("timestamp", 0.0))
            if event_ts > self._last_collision_ts:
                self._last_collision_ts = event_ts
                peak_g = float(collision.get("peak_g", 0.0))
                axis   = str(collision.get("axis", "?")).upper()
                alerts.append({
                    "id":    "collision_detected",
                    "level": "critical",
                    "msg":   (
                        f"⚠️  Collision detected on {axis}-axis "
                        f"({peak_g:.2f} g) — print paused"
                    ),
                })
                # Fire corrective action (pause printer) — import here to
                # avoid circular imports at module load time
                try:
                    from core.alert_actions import execute_alert_action
                    execute_alert_action("collision_detected", print_state)
                except Exception:
                    pass  # best-effort — alert is already in the list

        if dsp_latest is None:
            vib_dict = dict(_EMPTY_VIB)
            vib_dict["alerts"] = alerts
            return vib_dict, alerts

        axes = {}
        is_printing = (print_state == "printing")

        for axis_name in ("x", "y", "z"):
            d = dsp_latest.get(axis_name, _EMPTY_AXIS)
            axes[axis_name] = d

            if not is_printing:
                continue

            rms      = d.get("rms",      0.0)
            kurtosis = d.get("kurtosis", 0.0)
            peak_hz  = d.get("peak_hz",  0.0)

            # ── RMS alerts ─────────────────────────────────────────────────
            if rms > RMS_CRIT:
                alerts.append({
                    "id":    f"vib_crit_{axis_name}",
                    "level": "critical",
                    "msg":   f"{axis_name.upper()}-axis vibration critical: {rms:.3f} g RMS",
                })
            elif rms > RMS_WARN:
                alerts.append({
                    "id":    f"vib_high_{axis_name}",
                    "level": "warn",
                    "msg":   f"{axis_name.upper()}-axis vibration high: {rms:.3f} g RMS",
                })

            # ── Kurtosis / impulse alert ───────────────────────────────────
            if kurtosis > KURTOSIS_WARN:
                alerts.append({
                    "id":    f"vib_impulse_{axis_name}",
                    "level": "warn",
                    "msg":   (
                        f"{axis_name.upper()}-axis impulse detected "
                        f"(kurtosis {kurtosis:.1f}) — possible layer knock or debris"
                    ),
                })

            # ── Resonance frequency shift ──────────────────────────────────
            if peak_hz > 1.0:   # skip DC / noise
                baseline = self._baseline_hz.get(axis_name)
                if baseline is None:
                    # Warmup: collect a few samples before trusting baseline
                    self._baseline_window.append((axis_name, peak_hz))
                    axis_samples = [hz for ax, hz in self._baseline_window
                                    if ax == axis_name]
                    if len(axis_samples) >= self._warmup_samples:
                        self._baseline_hz[axis_name] = sum(axis_samples) / len(axis_samples)
                else:
                    drift = abs(peak_hz - baseline)
                    if drift > FREQ_SHIFT:
                        alerts.append({
                            "id":    f"vib_resonance_{axis_name}",
                            "level": "warn",
                            "msg":   (
                                f"{axis_name.upper()}-axis resonance shifted "
                                f"{drift:.1f} Hz (was {baseline:.1f} Hz, now {peak_hz:.1f} Hz)"
                            ),
                        })
                    else:
                        # Slowly track baseline (EMA α=0.05)
                        self._baseline_hz[axis_name] = 0.95 * baseline + 0.05 * peak_hz

        vib_dict = {**axes, "alerts": alerts, "available": True}
        return vib_dict, alerts

    def reset_baseline(self):
        """Call at print start to re-establish frequency baseline."""
        self._baseline_hz.clear()
        self._baseline_window.clear()
        self._last_collision_ts = 0.0


# Module-level singleton
vibration_monitor = VibrationMonitor()
