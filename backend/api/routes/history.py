"""
api/routes/history.py
---------------------
Full Print History and Job Intelligence API.
Provides paginated query, search, status filtering, aggregate statistics,
CSV export, and re-printing for historical print jobs.
"""

import csv
import io
import math
from typing import Dict, Any

from flask import Blueprint, jsonify, request, Response

from api import moonraker_util
from db.models import get_connection

history_bp = Blueprint("history_bp", __name__)


def _format_seconds(seconds: float) -> str:
    s = int(seconds or 0)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}h {m}m {sec}s"
    if m > 0:
        return f"{m}m {sec}s"
    return f"{sec}s"


@history_bp.route("", methods=["GET"])
def get_history():
    """Paginated list of print history jobs with search, filtering, and aggregate statistics."""
    page = max(1, request.args.get("page", 1, type=int))
    limit = max(1, min(200, request.args.get("limit", 20, type=int)))
    status = request.args.get("status", "all").strip().lower()
    search = request.args.get("search", "").strip()
    order = "ASC" if request.args.get("order", "desc").lower() == "asc" else "DESC"

    where_clauses = []
    params = []

    if status and status != "all":
        if status in ("complete", "completed"):
            where_clauses.append("LOWER(status) IN ('complete', 'completed')")
        else:
            where_clauses.append("LOWER(status) = ?")
            params.append(status)

    if search:
        where_clauses.append("filename LIKE ?")
        params.append(f"%{search}%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_connection()
    c = conn.cursor()

    # 1. Total count matching filter
    count_sql = f"SELECT COUNT(*) FROM print_history {where_sql}"
    c.execute(count_sql, params)
    total_count = c.fetchone()[0]

    # 2. Paginated rows
    offset = (page - 1) * limit
    select_cols = [
        "id", "filename", "status", "timestamp", "print_time_seconds",
        "filament_used_g", "power_used_wh", "cost_usd", "report_path",
        "annotated_gcode_path", "telemetry_hash", "excursions_count",
        "work_order_id", "timelapse_path"
    ]

    # Check available columns in current database
    c.execute("PRAGMA table_info(print_history)")
    existing_cols = {row[1] for row in c.fetchall()}
    valid_cols = [col for col in select_cols if col in existing_cols]

    cols_str = ", ".join(valid_cols)
    query_sql = f"SELECT {cols_str} FROM print_history {where_sql} ORDER BY id {order} LIMIT ? OFFSET ?"
    c.execute(query_sql, params + [limit, offset])

    jobs = []
    for row in c.fetchall():
        item = dict(zip(valid_cols, row))
        if str(item.get("status", "")).lower() == "complete":
            item["status"] = "completed"
        pts = item.get("print_time_seconds") or 0.0
        item["print_time_formatted"] = _format_seconds(pts)
        jobs.append(item)

    # 3. Overall aggregate statistics
    stats_sql = """
        SELECT 
            COUNT(*),
            COALESCE(SUM(print_time_seconds), 0.0),
            COALESCE(SUM(filament_used_g), 0.0),
            COALESCE(SUM(power_used_wh), 0.0),
            COALESCE(SUM(cost_usd), 0.0)
        FROM print_history
    """
    c.execute(stats_sql)
    tot_row = c.fetchone()

    c.execute("SELECT LOWER(status), COUNT(*) FROM print_history GROUP BY LOWER(status)")
    status_counts = dict(c.fetchall())

    completed = status_counts.get("completed", 0) + status_counts.get("complete", 0)
    cancelled = status_counts.get("cancelled", 0)
    error = status_counts.get("error", 0)
    total_prints = tot_row[0]
    success_rate = round((completed / total_prints * 100), 1) if total_prints > 0 else 0.0

    stats = {
        "total_jobs": total_prints,
        "completed_count": completed,
        "cancelled_count": cancelled,
        "error_count": error,
        "success_rate_pct": success_rate,
        "total_seconds": round(tot_row[1], 1),
        "total_hours": round(tot_row[1] / 3600.0, 1),
        "total_filament_g": round(tot_row[2], 1),
        "total_filament_kg": round(tot_row[2] / 1000.0, 2),
        "total_power_wh": round(tot_row[3], 1),
        "total_power_kwh": round(tot_row[3] / 1000.0, 2),
        "total_cost_usd": round(tot_row[4], 2),
    }

    conn.close()

    total_pages = max(1, math.ceil(total_count / limit)) if total_count > 0 else 1

    return jsonify({
        "jobs": jobs,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": total_pages,
        "stats": stats,
    })


@history_bp.route("/export", methods=["GET"])
def export_csv():
    """Export print history dataset as CSV."""
    status = request.args.get("status", "all").strip().lower()
    search = request.args.get("search", "").strip()

    where_clauses = []
    params = []
    if status and status != "all":
        if status in ("complete", "completed"):
            where_clauses.append("LOWER(status) IN ('complete', 'completed')")
        else:
            where_clauses.append("LOWER(status) = ?")
            params.append(status)
    if search:
        where_clauses.append("filename LIKE ?")
        params.append(f"%{search}%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_connection()
    c = conn.cursor()

    c.execute("PRAGMA table_info(print_history)")
    existing_cols = {row[1] for row in c.fetchall()}

    target_cols = [
        "id", "filename", "status", "timestamp", "print_time_seconds",
        "filament_used_g", "power_used_wh", "cost_usd", "report_path",
        "annotated_gcode_path", "timelapse_path", "excursions_count",
        "work_order_id"
    ]
    valid_cols = [c for c in target_cols if c in existing_cols]

    c.execute(f"SELECT {', '.join(valid_cols)} FROM print_history {where_sql} ORDER BY id DESC", params)
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(valid_cols + ["print_time_formatted"])

    pts_idx = valid_cols.index("print_time_seconds") if "print_time_seconds" in valid_cols else -1

    for row in rows:
        row_list = list(row)
        formatted_time = _format_seconds(row_list[pts_idx]) if pts_idx >= 0 else "0s"
        writer.writerow(row_list + [formatted_time])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=indus3d_print_history.csv",
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@history_bp.route("/reprint", methods=["POST"])
def reprint_job():
    """Start printing a file from history."""
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400
    filename = data.get("filename")
    job_id = data.get("id")

    if not filename and job_id is not None:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT filename FROM print_history WHERE id = ?", (job_id,))
        row = c.fetchone()
        conn.close()
        if row:
            filename = row[0]

    if not filename or not isinstance(filename, str):
        return jsonify({"error": "filename or valid job id required"}), 400

    filename = filename.strip()
    if any(char in filename for char in ('\n', '\r', ';', '"', '\\')) or any(ord(c) < 32 for c in filename):
        return jsonify({"error": "Invalid characters in filename"}), 400
    from api.routes.files import clean_rel, PathError
    try:
        filename = clean_rel(filename, allow_empty=False)
    except PathError as e:
        return jsonify({"error": str(e)}), 400
    from api.routes.printer import _printer_is_busy
    if _printer_is_busy():
        return jsonify({"error": "A print is already running or paused"}), 409
    import workers
    if workers.is_simulator(workers._active_worker):
        return jsonify({"error": "Use simulation controls to start a simulated print"}), 409

    # Execute print start via Moonraker SDCARD_PRINT_FILE
    try:
        moonraker_util.run_script_checked(f'SDCARD_PRINT_FILE FILENAME="{filename}"')
    except moonraker_util.ScriptRejected as e:
        return jsonify({"error": str(e)}), 422
    except moonraker_util.MoonrakerError as e:
        return jsonify({"error": f"Failed to start print: {e}"}), 502

    return jsonify({"status": "ok", "filename": filename})


@history_bp.route("/<int:job_id>", methods=["DELETE"])
def delete_job(job_id: int):
    """Delete a print history record."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM print_history WHERE id = ?", (job_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "Job not found"}), 404

    c.execute("DELETE FROM print_history WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "deleted_id": job_id})
