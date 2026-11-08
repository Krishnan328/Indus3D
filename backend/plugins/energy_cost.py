"""
plugins/energy_cost.py  (G3)
------------------------------
Energy and cost per print and per day/week/month, beyond the live PZEM readout.
Source: the print_history table the telemetry worker fills at the end of every
print (energy in Wh from the PZEM, filament grams, cost_usd).

cost_usd already contains electricity at the worker's fixed 0.15/kWh, so the
filament part is recovered as  cost_usd − Wh/1000 × 0.15  and electricity is
recomputed at your own tariff, INDUS3D_ENERGY_PRICE_PER_KWH (default 0.15).
Prints recorded without a PZEM have 0 Wh; they are counted but flagged.

GET /api/v1/plugins/energy_cost?period=day|week|month&limit=30
"""

import os
import time
from datetime import datetime

PLUGIN_INFO = {
    "title": "Energy and cost",
    "description": "Per-print and per-period energy and cost at your own electricity tariff.",
}

WORKER_TARIFF = 0.15


def _bucket(ts: float, period: str) -> str:
    d = datetime.fromtimestamp(ts)
    if period == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.strftime("%Y-%m") if period == "month" else d.strftime("%Y-%m-%d")


def summarize(rows: list, price: float, period: str = "day") -> dict:
    prints, buckets = [], {}
    for r in rows:
        wh = float(r.get("power_used_wh") or 0.0)
        cost_total = float(r.get("cost_usd") or 0.0)
        filament_cost = max(0.0, cost_total - wh / 1000.0 * WORKER_TARIFF)
        elec = wh / 1000.0 * price
        p = {"id": r["id"], "filename": r["filename"], "status": r["status"], "timestamp": r["timestamp"],
             "print_hours": round((r.get("print_time_seconds") or 0) / 3600.0, 2),
             "energy_wh": round(wh, 1), "filament_g": round(float(r.get("filament_used_g") or 0.0), 1),
             "filament_cost": round(filament_cost, 3), "electricity_cost": round(elec, 3),
             "total_cost": round(filament_cost + elec, 3), "no_power_data": wh == 0.0}
        prints.append(p)
        b = buckets.setdefault(_bucket(r["ts"], period), {"prints": 0, "energy_wh": 0.0, "filament_g": 0.0,
                                                          "filament_cost": 0.0, "electricity_cost": 0.0})
        b["prints"] += 1
        b["energy_wh"] += wh
        b["filament_g"] += p["filament_g"]
        b["filament_cost"] += filament_cost
        b["electricity_cost"] += elec
    for b in buckets.values():
        b["total_cost"] = round(b["filament_cost"] + b["electricity_cost"], 3)
        for k in ("energy_wh", "filament_g", "filament_cost", "electricity_cost"):
            b[k] = round(b[k], 3)
    return {"price_per_kwh": price, "period": period,
            "periods": dict(sorted(buckets.items(), reverse=True)), "prints": prints}


def load_rows(limit: int) -> list:
    from db.models import get_connection
    conn = get_connection()
    try:
        cur = conn.execute("SELECT id, filename, status, timestamp, print_time_seconds, filament_used_g, "
                           "power_used_wh, cost_usd, strftime('%s', timestamp) FROM print_history "
                           "ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for id_, fn, st, ts, secs, g, wh, cost, epoch in cur.fetchall():
            out.append({"id": id_, "filename": fn, "status": st, "timestamp": ts, "print_time_seconds": secs,
                        "filament_used_g": g, "power_used_wh": wh, "cost_usd": cost,
                        "ts": float(epoch) if epoch else time.time()})
        return out
    finally:
        conn.close()


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("plugin_energy_cost", __name__, url_prefix="/api/v1/plugins/energy_cost")

    @bp.route("", methods=["GET"])
    def energy():
        period = request.args.get("period", "day")
        if period not in ("day", "week", "month"):
            return jsonify({"error": "period must be day, week or month"}), 400
        try:
            limit = max(1, min(500, int(request.args.get("limit", 100))))
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        price = float(os.environ.get("INDUS3D_ENERGY_PRICE_PER_KWH", WORKER_TARIFF))
        from plugins._common import latest_telemetry
        out = summarize(load_rows(limit), price, period)
        out["live_power"] = latest_telemetry().get("power")
        return jsonify(out)

    app.register_blueprint(bp)
