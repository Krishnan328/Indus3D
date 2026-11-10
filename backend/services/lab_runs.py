"""Data and comparison helpers for the passive Printer Lab.

The lab records evidence collected by the dashboard and helper toolkit.  It
never starts a print, applies heater targets, or sends motion G-code.
"""

import json
import math
import time

from services.prediction_analysis import analyze, validate_predictions


RUN_KINDS = frozenset(("idle", "heating", "calibration", "print", "motion"))
RUN_STATUSES = frozenset(("planned", "capturing", "complete", "archived"))

# These are deliberately conservative starting points, not hardware limits.
# They are stored with every chosen baseline and can be adjusted per printer.
DEFAULT_BUDGETS = {
    "idle": {"indus_cpu_pct": 2.0, "indus_memory_mb": 100.0},
    "active_print": {"indus_cpu_pct": 20.0, "indus_memory_mb": 180.0},
    "vision": {"indus_cpu_pct": 45.0, "indus_memory_mb": 400.0},
}

NUMERIC_MEASUREMENTS = frozenset((
    "duration_s", "actual_time_s", "estimated_time_s", "energy_wh", "filament_g",
    "indus_cpu_pct", "indus_memory_mb", "mainsail_cpu_pct", "mainsail_memory_mb",
    "path_length_mm", "max_vibration", "quality_score", "extruder_temp_c", "bed_temp_c",
    "position_error_mm", "vibration_rms",
))


def _text(value, name, maximum=500):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def validate_run_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("A JSON object is required")
    clean = {}
    if not partial or "kind" in payload:
        kind = payload.get("kind", "")
        if kind not in RUN_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(RUN_KINDS))}")
        clean["kind"] = kind
    if not partial or "label" in payload:
        label = _text(payload.get("label"), "label", 120)
        if not label:
            raise ValueError("label is required")
        clean["label"] = label
    defaults = {"status": "planned"}
    for field, maximum in (("status", 32), ("printer_profile", 120), ("material", 120),
                           ("gcode_filename", 255), ("notes", 5000)):
        if not partial or field in payload:
            value = _text(payload.get(field, defaults.get(field, "")), field, maximum)
            if field == "status" and value not in RUN_STATUSES:
                raise ValueError(f"status must be one of: {', '.join(sorted(RUN_STATUSES))}")
            clean[field] = value
    if "slicer_estimated_seconds" in payload:
        value = payload["slicer_estimated_seconds"]
        clean["slicer_estimated_seconds"] = None if value in (None, "") else _number(value, "slicer_estimated_seconds")
    elif not partial:
        clean["slicer_estimated_seconds"] = None

    if not partial or "measurements" in payload:
        raw = payload.get("measurements") or {}
        if not isinstance(raw, dict):
            raise ValueError("measurements must be an object")
        unknown = set(raw) - NUMERIC_MEASUREMENTS
        if unknown:
            raise ValueError(f"Unknown measurement(s): {', '.join(sorted(unknown))}")
        clean["measurements"] = {key: _number(value, key) for key, value in raw.items()
                                 if value not in (None, "")}
    if not partial or "artifacts" in payload:
        raw = payload.get("artifacts") or {}
        if not isinstance(raw, dict):
            raise ValueError("artifacts must be an object")
        clean_artifacts = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key or len(key) > 80:
                raise ValueError("artifact keys must be short text")
            if isinstance(value, list):
                clean_artifacts[key] = [_text(item, f"artifacts.{key}", 500) for item in value]
            else:
                clean_artifacts[key] = _text(value, f"artifacts.{key}", 500)
        clean["artifacts"] = clean_artifacts
    if not partial or "predictions" in payload:
        clean["predictions"] = validate_predictions(payload.get("predictions"))
    return clean


