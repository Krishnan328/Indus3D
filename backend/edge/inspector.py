"""
edge/inspector.py
------------------
Device-tiered vision inspection orchestrator for Indus3D.
Selects and runs the appropriate vision tier based on DEVICE_TIER.

┌─────────────┬────────────┬────────────────────────────────────────────────┐
│ Tier        │ Device     │ Method                                         │
├─────────────┼────────────┼────────────────────────────────────────────────┤
│ 0 — Contour │ All        │ OpenCV Hu Moment contour matching (< 5 ms)     │
│ 1 — CAXTON  │ Pi 4B +    │ ONNX 4-head ResidualAttentionNet (CAXTON)      │
│ 2 — ProtoNet│ Pi 5 +     │ ShuffleNetV2 few-shot prototypical network      │
│ 3 — YOLO    │ Desktop    │ YOLOv8n/s real-time (1 FPS background thread)  │
└─────────────┴────────────┴────────────────────────────────────────────────┘

All tiers degrade gracefully: if the required model/library is absent, the
tier is skipped and the next available lower tier is used. The main Flask
server process is NEVER imported here — this runs in a separate companion
process (see requirements-vision.txt).

Environment variables:
  INDUS3D_DEVICE_TIER       — override tier (0–3)
  INDUS3D_VISION_MODEL_PATH — YOLO model path (Tier 3)
  INDUS3D_CAXTON_ONNX       — CAXTON ONNX path (Tier 1)
  INDUS3D_PROTO_PATH        — ProtoNet prototypes path (Tier 2)
"""

from __future__ import annotations

import logging
import os
import time

import cv2
import numpy as np
import requests

from edge import config
from edge.reporter import report_detection, HeartbeatLoop
from edge.contour_inspector import contour_inspector
from edge.caxton_inspector import caxton_inspector
from edge.protonet_inspector import protonet_inspector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TIER = config.DEVICE_TIER

# ── Tier 3: YOLO ─────────────────────────────────────────────────────────────
#   Only loaded on Desktop / Pi 5 (TIER >= 3 for full YOLO, TIER >= 2 for nano)
#   Uses the 3DAiProject best.pt weights (YOLOv8 binary: GOOD/BAD)
MODEL_MIN_CONFIDENCE = 0.35
CLASS_LABELS = {
    "spaghetti":   "Spaghetti Failure",
    "layer_shift": "Layer Shift",
    "detached":    "Part Detached from Bed",
    "z_too_high":  "z_too_high",
    "z_too_low":   "z_too_low",
    "0":           "Defect (3DAi)",
    "bad":         "Defect (3DAi)",
    "fail":        "Print Failure",
}


def _load_yolo_model():
    """
    Load YOLO model for Tier 3. Uses 3DAiProject best.pt if available,
    falls back to env-configured path. Returns (model, path) or (None, None).
    """
    model_path = config.MODEL_PATH
    alt_path   = os.path.join(config.MODELS_DIR, "3dai_best.pt")
    if not os.path.isfile(model_path) and os.path.isfile(alt_path):
        model_path = alt_path

    if not os.path.isfile(model_path):
        logger.warning(
            f"⚠️  Tier 3 (YOLO): No model at {model_path} or {alt_path}. "
            "Skipping YOLO tier. Place best.pt or run: "
            "cp /path/to/best.pt backend/edge/models/3dai_best.pt"
        )
        return None, None
    try:
        from ultralytics import YOLO
        logger.info(f"🧠 Tier 3 (YOLO): loading {model_path}")
        return YOLO(model_path), model_path
    except ImportError:
        logger.warning(
            "⚠️  Tier 3 (YOLO): ultralytics not installed. "
            "pip install ultralytics  (see requirements-vision.txt)"
        )
        return None, None
    except Exception as e:
        logger.warning(f"⚠️  Tier 3 (YOLO): failed to load: {e}")
        return None, None


