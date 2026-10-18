"""
edge/inspector.py
-------------------
YOLO-based print-failure detector. Needs a model trained on real failure
images from YOUR printer/camera setup — see edge/harvester.py for the
dataset-collection half of this workflow (it saves cropped snapshots
synced to a custom Klipper macro; label them, e.g. in Roboflow, then train
a YOLOv8 model and drop the resulting best.pt where INDUS3D_VISION_MODEL_PATH
points, default edge/models/best.pt).

Until you have a trained model, run edge/watchdog.py instead — it needs no
training data and reports to the same backend endpoint, so switching later
is just running a different script, nothing else changes.

Run on a companion device, not the printer's own Pi/mainboard — see
requirements-vision.txt. Requires: pip install -r requirements-vision.txt
(opencv-python, numpy, AND ultralytics/PyTorch — this script actually
needs all three, unlike watchdog.py).
"""

import logging
import os
import time

import cv2
import numpy as np

from edge import config
from edge.reporter import report_detection, HeartbeatLoop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# Minimum confidence (0-1, YOLO's own scale) for a raw model detection to
# even be considered — separate from, and lower than, the backend's own
# threshold_pct setting (config/loader.py get_edge_inspection_cfg), which
# decides whether a reported detection actually triggers a pause. This one
# just filters obvious noise before it's even sent.
MODEL_MIN_CONFIDENCE = 0.35

# Map your trained model's class names to a human-readable label sent to
# the backend (shown in the Action Log / dashboard). Edit this once you
# know your model's actual class names — Roboflow shows them during
# training, or check model.names after loading.
CLASS_LABELS = {
    "spaghetti": "Spaghetti Failure",
    "layer_shift": "Layer Shift",
    "detached": "Part Detached from Bed",
    "z_too_high": "z_too_high",
    "z_too_low": "z_too_low",
}


def _load_model():
    if not os.path.isfile(config.MODEL_PATH):
        logging.info(f"🔴 No trained model found at {config.MODEL_PATH}.")
        logging.info("   Run edge/watchdog.py instead until you've trained one — see edge/harvester.py")
        logging.info("   to start collecting images, then set INDUS3D_VISION_MODEL_PATH once trained.")
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        logging.info("🔴 ultralytics isn't installed. On the companion device: "
                      "pip install -r requirements-vision.txt")
        return None
    logging.info(f"🧠 Loading model: {config.MODEL_PATH}")
    return YOLO(config.MODEL_PATH)


def _grab_frame():
    try:
        import requests
        resp = requests.get(config.WEBCAM_SNAPSHOT_URL, timeout=5)
        if resp.status_code != 200:
            return None
        img_array = np.frombuffer(resp.content, dtype=np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception as e:
        logging.info(f"🔴 Snapshot fetch failed: {e}")
        return None


def run():
    logging.info(f"🧠 Indus3D Inspector (YOLO) starting — device_id={config.DEVICE_ID}")
    model = _load_model()
    if model is None:
        return  # already logged why — refuse to run rather than silently doing nothing useful

    logging.info(f"📡 Camera: {config.WEBCAM_SNAPSHOT_URL}")
    logging.info(f"📡 Reporting to: {config.BACKEND_URL}")
    logging.info(f"⏱  Checking every {config.CHECK_INTERVAL_S}s")

    heartbeat = HeartbeatLoop(detector="yolo")
    heartbeat.start()

    logging.info("🟢 Watching for trained failure classes...")
    while True:
        frame = _grab_frame()
        if frame is not None:
            results = model(frame, verbose=False)
            for result in results:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    if conf < MODEL_MIN_CONFIDENCE:
                        continue
                    class_id = int(box.cls[0])
                    class_name = model.names.get(class_id, f"class_{class_id}")
                    label = CLASS_LABELS.get(class_name, class_name)
                    report_detection(conf * 100, label, "yolo")

        time.sleep(config.CHECK_INTERVAL_S)


if __name__ == "__main__":
    run()