def _parse_json(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def serialize_run(row):
    columns = [col[0] for col in row.cursor_description] if hasattr(row, "cursor_description") else None
    # sqlite3.Row supports keyed access, tuples are used only by simple tests.
    get = (lambda key: row[key]) if not isinstance(row, tuple) else (lambda key: row[columns.index(key)])
    return {
        "id": get("id"), "created_at": get("created_at"), "updated_at": get("updated_at"),
        "kind": get("kind"), "label": get("label"), "status": get("status"),
        "printer_profile": get("printer_profile"), "material": get("material"),
        "gcode_filename": get("gcode_filename"), "slicer_estimated_seconds": get("slicer_estimated_seconds"),
        "notes": get("notes"), "measurements": _parse_json(get("measurements_json")),
        "artifacts": _parse_json(get("artifacts_json")),
        "predictions": _parse_json(get("predictions_json")),
        "analysis": _parse_json(get("analysis_json")),
    }


def _row_to_dict(cursor, row):
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


def fetch_runs(conn, limit=100):
    old_factory = conn.row_factory
    conn.row_factory = _row_to_dict
    try:
        rows = conn.execute("SELECT * FROM lab_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.row_factory = old_factory
    return [serialize_run(row) for row in rows]


def get_run(conn, run_id):
    old_factory = conn.row_factory
    conn.row_factory = _row_to_dict
    try:
        row = conn.execute("SELECT * FROM lab_runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.row_factory = old_factory
    return serialize_run(row) if row else None


def create_run(conn, payload):
    clean = validate_run_payload(payload)
    now = time.time()
    cursor = conn.execute("""
        INSERT INTO lab_runs (created_at, updated_at, kind, label, status, printer_profile,
          material, gcode_filename, slicer_estimated_seconds, notes, measurements_json, artifacts_json,
          predictions_json, analysis_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now, now, clean["kind"], clean["label"], clean["status"], clean["printer_profile"],
          clean["material"], clean["gcode_filename"], clean["slicer_estimated_seconds"], clean["notes"],
          json.dumps(clean["measurements"], sort_keys=True), json.dumps(clean["artifacts"], sort_keys=True),
          json.dumps(clean["predictions"], sort_keys=True),
          json.dumps(analyze(clean["predictions"], clean["measurements"], clean["slicer_estimated_seconds"]), sort_keys=True)))
    conn.commit()
    return get_run(conn, cursor.lastrowid)


def update_run(conn, run_id, payload):
    current = get_run(conn, run_id)
    if not current:
        return None
    clean = validate_run_payload(payload, partial=True)
    if not clean:
        return current
    fields, values = [], []
    for key, value in clean.items():
        column = {"measurements": "measurements_json", "artifacts": "artifacts_json", "predictions": "predictions_json"}.get(key, key)
        fields.append(f"{column} = ?")
        values.append(json.dumps(value, sort_keys=True) if key in ("measurements", "artifacts", "predictions") else value)
    merged_measurements = clean.get("measurements", current["measurements"])
    merged_predictions = clean.get("predictions", current["predictions"])
    estimate = clean.get("slicer_estimated_seconds", current["slicer_estimated_seconds"])
    fields.append("analysis_json = ?")
    values.append(json.dumps(analyze(merged_predictions, merged_measurements, estimate), sort_keys=True))
    fields.append("updated_at = ?")
    values.extend((time.time(), run_id))
    conn.execute(f"UPDATE lab_runs SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    return get_run(conn, run_id)


def _validate_budgets(raw):
    if raw is None:
        return {state: values.copy() for state, values in DEFAULT_BUDGETS.items()}
    if not isinstance(raw, dict):
        raise ValueError("budgets must be an object")
    clean = {state: values.copy() for state, values in DEFAULT_BUDGETS.items()}
    for state, values in raw.items():
        if state not in DEFAULT_BUDGETS or not isinstance(values, dict):
            raise ValueError("budgets must use idle, active_print, or vision states")
        allowed = set(DEFAULT_BUDGETS[state])
        if set(values) - allowed:
            raise ValueError("budgets contain an unsupported metric")
        clean[state].update({metric: _number(value, metric) for metric, value in values.items()})
    return clean


def create_baseline(conn, name, run_id, budgets=None):
    name = _text(name, "name", 80)
    if not name:
        raise ValueError("baseline name is required")
    if not get_run(conn, run_id):
        raise LookupError("run not found")
    clean_budgets = _validate_budgets(budgets)
    try:
        cursor = conn.execute("""
            INSERT INTO lab_baselines (name, run_id, created_at, budgets_json)
            VALUES (?, ?, ?, ?)
        """, (name, run_id, time.time(), json.dumps(clean_budgets, sort_keys=True)))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("A baseline with that name or run already exists") from None
        raise
    conn.commit()
    return get_baseline(conn, cursor.lastrowid)


def get_baseline(conn, baseline_id):
    cursor = conn.execute("""
        SELECT b.id AS baseline_id, b.name AS baseline_name, b.created_at AS baseline_created_at,
               b.budgets_json, r.* FROM lab_baselines b JOIN lab_runs r ON r.id = b.run_id
        WHERE b.id = ?
    """, (baseline_id,)).fetchone()
    row = cursor
    if not row:
        return None
    # sqlite's default cursor yields tuples; custom callers may use sqlite3.Row.
    names = [description[0] for description in conn.execute("""
        SELECT b.id AS baseline_id, b.name AS baseline_name, b.created_at AS baseline_created_at,
               b.budgets_json, r.* FROM lab_baselines b JOIN lab_runs r ON r.id = b.run_id
        WHERE b.id = ?
    """, (baseline_id,)).description]
    record = row if isinstance(row, dict) else dict(zip(names, row))
    return {"id": record["baseline_id"], "name": record["baseline_name"],
            "created_at": record["baseline_created_at"], "budgets": _parse_json(record["budgets_json"]),
            "run": serialize_run(record)}


def fetch_baselines(conn):
    rows = conn.execute("SELECT id FROM lab_baselines ORDER BY created_at DESC").fetchall()
    return [get_baseline(conn, row[0]) for row in rows]


def compare_measurements(run, baseline):
    """Return comparable metrics and their deltas; absent values remain absent."""
    baseline_metrics = baseline["run"]["measurements"]
    result = {}
    for metric, value in run["measurements"].items():
        reference = baseline_metrics.get(metric)
        if reference is None:
            continue
        delta = value - reference
        result[metric] = {"value": value, "baseline": reference, "delta": delta,
                          "delta_pct": (delta / reference * 100) if reference else None}
    return result


def budget_evaluation(run, budgets):
    metrics = run["measurements"]
    result = {}
    for state, limits in budgets.items():
        state_result = {}
        for metric, limit in limits.items():
            value = metrics.get(metric)
            state_result[metric] = {"limit": limit, "value": value,
                                    "pass": value is None or value <= limit}
        result[state] = state_result
    return result
