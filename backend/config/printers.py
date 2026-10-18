"""
config/printers.py
-------------------
Registry of known printer connections, for multi-printer *switching* — this
is Mainsail's actual model (one active Moonraker connection at a time,
switchable from a saved list), not N simultaneous live connections. Indus3D
runs a single TelemetryWorker against a single Moonraker instance; switching
means stopping that worker, pointing settings at a different host/port, and
starting a fresh one — see workers/manager.py for the orchestration.

Persisted to printers.json alongside indus_overrides.cfg / printer_profile.json.
"""

import json
import logging
import os
import uuid
from typing import Optional

from config.settings import settings

_HERE = os.path.dirname(os.path.abspath(__file__))
_PRINTERS_PATH = os.path.join(_HERE, "printers.json")

LOCAL_ID = "local"


def _default_registry() -> dict:
    # Seed with whatever .env / current settings already point at, so a
    # fresh install always has at least one entry — the printer it's
    # already talking to — instead of an empty, unusable list.
    return {
        "active": LOCAL_ID,
        "printers": [
            {"id": LOCAL_ID, "name": "Local Printer",
             "host": settings.MOONRAKER_HOST, "port": settings.MOONRAKER_PORT,
             "last_mesh_calibration": None},
        ],
    }


def _load() -> dict:
    if os.path.isfile(_PRINTERS_PATH):
        try:
            with open(_PRINTERS_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("printers"), list) and data.get("active"):
                return data
        except Exception as e:
            logging.info(f"🔴 printers.json unreadable, resetting: {e}")
    data = _default_registry()
    _save(data)
    return data


def _save(data: dict) -> None:
    tmp = _PRINTERS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _PRINTERS_PATH)  # atomic — never leaves a half-written file


def list_printers() -> dict:
    data = _load()
    return {"active": data["active"], "printers": data["printers"]}


def get_printer(printer_id: str) -> Optional[dict]:
    data = _load()
    return next((p for p in data["printers"] if p["id"] == printer_id), None)


def get_active_printer() -> Optional[dict]:
    data = _load()
    return next((p for p in data["printers"] if p["id"] == data["active"]), None)


def add_printer(name: str, host: str, port) -> dict:
    name = (name or "").strip()
    host = (host or "").strip()
    if not name:
        raise ValueError("name is required")
    if not host:
        raise ValueError("host is required")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("port must be a number")
    if not (1 <= port <= 65535):
        raise ValueError("port must be between 1 and 65535")

    data = _load()
    if any(p["host"] == host and p["port"] == port for p in data["printers"]):
        raise ValueError(f"{host}:{port} is already registered")

    new_id = uuid.uuid4().hex[:8]
    data["printers"].append({"id": new_id, "name": name, "host": host, "port": port, "last_mesh_calibration": None})
    _save(data)
    return list_printers()


def remove_printer(printer_id: str) -> dict:
    data = _load()
    if printer_id == data["active"]:
        raise ValueError("Cannot remove the active printer — switch to another one first")
    before = len(data["printers"])
    data["printers"] = [p for p in data["printers"] if p["id"] != printer_id]
    if len(data["printers"]) == before:
        raise ValueError("Unknown printer id")
    _save(data)
    return list_printers()


def mark_active(printer_id: str) -> dict:
    """Record which printer is active. Does NOT itself switch the live
    connection — that's workers.manager.switch_active_printer(), which calls
    this after the switch actually succeeds, so the persisted 'active' id
    never points at a printer the backend isn't really connected to."""
    data = _load()
    if not any(p["id"] == printer_id for p in data["printers"]):
        raise ValueError("Unknown printer id")
    data["active"] = printer_id
    _save(data)
    return list_printers()


def set_last_calibration(printer_id: str, iso_timestamp: str) -> dict:
    """Record when this printer's bed mesh was last (re)calibrated. Stored
    per-printer here rather than in browser localStorage — Klipper's own
    bed_mesh status has no timestamp field, and a localStorage-only date
    would show the wrong printer's calibration age after switching active
    printers (see workers/manager.py)."""
    data = _load()
    found = False
    for p in data["printers"]:
        if p["id"] == printer_id:
            p["last_mesh_calibration"] = iso_timestamp
            found = True
            break
    if not found:
        raise ValueError("Unknown printer id")
    _save(data)
    return list_printers()
