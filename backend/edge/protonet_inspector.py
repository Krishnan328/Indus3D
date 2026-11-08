"""
edge/protonet_inspector.py
---------------------------
Tier 2 — Few-Shot Prototypical Network using ShuffleNetV2-x0.5 backbone.
Activates on Pi 5 and above (DEVICE_TIER >= 2). ~15 FPS on Pi 4B CPU.

Based on: oliverbravery/Edge-FDM-Fault-Detection
  ShuffleNetV2 + Euclidean prototype distance, 93.7% F1, 15.1 FPS on Pi 4B.

Requires: torchvision (pip install torchvision --index-url https://download.pytorch.org/whl/cpu)
Falls back to ContourInspector if torchvision is not installed.

Support set workflow:
  1. Collect 5–10 "good" frames and 5–10 "defect" frames from your printer
  2. Run: python -m edge.protonet_inspector --build-prototypes --good-dir /path/to/good \
            --bad-dir /path/to/bad
  3. Prototypes saved to edge/models/prototypes.npz automatically
  4. Inspector loads them at startup and classifies via Euclidean distance
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import numpy as np

from edge import config

logger = logging.getLogger(__name__)

_PROTO_PATH = os.path.join(config.MODELS_DIR, "prototypes.npz")
PROTOTYPES_PATH = os.environ.get("INDUS3D_PROTO_PATH", _PROTO_PATH)

# ShuffleNetV2 embedding size (torchvision shufflenet_v2_x0_5 → 1024-d)
EMBED_DIM = 1024

# Normalisation constants (ImageNet)
_MEAN = (0.485, 0.456, 0.406)
_STD  = (0.229, 0.224, 0.225)


def _try_import_torch():
    """Return (torch, transforms, shufflenet) or raise ImportError."""
    import torch
    from torchvision import transforms
    from torchvision.models import shufflenet_v2_x0_5
    return torch, transforms, shufflenet_v2_x0_5


class ProtoNetInspector:
    """
    Few-shot Prototypical Network inspector using ShuffleNetV2-x0.5.
    Device Tier: 2+ (Pi 5, Desktop).

    Falls back gracefully when torchvision is not installed.
    """

    def __init__(self, proto_path: str = PROTOTYPES_PATH):
        self._proto_path   = proto_path
        self._model        = None
        self._transform    = None
        self._proto_normal = None   # np.ndarray (1024,)
        self._proto_defect = None   # np.ndarray (1024,)
        self._available    = False
        self._torch        = None
        self._load()

    def _load(self) -> None:
        try:
            torch, transforms, shufflenet = _try_import_torch()
            self._torch = torch
        except ImportError:
            logger.warning(
                "⚠️  ProtoNetInspector: torchvision not installed. "
                "pip install torchvision --index-url https://download.pytorch.org/whl/cpu "
                "(see requirements-vision.txt). Falling back to ContourInspector."
            )
            return

        try:
            # Build feature extractor — strip final FC to get embeddings
            try:
                model = shufflenet(weights=None)
            except TypeError:
                model = shufflenet(pretrained=False)
            model.fc = torch.nn.Identity()
            model.eval()
            self._model = model

            self._transform = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=_MEAN, std=_STD),
            ])
        except Exception as e:
            logger.warning(f"⚠️  ProtoNetInspector: model initialization failed: {e}")
            return

        # Load pre-built prototypes if available
        if os.path.isfile(self._proto_path):
            try:
                data = np.load(self._proto_path)
                self._proto_normal = data["normal"]
                self._proto_defect = data["defect"]
                self._available    = True
                logger.info(f"✅ ProtoNetInspector: prototypes loaded — {self._proto_path}")
            except Exception as e:
                logger.warning(
                    f"⚠️  ProtoNetInspector: could not load prototypes from "
                    f"{self._proto_path}: {e}. "
                    "Run: python -m edge.protonet_inspector --build-prototypes"
                )
        else:
            logger.warning(
                f"⚠️  ProtoNetInspector: prototypes not found at {self._proto_path}. "
                "Run: python -m edge.protonet_inspector --build-prototypes "
                "--good-dir /path/to/good_frames --bad-dir /path/to/bad_frames"
            )

    @property
    def available(self) -> bool:
        return self._available

    def _embed(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Extract ShuffleNetV2 embedding from a BGR frame."""
        if self._model is None or self._transform is None:
            return None
        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        tensor = self._transform(rgb).unsqueeze(0)   # (1, 3, 224, 224)
        with self._torch.no_grad():
            emb = self._model(tensor).squeeze(0).numpy()   # (1024,)
        return emb

    def inspect(self, frame_bgr: np.ndarray) -> dict:
        """
        Classify frame as 'normal' or 'defect' via prototype distance.

        Returns:
            {
              "method":       "protonet_shufflenet",
              "available":    bool,
              "class":        "normal" | "defect",
              "distance":     float,   # Euclidean dist to winning prototype
              "confidence":   float,   # softmax-like [0.0, 1.0]
              "is_alert":     bool,
              "inference_ms": float,
            }
        """
        neutral = {
            "method": "protonet_shufflenet", "available": False,
            "class": "normal", "distance": 0.0,
            "confidence": 0.5, "is_alert": False, "inference_ms": 0.0,
        }

        if not self._available or frame_bgr is None:
            return neutral

        t0 = time.perf_counter()
        emb = self._embed(frame_bgr)
        if emb is None:
            return neutral

        d_normal = float(np.linalg.norm(emb - self._proto_normal))
        d_defect = float(np.linalg.norm(emb - self._proto_defect))

        # Softmax confidence: e^{-d_win} / (e^{-d_norm} + e^{-d_defect})
        e_n = np.exp(-d_normal)
        e_d = np.exp(-d_defect)
        conf = float(max(e_n, e_d) / (e_n + e_d + 1e-9))

        pred  = "normal" if d_normal <= d_defect else "defect"
        alert = pred == "defect" and conf > 0.65

        inference_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "method":       "protonet_shufflenet",
            "available":    True,
            "class":        pred,
            "distance":     round(min(d_normal, d_defect), 4),
            "confidence":   round(conf, 4),
            "is_alert":     alert,
            "inference_ms": round(inference_ms, 2),
        }

    def build_prototypes(self, good_frames: list, bad_frames: list) -> None:
        """
        Build and save class prototypes from support frame lists.

        Args:
            good_frames: list of BGR np.ndarray frames for 'normal' class
            bad_frames:  list of BGR np.ndarray frames for 'defect' class
        """
        if self._model is None:
            raise RuntimeError("torchvision not available — cannot build prototypes")
        if not good_frames or not bad_frames:
            raise ValueError("Need at least 1 good and 1 bad frame")

        logger.info(f"Building prototypes: {len(good_frames)} normal, {len(bad_frames)} defect frames")
        good_embs  = np.stack([self._embed(f) for f in good_frames])   # (N, 1024)
        bad_embs   = np.stack([self._embed(f) for f in bad_frames])

        proto_normal = good_embs.mean(axis=0)
        proto_defect = bad_embs.mean(axis=0)

        os.makedirs(os.path.dirname(self._proto_path), exist_ok=True)
        np.savez(self._proto_path, normal=proto_normal, defect=proto_defect)
        self._proto_normal = proto_normal
        self._proto_defect = proto_defect
        self._available    = True
        logger.info(f"✅ Prototypes saved to {self._proto_path}")


protonet_inspector = ProtoNetInspector()


# ── CLI entry-point for building prototypes ─────────────────────────────────
if __name__ == "__main__":
    import argparse
    import cv2

    parser = argparse.ArgumentParser(description="Build ProtoNet support prototypes")
    parser.add_argument("--build-prototypes", action="store_true", required=True)
    parser.add_argument("--good-dir", required=True, help="Directory of 'normal' frames")
    parser.add_argument("--bad-dir",  required=True, help="Directory of 'defect' frames")
    args = parser.parse_args()

    def _load_dir(d):
        frames = []
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith((".jpg", ".jpeg", ".png")):
                img = cv2.imread(os.path.join(d, fn))
                if img is not None:
                    frames.append(img)
        return frames

    insp = ProtoNetInspector()
    good = _load_dir(args.good_dir)
    bad  = _load_dir(args.bad_dir)
    print(f"Loaded {len(good)} good, {len(bad)} bad frames")
    insp.build_prototypes(good, bad)
    print(f"Done. Prototypes at: {insp._proto_path}")
