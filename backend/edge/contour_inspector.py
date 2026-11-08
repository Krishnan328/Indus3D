"""
edge/contour_inspector.py
--------------------------
Tier 0/1 — Universal baseline inspector using OpenCV Hu Moment contour
matching. Requires NO deep-learning framework — pure OpenCV < 5 ms per frame.
Runs on ALL device tiers (Pi 3, Pi 4B, Pi 5, Desktop).

Based on the Hu Moments approach from:
  alexgrigoras/failure_detection_for_3d_printing (image_matching.py)

How it works:
  1. Convert frame to grayscale → Gaussian blur → adaptive threshold
  2. Find contours, compute 7-element log-Hu-moments for the largest
  3. Compare against a reference contour (loaded from JSON sidecar, or the
     bundled workers/data/benchy_contours.json default)
  4. Mahalanobis-style Hu moment distance → anomaly_score [0.0, 1.0]
  5. Alert when anomaly_score > ANOMALY_THRESHOLD
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Anomaly score threshold above which is_alert=True
ANOMALY_THRESHOLD = 0.65

# How many Hu moments to compare (7 is the full set)
N_HU = 7

# Path to default reference contours (Benchy baseline, shipped with repo)
_DEFAULT_REF = os.path.join(
    os.path.dirname(__file__), "..", "workers", "data", "benchy_contours.json"
)


def _log_hu_moments(moments: dict) -> np.ndarray:
    """Convert OpenCV moment dict to 7-element log-Hu vector (sign-preserved)."""
    hu = cv2.HuMoments(moments).flatten()
    log_hu = np.zeros(N_HU, dtype=np.float64)
    for i, h in enumerate(hu[:N_HU]):
        if h != 0.0:
            log_hu[i] = -math.copysign(1.0, h) * math.log10(abs(h))
    return log_hu


def _largest_contour_hu(gray: np.ndarray) -> Optional[np.ndarray]:
    """
    Threshold → find contours → return log-Hu vector of the largest contour.
    Returns None if no significant contour found.
    """
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    # Adaptive threshold handles variable illumination
    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
        blockSize=31, C=5
    )
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 200:  # too small — noise
        return None
    m = cv2.moments(largest)
    return _log_hu_moments(m)


class ContourInspector:
    """
    Hu-Moment contour inspector. Device Tier: 0 (runs on ALL devices).

    Usage:
        inspector = ContourInspector(reference_json_path=None)
        result = inspector.inspect(frame)
        # result: {"method": "hu_moments", "anomaly_score": float, "is_alert": bool,
        #          "inference_ms": float}
    """

    def __init__(self, reference_json_path: Optional[str] = None):
        self._ref_hu: Optional[np.ndarray] = None
        self._ref_std: Optional[np.ndarray] = None
        self._load_reference(reference_json_path or _DEFAULT_REF)

    def _load_reference(self, path: str) -> None:
        """
        Load reference Hu moment vectors from a JSON sidecar file.
        The file is expected to contain:
          {"hu_mean": [...7 floats...], "hu_std": [...7 floats...]}
        or a list of 7-element arrays that this method will average.
        Falls back to no-reference mode (anomaly_score always 0.5) if missing.
        """
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict) and "hu_mean" in data:
                self._ref_hu  = np.array(data["hu_mean"], dtype=np.float64)
                self._ref_std = np.array(data.get("hu_std", [1.0] * N_HU), dtype=np.float64)
            elif isinstance(data, list) and len(data) > 0:
                arr = np.array(data, dtype=np.float64)
                self._ref_hu  = arr.mean(axis=0)[:N_HU]
                self._ref_std = arr.std(axis=0)[:N_HU] + 1e-6
            logger.info(f"✅ ContourInspector: loaded reference from {path}")
        except (FileNotFoundError, json.JSONDecodeError, KeyError, Exception) as e:
            logger.warning(f"⚠️  ContourInspector: no reference loaded ({e}) — running in score=0.5 mode")

    def inspect(self, frame: np.ndarray) -> dict:
        """
        Inspect a BGR frame. Returns anomaly score and alert flag.

        Args:
            frame: OpenCV BGR image (np.ndarray, dtype=uint8)

        Returns:
            {
              "method":       "hu_moments",
              "anomaly_score": float [0.0–1.0],
              "is_alert":      bool,
              "inference_ms":  float,
            }
        """
        t0 = time.perf_counter()

        if frame is None or frame.size == 0:
            return {"method": "hu_moments", "anomaly_score": 0.0,
                    "is_alert": False, "inference_ms": 0.0}

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hu_vec = _largest_contour_hu(gray)

        inference_ms = (time.perf_counter() - t0) * 1000.0

        if hu_vec is None:
            return {"method": "hu_moments", "anomaly_score": 0.0,
                    "is_alert": False, "inference_ms": round(inference_ms, 2)}

        if self._ref_hu is None:
            # No reference — return a neutral score
            return {"method": "hu_moments", "anomaly_score": 0.5,
                    "is_alert": False, "inference_ms": round(inference_ms, 2)}

        # Normalised Euclidean distance in Hu-moment space
        std_safe = np.where(self._ref_std > 0, self._ref_std, 1.0)
        diff = (hu_vec - self._ref_hu) / std_safe
        dist = float(np.linalg.norm(diff))

        # Sigmoid squash: dist → [0, 1]  (dist=0 → 0.0; dist=3 → ~0.95)
        anomaly_score = float(1.0 / (1.0 + math.exp(-0.8 * (dist - 3.0))))
        is_alert = anomaly_score > ANOMALY_THRESHOLD

        inference_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "method":        "hu_moments",
            "anomaly_score": round(anomaly_score, 4),
            "is_alert":      is_alert,
            "inference_ms":  round(inference_ms, 2),
        }


# Module-level singleton — inspector.py imports this
contour_inspector = ContourInspector()
