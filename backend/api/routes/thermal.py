"""Thermal history and Moonraker sensors for the temperature chart and the Sensors card.

  GET /api/v1/printer/thermal_history?minutes=60[&max_points=600]
  GET /api/v1/printer/sensors

thermal_history merges three sources into per-series ``{"t": [epoch s...], "v": [...]}`` arrays:

* Moonraker ``/server/temperature_store``  every heater (+ target and power), temperature_sensor and
  temperature_fan, 1 sample per second for the last ~20 minutes (``temperature_store_size``). Newest data.
* SQLite ``twin_snapshots``   extruder / bed temperature and target, logged by the telemetry loop; used
  only for the part of the range older than the Moonraker store, so 1 h / 6 h / 24 h views have a line.
* SQLite ``telemetry_samples``   chamber temperature and humidity from the ESP8266 bed hub. The hub's
  temperature is only included when Klipper has no chamber sensor of its own (the fallback);
  humidity is included whenever the hub has recorded any.

Series ids are Klipper object names (``extruder``, ``heater_generic chamber``, ``temperature_sensor mcu``)
with a suffix for the extras: ``.target``, ``.power``, ``.speed``. Hub series are ``esp_bed_hub.chamber`` and
``esp_bed_hub.humidity``. Every long range is bucket-averaged to at most ``max_points`` points per series.

If Moonraker is down the database part is still returned (``sources.moonraker.ok`` is false); the endpoint
only answers 502 when there is nothing at all to show.
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from api import moonraker_util as mu
from config.settings import settings

thermal_bp = Blueprint("thermal", __name__)

MAX_MINUTES = 24 * 60
DEFAULT_POINTS, MIN_POINTS, MAX_POINTS = 600, 50, 2000
SENSOR_HISTORY_POINTS = 120
_STORE_FIELDS = {"temperatures": "", "targets": ".target", "powers": ".power", "speeds": ".speed"}
_CHAMBER_NAME = re.compile(r"chamber", re.I)

Series = Dict[str, Dict[str, list]]


# ── pure helpers ──────────────────────────────────────────────────────────────
def bucket(ts: List[float], vs: List[Optional[float]], step: float) -> Tuple[List[float], List[float]]:
    """Average samples into ``step``-second buckets (timestamp = bucket start). ``step <= 1`` returns the
    input unchanged. Nones are skipped."""
    pairs = [(t, v) for t, v in zip(ts, vs) if v is not None]
    if step <= 1 or len(pairs) < 2:
        return [p[0] for p in pairs], [p[1] for p in pairs]
    out_t, out_v, cur, acc, n = [], [], None, 0.0, 0
    for t, v in pairs:
        b = int(t // step) * step
        if b != cur and n:
            out_t.append(cur); out_v.append(round(acc / n, 3))
            acc, n = 0.0, 0
        cur = b
        acc += v; n += 1
    if n:
        out_t.append(cur); out_v.append(round(acc / n, 3))
    return out_t, out_v


def _round(values):
    return [None if v is None else round(float(v), 3) for v in values]


def moonraker_series(store: dict, now: float) -> Series:
    """Series from a ``/server/temperature_store`` result. Samples are 1 s apart and end 'now'."""
    out: Series = {}
    for obj, fields in (store or {}).items():
        if not isinstance(fields, dict):
            continue
        for field, suffix in _STORE_FIELDS.items():
            values = fields.get(field)
            if not isinstance(values, list) or not values:
                continue
            n = len(values)
            out[f"{obj}{suffix}"] = {"t": [round(now - (n - 1 - i), 1) for i in range(n)], "v": _round(values)}
    return out


def _conn():
    from db.models import get_connection
    return get_connection()


def twin_series(since: float, step: float, before: Optional[float] = None) -> Series:
    """extruder / heater_bed temperature and target from twin_snapshots, bucket-averaged."""
    conn = _conn()
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_twin_snapshots_ts ON twin_snapshots(timestamp)")
        end = before if before is not None else time.time() + 1
        rows = conn.execute(
            "SELECT CAST(timestamp / ? AS INTEGER) * ? AS b, AVG(ext_temp), AVG(ext_target), AVG(bed_temp), AVG(bed_target) "
            "FROM twin_snapshots WHERE timestamp >= ? AND timestamp < ? AND print_state != 'offline' "
            "GROUP BY b ORDER BY b", (step, step, since, end)).fetchall()
    finally:
        conn.close()
    names = ("extruder", "extruder.target", "heater_bed", "heater_bed.target")
    out: Series = {n: {"t": [], "v": []} for n in names}
    for row in rows:
        for name, value in zip(names, row[1:]):
            if value is not None:
                out[name]["t"].append(float(row[0])); out[name]["v"].append(round(value, 3))
    return {k: v for k, v in out.items() if v["t"]}


def hub_series(since: float, step: float) -> Series:
    """Chamber temperature (id esp_bed_hub.chamber) and humidity from telemetry_samples."""
    cutoff = datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds")
    conn = _conn()
    try:
        has = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry_samples'").fetchone()
        if not has:
            return {}
        rows = conn.execute(
            "SELECT CAST(strftime('%s', timestamp_utc) / ? AS INTEGER) * ? AS b, AVG(chamber_temp_c), AVG(chamber_humidity_pct) "
            "FROM telemetry_samples WHERE timestamp_utc >= ? GROUP BY b ORDER BY b", (step, step, cutoff)).fetchall()
    finally:
        conn.close()
    out: Series = {"esp_bed_hub.chamber": {"t": [], "v": []}, "esp_bed_hub.humidity": {"t": [], "v": []}}
    for b, temp, hum in rows:
        if temp is not None:
            out["esp_bed_hub.chamber"]["t"].append(float(b)); out["esp_bed_hub.chamber"]["v"].append(round(temp, 2))
        if hum is not None:
            out["esp_bed_hub.humidity"]["t"].append(float(b)); out["esp_bed_hub.humidity"]["v"].append(round(hum, 2))
    return {k: v for k, v in out.items() if v["t"]}


def has_klipper_chamber(names) -> bool:
    return any(_CHAMBER_NAME.search(n.split(".")[0]) and not n.startswith("esp_bed_hub") for n in names)


def _simulator():
    import workers
    w = workers._active_worker
    return workers.is_simulator(w)


# ── GET /thermal_history ──────────────────────────────────────────────────────
@thermal_bp.route("/thermal_history", methods=["GET"])
def thermal_history():
    try:
        minutes = float(request.args.get("minutes", 20))
        max_points = int(request.args.get("max_points", DEFAULT_POINTS))
    except ValueError:
        return jsonify({"ok": False, "error": "minutes and max_points must be numbers"}), 400
    if not (minutes == minutes) or minutes < 1 or minutes > MAX_MINUTES:
        return jsonify({"ok": False, "error": f"minutes must be between 1 and {MAX_MINUTES}"}), 400
    max_points = min(max(max_points, MIN_POINTS), MAX_POINTS)

    now = time.time()
    since = now - minutes * 60
    step = max(1.0, round(minutes * 60 / max_points))
    sources: dict = {}
    series: Series = {}

    # 1. Moonraker's own store (newest ~20 min, 1 Hz)
    store: Optional[dict] = None
    sim = _simulator()
    if sim:
        sources["moonraker"] = {"ok": False, "error": "simulator running"}
    else:
        try:
            store = mu.get_json("/server/temperature_store")
            fresh = moonraker_series(store, now)
            for name, s in fresh.items():
                keep = [i for i, t in enumerate(s["t"]) if t >= since]
                t, v = bucket([s["t"][i] for i in keep], [s["v"][i] for i in keep], step)
                if t:
                    series[name] = {"t": t, "v": v}
            covered = min((s["t"][0] for s in fresh.values()), default=None)
            sources["moonraker"] = {"ok": True, "series": len(fresh), "from": covered}
        except mu.MoonrakerError as e:
            sources["moonraker"] = {"ok": False, "error": str(e)}

    # 2. twin_snapshots for the stretch before the Moonraker window (extruder / bed only)
    mr_start = min((s["t"][0] for n, s in series.items() if n in ("extruder", "heater_bed")), default=None)
    try:
        if mr_start is None or mr_start - since > step:
            old = twin_series(since, step, before=mr_start)
            for name, s in old.items():
                cur = series.get(name)
                series[name] = ({"t": s["t"] + cur["t"], "v": s["v"] + cur["v"]} if cur else s)
            sources["twin_snapshots"] = {"ok": True, "series": len(old)}
    except Exception as e:  # noqa: BLE001
        logging.info(f"thermal_history: twin_snapshots unavailable: {e}")
        sources["twin_snapshots"] = {"ok": False, "error": f"{type(e).__name__}"}

    # 3. ESP8266 hub: chamber temperature only as a fallback, humidity always
    klipper_chamber = has_klipper_chamber(series)
    try:
        hub = hub_series(since, step)
        for name, s in hub.items():
            if name == "esp_bed_hub.chamber" and klipper_chamber:
                continue
            series[name] = s
        sources["esp_bed_hub"] = {"ok": True, "series": len(hub)}
    except Exception as e:  # noqa: BLE001
        logging.info(f"thermal_history: telemetry_samples unavailable: {e}")
        sources["esp_bed_hub"] = {"ok": False, "error": f"{type(e).__name__}"}

    if not series and not sim and not sources.get("moonraker", {}).get("ok"):
        err = sources.get("moonraker", {}).get("error", "no data")
        return jsonify({"ok": False, "error": err, "moonraker": settings.moonraker_url, "sources": sources}), 502
    chamber_source = "klipper" if klipper_chamber else ("esp_bed_hub" if "esp_bed_hub.chamber" in series else None)
    return jsonify({"ok": True, "now": now, "minutes": minutes, "step_s": step, "series": series,
                    "sources": sources, "chamber_source": chamber_source})


# ── GET /sensors ──────────────────────────────────────────────────────────────
def _thin(values: list, n: int = SENSOR_HISTORY_POINTS) -> list:
    if len(values) <= n:
        return values
    stride = -(-len(values) // n)
    return values[::stride][-n:] if stride > 1 else values[-n:]


def moonraker_sensors(listing: dict, measurements: dict) -> List[dict]:
    """Normalised sensor rows from Moonraker's /server/sensors/list and /measurements results."""
    sensors = (listing or {}).get("sensors", listing or {})
    out = []
    for sid, info in sensors.items():
        if not isinstance(info, dict):
            continue
        history = {k: _thin(v) for k, v in ((measurements or {}).get(sid) or {}).items() if isinstance(v, list)}
        out.append({"id": sid, "friendly_name": info.get("friendly_name") or sid, "type": info.get("type"),
                    "values": info.get("values") or {}, "keys": list((info.get("values") or {}).keys()),   # Flask sorts dict keys; Moonraker's order pairs values with parameter_info
                    "parameter_info": info.get("parameter_info") or [],
                    "history": history, "source": "moonraker"})
    return out


