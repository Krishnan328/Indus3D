"""Explain prediction-versus-reality deltas without changing a printer.

Every recommendation is an investigation or manual-review suggestion. This
module intentionally has no Moonraker, Klipper, filesystem, or network calls.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


METRICS = {
    "elapsed_time_s": {
        "actual": "actual_time_s", "tolerance_pct": 10.0, "unit": "s",
        "high": "Actual time is longer than predicted. Review acceleration, speed limits, pauses, and slicer overhead before changing a profile.",
        "low": "Actual time is shorter than predicted. Check the slicer estimate and confirm speed-factor telemetry before changing a profile.",
    },
    "energy_wh": {
        "actual": "energy_wh", "tolerance_pct": 15.0, "unit": "Wh",
        "high": "Measured energy is higher than predicted. Verify the wattmeter and inspect heat loss, chamber conditions, and heater duty cycle.",
        "low": "Measured energy is lower than predicted. Verify the meter sampling interval and the model's standby-load assumption.",
    },
    "filament_g": {
        "actual": "filament_g", "tolerance_pct": 8.0, "unit": "g",
        "high": "More material was used than predicted. Measure a calibration specimen and review extrusion multiplier or flow before any manual adjustment.",
        "low": "Less material was used than predicted. Inspect for under-extrusion and compare measured dimensions before any manual adjustment.",
    },
    "extruder_temp_c": {
        "actual": "extruder_temp_c", "tolerance_pct": 3.0, "unit": "°C",
        "high": "Nozzle temperature exceeds the prediction. Verify sensor placement and PID behaviour; do not overwrite PID values from this report.",
        "low": "Nozzle temperature trails the prediction. Check heater performance and PID settling before a supervised PID tune.",
    },
    "bed_temp_c": {
        "actual": "bed_temp_c", "tolerance_pct": 3.0, "unit": "°C",
        "high": "Bed temperature exceeds the prediction. Verify the sensor and PID settling before a supervised PID tune.",
        "low": "Bed temperature trails the prediction. Review heater capacity, bed insulation, and PID settling before a supervised PID tune.",
    },
    "path_length_mm": {
        "actual": "path_length_mm", "tolerance_pct": 5.0, "unit": "mm",
        "high": "Observed path is longer than expected. Check coordinate sampling and G-code interpretation before investigating motion configuration.",
        "low": "Observed path is shorter than expected. Check telemetry coverage and missing samples before investigating motion configuration.",
    },
    "position_error_mm": {
        "actual": "position_error_mm", "tolerance_pct": 25.0, "unit": "mm",
        "high": "Position error is higher than predicted. Inspect belts, pulleys, limits, and telemetry quality; do not compensate it automatically.",
        "low": "Position error is below prediction. Keep collecting comparable runs before tightening thresholds.",
    },
    "vibration_rms": {
        "actual": "vibration_rms", "tolerance_pct": 20.0, "unit": "",
        "high": "Vibration exceeds the prediction. Inspect mechanics and run a supervised input-shaping measurement before changing shaper values.",
        "low": "Vibration is below prediction. Confirm the sensor mount and capture conditions before changing any threshold.",
    },
}


def finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def validate_predictions(raw: Any) -> Dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("predictions must be an object")
    unsupported = set(raw) - set(METRICS)
    if unsupported:
        raise ValueError(f"Unknown prediction(s): {', '.join(sorted(unsupported))}")
    return {metric: finite_nonnegative(value, metric) for metric, value in raw.items()
            if value not in (None, "")}


def analyze(predictions: Dict[str, float], measurements: Dict[str, float], slicer_estimated_seconds: Optional[float] = None) -> Dict[str, Any]:
    """Compare matching measures, return explicit residuals and safe suggestions."""
    expected = dict(predictions)
    if "elapsed_time_s" not in expected and slicer_estimated_seconds is not None:
        expected["elapsed_time_s"] = slicer_estimated_seconds
    comparisons = {}
    recommendations = []
    absolute_percent_errors = []
    for metric, definition in METRICS.items():
        predicted = expected.get(metric)
        actual = measurements.get(definition["actual"])
        if predicted is None or actual is None:
            continue
        residual = actual - predicted
        error_pct = (residual / predicted * 100.0) if predicted else None
        within_tolerance = abs(error_pct) <= definition["tolerance_pct"] if error_pct is not None else actual == 0
        comparisons[metric] = {
            "predicted": predicted, "actual": actual, "residual": residual,
            "error_pct": error_pct, "tolerance_pct": definition["tolerance_pct"],
            "within_tolerance": within_tolerance, "unit": definition["unit"],
        }
        if error_pct is not None:
            absolute_percent_errors.append(abs(error_pct))
        if not within_tolerance:
            recommendation = definition["high"] if residual > 0 else definition["low"]
            if recommendation not in recommendations:
                recommendations.append(recommendation)
    return {
        "schema": "indus3d-prediction-reality-v1",
        "metrics_compared": len(comparisons),
        "mean_absolute_percentage_error": (sum(absolute_percent_errors) / len(absolute_percent_errors)
                                           if absolute_percent_errors else None),
        "comparisons": comparisons,
        "recommendations": recommendations or ["No out-of-tolerance matched measurements yet. Collect more comparable runs before changing a printer setting."],
        "actions_applied": [],
        "safety_note": "This analysis never sends commands or changes printer settings.",
    }


def markdown(report: Dict[str, Any]) -> str:
    """Render an auditable human report without omitting missing metrics."""
    lines = ["# Indus3D prediction-versus-reality report", "",
             f"Matched metrics: **{report['metrics_compared']}**",
             f"Mean absolute percentage error: **{report['mean_absolute_percentage_error'] if report['mean_absolute_percentage_error'] is not None else '—'}**", "",
             "## Residuals", ""]
    if not report["comparisons"]:
        lines.append("No matching prediction and real-world measurement pairs were supplied.")
    for name, item in report["comparisons"].items():
        pct = "—" if item["error_pct"] is None else f"{item['error_pct']:.2f}%"
        unit = f" {item['unit']}" if item["unit"] else ""
        state = "within tolerance" if item["within_tolerance"] else "review required"
        lines.append(f"- **{name}**: predicted {item['predicted']:.3f}{unit}; actual {item['actual']:.3f}{unit}; residual {item['residual']:+.3f}{unit} ({pct}, {state}).")
    lines.extend(["", "## Recommendations", ""])
    lines.extend(f"- {item}" for item in report["recommendations"])
    lines.extend(["", "## Safety", "", report["safety_note"], ""])
    return "\n".join(lines)
