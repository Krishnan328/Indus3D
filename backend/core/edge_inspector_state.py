"""
core/edge_inspector_state.py
------------------------------
In-memory state for the optional vision-inspection edge device (see
backend/edge/, api/routes/edge.py). Deliberately not persisted to disk —
this is live connection/session state ("is the companion device currently
reachable", "when did we last act on a detection"), not configuration.
Configuration itself lives in indus_overrides.cfg (config/loader.py's
get_edge_inspection_cfg / update_edge_inspection_cfg), same as timelapse.
"""

import time

_last_heartbeat_time = None
_last_heartbeat_info = {}
_last_detection = None      # {"confidence": float, "label": str, "detector": str, "ts": float} | None
_last_alert_time = 0.0      # for cooldown — last time a detection actually triggered the pause pipeline

# A device is considered "connected" if we've heard from it within this
# window. Heartbeats should arrive roughly every few seconds from a live
# edge script; anything longer than this and it's reasonable to assume the
# companion device is offline, crashed, or unplugged.
HEARTBEAT_TIMEOUT_S = 30.0


def record_heartbeat(info: dict):
    global _last_heartbeat_time, _last_heartbeat_info
    _last_heartbeat_time = time.time()
    _last_heartbeat_info = info or {}


def record_detection(confidence: float, label: str, detector: str):
    global _last_detection
    _last_detection = {"confidence": confidence, "label": label, "detector": detector, "ts": time.time()}


def is_connected() -> bool:
    return _last_heartbeat_time is not None and (time.time() - _last_heartbeat_time) < HEARTBEAT_TIMEOUT_S


def in_cooldown(cooldown_s: float) -> bool:
    return (time.time() - _last_alert_time) < cooldown_s


def mark_alert_fired():
    global _last_alert_time
    _last_alert_time = time.time()


def get_status() -> dict:
    return {
        "connected": is_connected(),
        "last_heartbeat": _last_heartbeat_time,
        "last_heartbeat_info": _last_heartbeat_info,
        "last_detection": _last_detection,
    }
