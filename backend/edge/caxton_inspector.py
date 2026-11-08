"""
edge/caxton_inspector.py
-------------------------
Tier 1 — CAXTON 4-head residual attention classifier for process parameter
quality assessment. Activates on Pi 4B and above (DEVICE_TIER >= 1).

Based on: Cambridge CAXTON (Lyngby et al., Nature Commun. 2022)
  cam-cambridge/caxton (ResidualAttentionNet-56 with 4 independent heads)

At inference time this module uses ONNX Runtime (onnxruntime — CPU-only,
~7 MB pip package). The model must first be exported offline from the
original PyTorch checkpoint using `scripts/export_caxton_onnx.py`.

If the ONNX file is not present:
  - A warning is logged once
  - All inspect() calls return a neutral result dict (no crash)
  - The system falls back to ContourInspector only

CAXTON head mapping (4 heads, 3 classes each: 0=low, 1=optimal, 2=high):
  Head 0 → flow rate state     (under/optimal/over-extrusion)
  Head 1 → print speed state   (too slow / optimal / too fast)
  Head 2 → z-offset state      (too close / optimal / too far)
  Head 3 → hotend temp state   (under-temp / optimal / over-temp)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import numpy as np

from edge import config

logger = logging.getLogger(__name__)

# Default ONNX path — place exported model here, or set env var
_DEFAULT_ONNX = os.path.join(config.MODELS_DIR, "caxton.onnx")
CAXTON_ONNX_PATH = os.environ.get("INDUS3D_CAXTON_ONNX", _DEFAULT_ONNX)

# CAXTON input size (RAN-56 trained on 224×224)
INPUT_H = 224
INPUT_W = 224

# ImageNet normalisation (CAXTON uses same as torchvision)
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Human-readable state labels per head
_HEAD_LABELS = [
    ["low_flow",  "optimal_flow",  "high_flow"],
    ["low_speed", "optimal_speed", "high_speed"],
    ["low_z",     "optimal_z",     "high_z"],
    ["low_temp",  "optimal_temp",  "high_temp"],
]

_HEAD_NAMES = ["flow_state", "speed_state", "z_state", "temp_state"]

# Corrective G-code hints per (head, class) — consumed by quality_controller
# Values: None = no correction needed, string = G-code fragment to consider
_CORRECTION_HINTS = {
    # head 0 — flow
    ("flow_state", "low_flow"):   "M221 S{+5}",    # increase flow 5%
    ("flow_state", "high_flow"):  "M221 S{-5}",
    # head 2 — z-offset
    ("z_state",    "low_z"):      "SET_GCODE_OFFSET Z={+0.02}",
    ("z_state",    "high_z"):     "SET_GCODE_OFFSET Z={-0.02}",
    # head 3 — temp
    ("temp_state", "low_temp"):   "M104 S{+5}",
    ("temp_state", "high_temp"):  "M104 S{-5}",
}


def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
    """Resize → RGB → normalise → NCHW float32."""
    import cv2
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (INPUT_W, INPUT_H), interpolation=cv2.INTER_LINEAR)
    arr = resized.astype(np.float32) / 255.0
    arr = (arr - _MEAN) / _STD
    return arr.transpose(2, 0, 1)[np.newaxis, ...]   # (1, 3, H, W)


class CaxtonInspector:
    """
    CAXTON ONNX-based 4-head process quality classifier.
    Device Tier: 1+ (Pi 4B and above).

    Falls back gracefully if onnxruntime or the ONNX model is absent.
    """

    def __init__(self, onnx_path: str = CAXTON_ONNX_PATH):
        self._session = None
        self._onnx_path = onnx_path
        self._warned = False
        self._load_session()

    def _load_session(self) -> None:
        if not os.path.isfile(self._onnx_path):
            logger.warning(
                f"⚠️  CaxtonInspector: ONNX model not found at {self._onnx_path}. "
                "Export it first: python scripts/export_caxton_onnx.py "
                "(see docs/SETUP.md § Vision Tier 1). Running without CAXTON."
            )
            return
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 2
            opts.intra_op_num_threads = 2
            self._session = ort.InferenceSession(
                self._onnx_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            logger.info(f"✅ CaxtonInspector: ONNX session loaded — {self._onnx_path}")
        except ImportError:
            logger.warning(
                "⚠️  CaxtonInspector: onnxruntime not installed. "
                "pip install onnxruntime  (see requirements-vision.txt). "
                "Running without CAXTON."
            )
        except Exception as e:
            logger.warning(f"⚠️  CaxtonInspector: failed to load ONNX: {e}")

    @property
    def available(self) -> bool:
        """True if ONNX session is ready for inference."""
        return self._session is not None

    def inspect(self, frame_bgr: np.ndarray) -> dict:
        """
        Run CAXTON 4-head inference on a single BGR frame.

        Returns:
            {
              "method":       "caxton_onnx",
              "available":    bool,
              "flow_state":   int (0/1/2),
              "speed_state":  int,
              "z_state":      int,
              "temp_state":   int,
              "flow_label":   str,
              "speed_label":  str,
              "z_label":      str,
              "temp_label":   str,
              "corrections":  list[str],   # G-code hints for quality_controller
              "all_optimal":  bool,
              "inference_ms": float,
            }
        """
        neutral = {
            "method": "caxton_onnx", "available": False,
            "flow_state": 1, "speed_state": 1, "z_state": 1, "temp_state": 1,
            "flow_label": "optimal_flow", "speed_label": "optimal_speed",
            "z_label": "optimal_z", "temp_label": "optimal_temp",
            "corrections": [], "all_optimal": True, "inference_ms": 0.0,
        }

        if not self.available or frame_bgr is None:
            return neutral

        t0 = time.perf_counter()
        try:
            inp = _preprocess(frame_bgr)
            input_name = self._session.get_inputs()[0].name
            raw_outputs = self._session.run(None, {input_name: inp})
        except Exception as e:
            logger.warning(f"⚠️  CaxtonInspector inference error: {e}")
            return neutral

        inference_ms = (time.perf_counter() - t0) * 1000.0

        # raw_outputs: list of 4 arrays, each shape (1, 3) — one per head
        # If model outputs a single (1, 12) tensor, reshape to 4×3
        if len(raw_outputs) == 1:
            logits = raw_outputs[0].reshape(4, 3)
        else:
            logits = np.concatenate([o for o in raw_outputs], axis=0)  # (4, 3)

        states  = np.argmax(logits, axis=1).tolist()   # [0–2] × 4
        labels  = [_HEAD_LABELS[i][s] for i, s in enumerate(states)]

        corrections = []
        for name, label in zip(_HEAD_NAMES, labels):
            hint = _CORRECTION_HINTS.get((name, label))
            if hint:
                corrections.append(hint)

        result = {
            "method":       "caxton_onnx",
            "available":    True,
            "flow_state":   states[0],
            "speed_state":  states[1],
            "z_state":      states[2],
            "temp_state":   states[3],
            "flow_label":   labels[0],
            "speed_label":  labels[1],
            "z_label":      labels[2],
            "temp_label":   labels[3],
            "corrections":  corrections,
            "all_optimal":  all(s == 1 for s in states),
            "inference_ms": round(inference_ms, 2),
        }
        return result


caxton_inspector = CaxtonInspector()
