"""
edge/reporter.py
------------------
Shared HTTP reporting for the vision-inspection edge scripts. Both
inspector.py (YOLO) and watchdog.py (motion-based) call the same two
functions here to talk to the main Indus3D backend — keeps the actual
detection logic in each script focused on detection, not HTTP plumbing,
and keeps the two scripts' reporting behavior consistent.

Deliberately does NOT talk to Moonraker directly (no pause commands, no
gcode) — that's the backend's job, via /api/v1/edge/inspection-alert. This
process only ever reports what it sees.
"""

import logging
import time

import requests

from edge import config


def send_heartbeat(detector: str) -> bool:
    try:
        res = requests.post(
            f"{config.BACKEND_URL}/api/v1/edge/heartbeat",
            json={"device_id": config.DEVICE_ID, "detector": detector},
            timeout=5,
        )
        return res.ok
    except Exception as e:
        logging.info(f"🔴 Heartbeat failed (is the Indus3D backend reachable at {config.BACKEND_URL}?): {e}")
        return False


def report_detection(confidence: float, label: str, detector: str) -> dict:
    """Reports a detection to the backend, which decides whether it's
    actionable (enabled, above threshold, not in cooldown, actually
    printing) — this script doesn't need to know any of that. Returns the
    backend's response dict, or {"status": "report_failed"} if the request
    itself couldn't be sent."""
    try:
        res = requests.post(
            f"{config.BACKEND_URL}/api/v1/edge/inspection-alert",
            json={"confidence": confidence, "label": label, "detector": detector},
            timeout=5,
        )
        data = res.json()
        logging.info(f"📡 Reported '{label}' ({confidence:.0f}%) -> backend status: {data.get('status')}")
        return data
    except Exception as e:
        logging.info(f"🔴 Could not report detection to {config.BACKEND_URL}: {e}")
        return {"status": "report_failed"}


class HeartbeatLoop:
    """Runs send_heartbeat() on its own interval in a background thread,
    so the main detection loop doesn't need to interleave timing logic for
    two unrelated things (checking frames vs. pinging the backend)."""

    def __init__(self, detector: str):
        import threading
        self._detector = detector
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            send_heartbeat(self._detector)
            time.sleep(config.HEARTBEAT_INTERVAL_S)