def _grab_frame():
    """Fetch a snapshot from the webcam URL. Returns BGR ndarray or None."""
    try:
        resp = requests.get(config.WEBCAM_SNAPSHOT_URL, timeout=5)
        if resp.status_code != 200:
            return None
        img_array = np.frombuffer(resp.content, dtype=np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.debug(f"Snapshot fetch failed: {e}")
        return None


def _run_tier0(frame) -> bool:
    """Tier 0: Hu Moment contour inspection. Always runs."""
    result = contour_inspector.inspect(frame)
    if result["is_alert"]:
        report_detection(
            result["anomaly_score"] * 100,
            f"Contour anomaly (score={result['anomaly_score']:.2f})",
            "contour"
        )
        return True
    return False


def _run_tier1(frame) -> bool:
    """Tier 1: CAXTON ONNX 4-head classifier."""
    if not caxton_inspector.available:
        return False
    result = caxton_inspector.inspect(frame)
    if not result.get("all_optimal", True):
        non_optimal = [
            f"{k}={v}" for k, v in result.items()
            if k.endswith("_label") and "optimal" not in str(v)
        ]
        if non_optimal:
            report_detection(
                70.0,
                f"CAXTON: {', '.join(non_optimal)}",
                "caxton"
            )
            return True
    return False


def _run_tier2(frame) -> bool:
    """Tier 2: ProtoNet ShuffleNetV2 few-shot classifier."""
    if not protonet_inspector.available:
        return False
    result = protonet_inspector.inspect(frame)
    if result["is_alert"]:
        report_detection(
            result["confidence"] * 100,
            f"ProtoNet defect (conf={result['confidence']:.2f})",
            "protonet"
        )
        return True
    return False


def _run_tier3(frame, model) -> bool:
    """Tier 3: YOLOv8 real-time detection."""
    if model is None or frame is None:
        return False
    try:
        results = model(frame, verbose=False)
        for result in results:
            for box in result.boxes:
                conf = float(box.conf[0])
                if conf < MODEL_MIN_CONFIDENCE:
                    continue
                class_id   = int(box.cls[0])
                class_name = model.names.get(class_id, f"class_{class_id}")
                label = CLASS_LABELS.get(str(class_name).lower(), str(class_name))
                report_detection(conf * 100, label, "yolo")
                return True
    except Exception as e:
        logger.warning(f"⚠️  Tier 3 YOLO inference error: {e}")
    return False


def run():
    logger.info(f"🚀 Indus3D Inspector starting — DEVICE_TIER={TIER}, device_id={config.DEVICE_ID}")
    logger.info("   Tier 0 (Contour): always active")

    # Tier 1 — CAXTON ONNX
    if TIER >= 1:
        if caxton_inspector.available:
            logger.info("   Tier 1 (CAXTON ONNX): ✅ active")
        else:
            logger.info("   Tier 1 (CAXTON ONNX): ⚠️  model missing (see docs/SETUP.md)")
    else:
        logger.info("   Tier 1 (CAXTON): skipped (device tier 0)")

    # Tier 2 — ProtoNet
    if TIER >= 2:
        if protonet_inspector.available:
            logger.info("   Tier 2 (ProtoNet): ✅ active")
        else:
            logger.info("   Tier 2 (ProtoNet): ⚠️  prototypes missing — build them first")
    else:
        logger.info(f"   Tier 2 (ProtoNet): skipped (tier {TIER} < 2)")

    # Tier 3 — YOLO
    yolo_model = None
    if TIER >= 3:
        yolo_model, yolo_path = _load_yolo_model()
        if yolo_model:
            logger.info(f"   Tier 3 (YOLO): ✅ active ({yolo_path})")
        else:
            logger.info("   Tier 3 (YOLO): ⚠️  model/ultralytics missing")
    else:
        logger.info(f"   Tier 3 (YOLO): skipped (tier {TIER} < 3)")

    logger.info(f"📡 Camera: {config.WEBCAM_SNAPSHOT_URL}")
    logger.info(f"📡 Reporting to: {config.BACKEND_URL}")
    logger.info(f"⏱  Checking every {config.CHECK_INTERVAL_S}s")

    heartbeat = HeartbeatLoop(detector=f"tier{TIER}")
    heartbeat.start()

    logger.info("🟢 Watching for print failures...")
    while True:
        frame = _grab_frame()
        if frame is not None:
            # Always run Tier 0
            _run_tier0(frame)

            # Tier 1 on Pi 4B+
            if TIER >= 1:
                _run_tier1(frame)

            # Tier 2 on Pi 5+
            if TIER >= 2:
                _run_tier2(frame)

            # Tier 3 on Desktop
            if TIER >= 3:
                _run_tier3(frame, yolo_model)

        time.sleep(config.CHECK_INTERVAL_S)


if __name__ == "__main__":
    run()
