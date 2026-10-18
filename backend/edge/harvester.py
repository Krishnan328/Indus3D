"""
edge/harvester.py
-------------------
Dataset-collection tool for training a real failure-detection model (see
edge/inspector.py). Watches for a custom Klipper macro variable
(INDUS_INSPECT's snap_flag) and grabs a cropped snapshot whenever it's set
— the idea being you add a macro to printer.cfg that periodically parks
the toolhead clear of the print and sets that flag, so every collected
image is from a consistent, unobstructed angle.

Example macro to add to printer.cfg (park position and timing are yours to
tune — this is just a starting point):

    [gcode_macro INDUS_INSPECT]
    variable_snap_flag: 0
    gcode:
        SET_GCODE_VARIABLE MACRO=INDUS_INSPECT VARIABLE=snap_flag VALUE=1
        G4 P500                          ; hold briefly so the harvester catches it
        SET_GCODE_VARIABLE MACRO=INDUS_INSPECT VARIABLE=snap_flag VALUE=0

Call INDUS_INSPECT periodically from your own layer-change/timed macro if
you want automatic collection during real prints.

Collected images land in edge/dataset/raw_images/ — label them (e.g. in
Roboflow), train a YOLOv8 model, and point INDUS3D_VISION_MODEL_PATH
(edge/config.py) at the resulting best.pt for edge/inspector.py to use.

Run on a companion device, not the printer's own Pi/mainboard.
"""

import logging
import os
import time
from datetime import datetime

import cv2
import numpy as np
import requests

from edge import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

DATASET_DIR = os.path.join(os.path.dirname(__file__), "dataset", "raw_images")
os.makedirs(DATASET_DIR, exist_ok=True)

STATUS_URL = (
    f"http://{config.PRINTER_HOST}:{config.MOONRAKER_PORT}"
    f"/printer/objects/query?gcode_macro%20INDUS_INSPECT"
)

SNAP_COOLDOWN_S = 3.0  # prevents double-snapping while the macro's flag is held high


def _check_snap_flag() -> bool:
    """Reads the custom Klipper macro variable to see if the toolhead is
    currently parked and ready to be photographed."""
    try:
        res = requests.get(STATUS_URL, timeout=2)
        if res.ok:
            data = res.json()
            flag = data["result"]["status"]["gcode_macro INDUS_INSPECT"]["snap_flag"]
            return int(flag) == 1
    except Exception:
        pass
    return False


def run():
    logging.info("🌾 Indus3D Harvester starting.")
    logging.info(f"📡 Camera: {config.WEBCAM_SNAPSHOT_URL}")
    logging.info(f"📡 Klipper macro status: {STATUS_URL}")
    logging.info(f"💾 Saving to: {DATASET_DIR}")
    logging.info("⏳ Waiting for the INDUS_INSPECT snap_flag...\n")

    last_snap_time = 0.0
    images_collected = 0

    while True:
        if _check_snap_flag():
            now = time.time()
            if now - last_snap_time > SNAP_COOLDOWN_S:
                try:
                    img_resp = requests.get(config.WEBCAM_SNAPSHOT_URL, timeout=5)
                    if img_resp.status_code == 200:
                        img_array = np.frombuffer(img_resp.content, dtype=np.uint8)
                        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

                        if frame is not None:
                            h, w = frame.shape[:2]
                            cy, cx = h // 2, w // 2
                            half = 320
                            y0, y1 = max(0, cy - half), min(h, cy + half)
                            x0, x1 = max(0, cx - half), min(w, cx + half)
                            roi = frame[y0:y1, x0:x1]

                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = os.path.join(DATASET_DIR, f"indus_roi_{timestamp}.jpg")
                            cv2.imwrite(filename, roi)
                            images_collected += 1
                            logging.info(f"📸 [{timestamp}] Snapped ROI frame #{images_collected}.")

                            last_snap_time = now
                except Exception as e:
                    logging.info(f"🔴 Camera fetch error: {e}")

        # Poll fairly often so a short "parked" window isn't missed.
        time.sleep(0.2)


if __name__ == "__main__":
    run()