def hub_sensor() -> Optional[dict]:
    """The esp_bed_hub plugin's own data shaped like a Moonraker sensor, or None when it has none."""
    try:
        from plugins.esp_bed_hub import hub
        if not hub.enabled:
            return None
        chamber = hub.chamber(max_age_s=30.0)
        if not chamber:
            return None
        rows = []
        try:
            rows = hub.store.recent(20, SENSOR_HISTORY_POINTS)
        except Exception:  # noqa: BLE001
            pass
        info = {"temperature": chamber.get("temp_c"), "humidity": chamber.get("humidity_pct"),
                "pressure": chamber.get("pressure_hpa")}
        cols = {"temperature": "chamber_temp_c", "humidity": "chamber_humidity_pct", "pressure": "chamber_pressure_hpa"}
        return {"id": "esp_bed_hub", "friendly_name": "ESP8266 bed hub", "type": "plugin",
                "values": {k: v for k, v in info.items() if v is not None},
                "keys": [k for k in ("temperature", "humidity", "pressure") if info.get(k) is not None],
                "parameter_info": [{"units": u, "field": k} for k, u in (("temperature", "°C"), ("humidity", "%"), ("pressure", "hPa"))
                                   if info.get(k) is not None],
                "history": {k: [r[c] for r in rows if r.get(c) is not None] for k, c in cols.items()
                            if info.get(k) is not None},
                "source": "esp_bed_hub"}
    except Exception as e:  # noqa: BLE001
        logging.info(f"sensors: bed hub fallback unavailable: {e}")
        return None


@thermal_bp.route("/sensors", methods=["GET"])
def sensors():
    rows: List[dict] = []
    moonraker = {"ok": True}
    try:
        listing = mu.get_json("/server/sensors/list")
        try:
            measurements = mu.get_json("/server/sensors/measurements")
        except mu.MoonrakerError:
            measurements = {}                    # sensors listed, history not available: still show the readings
        rows = moonraker_sensors(listing, measurements)
    except mu.MoonrakerError as e:
        moonraker = {"ok": False, "error": str(e)}
    ids = {r["id"].lower() for r in rows}
    if "bed_hub" not in ids:                     # the MQTT sensor is the preferred source; the plugin is the fallback
        extra = hub_sensor()
        if extra:
            rows.append(extra)
    if not rows and not moonraker["ok"]:
        return jsonify({"ok": False, "error": moonraker["error"], "moonraker": settings.moonraker_url}), 502
    return jsonify({"ok": True, "sensors": rows, "moonraker": moonraker})
