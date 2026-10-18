"""
edge/watchdog.py
------------------
Motion-based print-failure detector — no trained model needed, works out
of the box. Watches the webcam for a sustained blob of unexpected motion
(a classic signature of a detached print dragging around, or a spaghetti
failure) using OpenCV background subtraction, and reports detections to
the main Indus3D backend, which decides whether to actually pause (see
api/routes/edge.py).

This is the "day one" detector — reasonable and immediately useful, but
cruder than a trained model (edge/inspector.py). Run this until you've
collected enough images with edge/harvester.py and trained a real model,
then switch.

Run on a companion device, not the printer's own Pi/mainboard — see
requirements-vision.txt. Requires: pip install -r requirements-vision.txt
(only opencv-python and numpy are actually used here; ultralytics/PyTorch
are not needed for this script).
"""

import logging
import time

import cv2
import numpy as np

from edge import config
from edge.reporter import report_detection, HeartbeatLoop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# How many pixels of moving-blob area constitutes an anomaly. Tune this for
# your camera's distance/resolution/framing — there's no universal value.
ANOMALY_AREA_THRESHOLD = 15000

# Consecutive anomalous frames required before actually reporting — a
# single glitchy frame (camera noise, someone walking past) shouldn't
# trigger a pause; sustained motion for several seconds should.
ANOMALY_FRAMES_TO_TRIGGER = 30


def _pseudo_confidence(area: float) -> float:
    """Confidence isn't a real probability for a motion-based detector the
    way it is for a trained model — this maps "how far past the
    threshold" to a 0-100 scale so the backend's confidence-threshold
    setting still means something consistent between this script and
    inspector.py."""
    ratio = area / ANOMALY_AREA_THRESHOLD
    return float(max(0.0, min(100.0, 50.0 + (ratio - 1.0) * 50.0)))


def run(test_mode: bool = False):
    logging.info(f"👁️  Indus3D Watchdog (motion-based) starting — device_id={config.DEVICE_ID}")
    logging.info(f"📡 Camera: {config.WEBCAM_STREAM_URL}")
    logging.info(f"📡 Reporting to: {config.BACKEND_URL}")

    heartbeat = HeartbeatLoop(detector="motion")
    heartbeat.start()

    cam_source = (
        int(config.WEBCAM_STREAM_URL)
        if str(config.WEBCAM_STREAM_URL).isdigit()
        else config.WEBCAM_STREAM_URL
    )
    cap = cv2.VideoCapture(cam_source)
    if not cap.isOpened():
        logging.info("🔴 Cannot connect to the webcam stream. Check INDUS3D_WEBCAM_STREAM_URL / network.")
        heartbeat.stop()
        return False

    # MOG2 background subtractor: learns what the static scene (bed, frame)
    # looks like and isolates only the pixels that are actually moving.
    back_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=False)

    anomaly_counter = 0
    last_report_time = 0.0
    REPORT_COOLDOWN_S = 5.0  # don't hammer the backend every frame while sustained motion continues
    frames_processed = 0

    logging.info("🟢 Watching for anomalous motion...")
    while True:
        ret, frame = cap.read()
        if not ret:
            if test_mode:
                break
            logging.info("⚠️  Stream dropped — reconnecting in 2s...")
            time.sleep(2)
            cap = cv2.VideoCapture(cam_source)
            continue

        frame = cv2.resize(frame, (640, 480))
        fg_mask = back_sub.apply(frame)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        total_moving_area = sum(cv2.contourArea(c) for c in contours if cv2.contourArea(c) > 500)

        if total_moving_area > ANOMALY_AREA_THRESHOLD:
            anomaly_counter += 1
        elif anomaly_counter > 0:
            anomaly_counter -= 1

        if anomaly_counter >= ANOMALY_FRAMES_TO_TRIGGER:
            now = time.time()
            if now - last_report_time > REPORT_COOLDOWN_S:
                confidence = _pseudo_confidence(total_moving_area)
                report_detection(confidence, "sustained_motion_anomaly", "motion")
                last_report_time = now
            anomaly_counter = 0  # reset so we require another full run-up before reporting again

        frames_processed += 1
        if test_mode and frames_processed >= 5:
            heartbeat.stop()
            cap.release()
            return True

        time.sleep(0.05)  # ~20fps processing cap — plenty for this, keeps CPU reasonable


if __name__ == "__main__":
    import sys
    test = "--test" in sys.argv
    run(test_mode=test)
