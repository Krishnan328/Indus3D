"""Guarded calibration planning; intentionally no printer-control implementation."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict

from services.prediction_analysis import analyze, finite_nonnegative, validate_predictions


PREFLIGHT_FLAGS = ("operator_present", "bed_clear", "emergency_stop_accessible", "no_active_job_confirmed", "rollback_snapshot_confirmed")
PHASES = {
    "bed_geometry": {"label": "Bed geometry and mesh validation", "command": "BED_MESH_OUTPUT", "note": "Compare the mesh output against the configured geometry before probing."},
    "bed_mesh": {"label": "Bed mesh", "command": "G28\nBED_MESH_CALIBRATE", "note": "Requires a configured probe and an attended, clear bed."},
    "pid_hotend": {"label": "Hotend PID", "command": "PID_CALIBRATE HEATER=extruder TARGET={target}", "note": "Review the target and observe the full cycle; values are not persisted by this workflow."},
    "pid_bed": {"label": "Bed PID", "command": "PID_CALIBRATE HEATER=heater_bed TARGET={target}", "note": "Review the target and observe the full cycle; values are not persisted by this workflow."},
    "input_shaping": {"label": "Input shaping", "command": "SHAPER_CALIBRATE", "note": "Requires correctly installed accelerometer hardware and operator supervision."},
    "flow": {"label": "Flow validation", "command": None, "note": "Generate a review-only flow artifact with tools/indus3d_lab/calibration; manually measure its result."},
    "pressure_advance": {"label": "Pressure advance", "command": None, "note": "Generate a review-only pressure-advance artifact and inspect the printed transitions manually."},
    "first_layer": {"label": "First-layer / Z-offset", "command": "G28\nPROBE_CALIBRATE", "note": "Use the printer's supervised probe-calibration interaction; do not persist automatically."},
    "validation": {"label": "Final validation print", "command": None, "note": "Run only an operator-approved validation print, then attach the report and real-world measurements."},
}


def _json(value: Any) -> Dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _serialize(row):
    names = ("id", "created_at", "updated_at", "status", "preflight_json", "rollback_json", "evidence_json", "persistence_approval_json")
    item = row if isinstance(row, dict) else dict(zip(names, row))
    return {"id": item["id"], "created_at": item["created_at"], "updated_at": item["updated_at"],
            "status": item["status"], "preflight": _json(item["preflight_json"]),
            "rollback": _json(item["rollback_json"]), "evidence": _json(item["evidence_json"]),
            "persistence_approval": _json(item["persistence_approval_json"])}


def get_workflow(conn, workflow_id):
    row = conn.execute("SELECT * FROM calibration_workflows WHERE id = ?", (workflow_id,)).fetchone()
    return _serialize(row) if row else None


def create_workflow(conn, preflight, readiness, rollback_snapshot):
    if not readiness.get("ready"):
        raise RuntimeError(readiness.get("reason") or "Printer is not ready")
    if not isinstance(preflight, dict) or any(preflight.get(flag) is not True for flag in PREFLIGHT_FLAGS):
        raise ValueError("All physical preflight acknowledgements are required")
    if not isinstance(rollback_snapshot, dict) or not rollback_snapshot:
        raise ValueError("A rollback snapshot is required before command planning")
    workflow_id, now = str(uuid.uuid4()), time.time()
    conn.execute("""
        INSERT INTO calibration_workflows (id, created_at, updated_at, status, preflight_json, rollback_json)
        VALUES (?, ?, ?, 'prepared', ?, ?)
    """, (workflow_id, now, now, json.dumps(preflight, sort_keys=True), json.dumps(rollback_snapshot, sort_keys=True)))
    conn.commit()
    return get_workflow(conn, workflow_id)


def _guard(conn, workflow_id, readiness):
    workflow = get_workflow(conn, workflow_id)
    if not workflow:
        raise LookupError("Calibration workflow was not found")
    if workflow["status"] not in ("prepared", "validated"):
        raise RuntimeError("Calibration workflow is not open")
    if not readiness.get("ready"):
        raise RuntimeError(readiness.get("reason") or "Printer is not ready")
    if any(workflow["preflight"].get(flag) is not True for flag in PREFLIGHT_FLAGS) or not workflow["rollback"]:
        raise RuntimeError("Physical preflight and rollback snapshot are required")
    return workflow


def plan_command(conn, workflow_id, phase, payload, readiness):
    _guard(conn, workflow_id, readiness)
    if phase not in PHASES:
        raise ValueError("Unknown calibration phase")
    item = PHASES[phase]
    command = item["command"]
    if phase in ("pid_hotend", "pid_bed"):
        target = finite_nonnegative((payload or {}).get("target"), "target")
        low, high = ((150, 300) if phase == "pid_hotend" else (40, 120))
        if not low <= target <= high:
            raise ValueError(f"{phase} target must be {low}–{high} °C")
        command = command.format(target=f"{target:.0f}")
    return {"phase": phase, **item, "command": command, "execution": "not performed",
            "required_next_action": "Review this plan, complete physical checks again, then use your printer's supervised/manual execution path."}


def record_collection(conn, workflow_id, snapshot, readiness):
    workflow = _guard(conn, workflow_id, readiness)
    evidence = workflow["evidence"]
    evidence.setdefault("collections", []).append({"recorded_at": time.time(), "snapshot": snapshot})
    conn.execute("UPDATE calibration_workflows SET evidence_json = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(evidence, sort_keys=True), time.time(), workflow_id))
    conn.commit()
    return get_workflow(conn, workflow_id)


def record_validation(conn, workflow_id, payload, readiness):
    workflow = _guard(conn, workflow_id, readiness)
    report_path = payload.get("report_path") if isinstance(payload, dict) else None
    if not isinstance(report_path, str) or not report_path.strip():
        raise ValueError("A final validation report path is required")
    predictions = validate_predictions(payload.get("predictions"))
    raw_measurements = payload.get("measurements") or {}
    if not isinstance(raw_measurements, dict):
        raise ValueError("measurements must be an object")
    measurements = {key: finite_nonnegative(value, key) for key, value in raw_measurements.items()}
    evidence = workflow["evidence"]
    evidence["final_validation"] = {"recorded_at": time.time(), "report_path": report_path.strip(),
                                    "analysis": analyze(predictions, measurements), "operator_reviewed_part": payload.get("operator_reviewed_part") is True}
    conn.execute("UPDATE calibration_workflows SET evidence_json = ?, status = 'validated', updated_at = ? WHERE id = ?",
                 (json.dumps(evidence, sort_keys=True), time.time(), workflow_id))
    conn.commit()
    return get_workflow(conn, workflow_id)


def approve_persistence(conn, workflow_id, operator):
    workflow = get_workflow(conn, workflow_id)
    if not workflow:
        raise LookupError("Calibration workflow was not found")
    if workflow["status"] != "validated" or not workflow["evidence"].get("final_validation", {}).get("operator_reviewed_part"):
        raise RuntimeError("A reviewed final validation print and report are required before persistence approval")
    if not isinstance(operator, str) or not operator.strip() or len(operator.strip()) > 120:
        raise ValueError("An approving operator is required")
    approval = {"approved_by": operator.strip(), "approved_at": time.time(),
                "scope": "approval record only; no Klipper setting was persisted automatically"}
    conn.execute("UPDATE calibration_workflows SET persistence_approval_json = ?, status = 'approved', updated_at = ? WHERE id = ?",
                 (json.dumps(approval, sort_keys=True), time.time(), workflow_id))
    conn.commit()
    return get_workflow(conn, workflow_id)
