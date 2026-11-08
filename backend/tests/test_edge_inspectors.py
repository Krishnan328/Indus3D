"""
tests/test_edge_inspectors.py
-------------------------------
Unit tests for multi-tier edge vision inspectors:
- config._autodetect_tier()
- ContourInspector (Tier 0)
- CaxtonInspector (Tier 1 fallback)
- ProtoNetInspector (Tier 2 fallback)
- Inspector orchestrator
"""

import numpy as np
import pytest

from edge import config
from edge.contour_inspector import ContourInspector, contour_inspector
from edge.caxton_inspector import CaxtonInspector, caxton_inspector
from edge.protonet_inspector import ProtoNetInspector, protonet_inspector


class TestDeviceTierConfig:
    def test_autodetect_tier_range(self):
        tier = config._autodetect_tier()
        assert isinstance(tier, int)
        assert 0 <= tier <= 3

    def test_device_tier_loaded(self):
        assert isinstance(config.DEVICE_TIER, int)
        assert 0 <= config.DEVICE_TIER <= 3


class TestContourInspector:
    def test_empty_frame(self):
        res = contour_inspector.inspect(None)
        assert res["method"] == "hu_moments"
        assert res["anomaly_score"] == 0.0
        assert not res["is_alert"]

    def test_synthetic_frame(self):
        # Create a simple synthetic image with a centered white rectangle
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        img[50:250, 50:250] = 255
        res = contour_inspector.inspect(img)
        assert res["method"] == "hu_moments"
        assert isinstance(res["anomaly_score"], float)
        assert 0.0 <= res["anomaly_score"] <= 1.0
        assert isinstance(res["is_alert"], bool)
        assert res["inference_ms"] >= 0.0


class TestCaxtonInspector:
    def test_graceful_missing_model(self):
        # Pointing to non-existent onnx file
        dummy = CaxtonInspector(onnx_path="/tmp/non_existent_caxton.onnx")
        assert not dummy.available
        res = dummy.inspect(np.zeros((224, 224, 3), dtype=np.uint8))
        assert res["method"] == "caxton_onnx"
        assert not res["available"]
        assert res["all_optimal"] is True
        assert res["corrections"] == []


class TestProtoNetInspector:
    def test_graceful_missing_prototypes(self):
        # Pointing to non-existent prototype file
        dummy = ProtoNetInspector(proto_path="/tmp/non_existent_proto.npz")
        assert not dummy.available
        res = dummy.inspect(np.zeros((224, 224, 3), dtype=np.uint8))
        assert res["method"] == "protonet_shufflenet"
        assert not res["available"]
        assert res["class"] == "normal"
        assert not res["is_alert"]
