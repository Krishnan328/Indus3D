"""
edge/config.py
----------------
Shared configuration for the vision-inspection edge scripts (inspector.py,
watchdog.py, harvester.py). These run on a SEPARATE companion device from
the main Indus3D backend — see requirements-vision.txt and
docs/DEVELOPMENT.md for why — so everything here is read from the
environment rather than hardcoded, since "the printer's IP" and "the
Indus3D backend's IP" are both genuinely different per-install.

Set these in the companion device's shell environment, or in a .env file
in this directory loaded with `python-dotenv` if you prefer — this module
doesn't assume either, it just reads os.environ with sensible fallbacks.
"""

import os

# The printer's own Moonraker/webcam host — same machine as Klipper.
PRINTER_HOST = os.environ.get("INDUS3D_PRINTER_HOST", "127.0.0.1")
MOONRAKER_PORT = int(os.environ.get("INDUS3D_MOONRAKER_PORT", "7125"))

# Webcam stream/snapshot path — crowsnest's default. Override if yours
# differs (e.g. a second camera, a non-default crowsnest.conf).
WEBCAM_STREAM_URL = os.environ.get(
    "INDUS3D_WEBCAM_STREAM_URL", f"http://{PRINTER_HOST}/webcam/?action=stream"
)
WEBCAM_SNAPSHOT_URL = os.environ.get(
    "INDUS3D_WEBCAM_SNAPSHOT_URL", f"http://{PRINTER_HOST}/webcam/?action=snapshot"
)

# The Indus3D BACKEND's host — where the main Flask app + telemetry worker
# run. On many setups this is the same Pi as the printer (PRINTER_HOST);
# it's a separate variable because it doesn't have to be.
BACKEND_HOST = os.environ.get("INDUS3D_BACKEND_HOST", PRINTER_HOST)
BACKEND_PORT = int(os.environ.get("INDUS3D_BACKEND_PORT", "5001"))
BACKEND_URL = os.environ.get("INDUS3D_BACKEND_URL", f"http://{BACKEND_HOST}:{BACKEND_PORT}")

# A name for this device, sent with heartbeats — helps tell multiple
# companion devices apart on the /api/v1/edge/status view, if you ever run
# more than one.
DEVICE_ID = os.environ.get("INDUS3D_DEVICE_ID", "vision-1")

# How often to send a heartbeat to the backend, in seconds. Must be well
# under the backend's HEARTBEAT_TIMEOUT_S (core/edge_inspector_state.py,
# currently 30s) or the dashboard will show "offline" between heartbeats.
HEARTBEAT_INTERVAL_S = float(os.environ.get("INDUS3D_HEARTBEAT_INTERVAL_S", "10"))

# Path to a trained YOLO model (.pt). If this file doesn't exist,
# inspector.py falls back to the motion-based detector automatically
# rather than failing outright — see edge/inspector.py.
MODEL_PATH = os.environ.get("INDUS3D_VISION_MODEL_PATH", os.path.join(os.path.dirname(__file__), "models", "best.pt"))

# How often to run a detection pass, in seconds. Inference (especially
# YOLO) is CPU-heavy — don't run this at camera framerate.
CHECK_INTERVAL_S = float(os.environ.get("INDUS3D_VISION_CHECK_INTERVAL_S", "15"))
