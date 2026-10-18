"""Tests for the edge computer vision pipeline and /api/v1/edge/* routes.

Verifies:
  1. In-memory state tracking (heartbeat, timeout, cooldown).
  2. Edge watchdog pseudo-confidence calculations.
  3. API heartbeat and status endpoints.
  4. Inspection alert filtering (disabled, below threshold, not printing, cooldown).
  5. Corrective actions: babystepping for Z errors, warnings for defects, and PAUSE for spaghetti/detachment.
"""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from api.server import app
from core import edge_inspector_state as state
from edge.watchdog import _pseudo_confidence, ANOMALY_AREA_THRESHOLD


class TestEdgeInspectorState(unittest.TestCase):
    def setUp(self):
        # Reset state module globals
        state._last_heartbeat_time = None
        state._last_heartbeat_info = {}
        state._last_detection = None
        state._last_alert_time = 0.0

    def test_heartbeat_recording_and_connection_status(self):
        self.assertFalse(state.is_connected())
        state.record_heartbeat({"device_id": "test-cam", "detector": "yolo"})
        self.assertTrue(state.is_connected())

        # Simulate timeout (>30s)
        state._last_heartbeat_time = time.time() - 35.0
        self.assertFalse(state.is_connected())

    def test_cooldown_logic(self):
        self.assertFalse(state.in_cooldown(60.0))
        state.mark_alert_fired()
        self.assertTrue(state.in_cooldown(60.0))
        self.assertFalse(state.in_cooldown(0.0))

    def test_detection_recording(self):
        state.record_detection(88.5, "Spaghetti Failure", "yolo")
        status = state.get_status()
        self.assertIsNotNone(status["last_detection"])
        self.assertEqual(status["last_detection"]["confidence"], 88.5)
        self.assertEqual(status["last_detection"]["label"], "Spaghetti Failure")


class TestWatchdogMath(unittest.TestCase):
    def test_pseudo_confidence(self):
        # At threshold -> 50%
        self.assertAlmostEqual(_pseudo_confidence(ANOMALY_AREA_THRESHOLD), 50.0)
        # Double threshold -> 100%
        self.assertAlmostEqual(_pseudo_confidence(ANOMALY_AREA_THRESHOLD * 2.0), 100.0)
        # Half threshold -> 25%
        self.assertAlmostEqual(_pseudo_confidence(ANOMALY_AREA_THRESHOLD * 0.5), 25.0)
        # Clamped at 0% and 100%
        self.assertEqual(_pseudo_confidence(0), 0.0)
        self.assertEqual(_pseudo_confidence(ANOMALY_AREA_THRESHOLD * 5), 100.0)


class TestEdgeApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        state._last_heartbeat_time = None
        state._last_heartbeat_info = {}
        state._last_detection = None
        state._last_alert_time = 0.0

    def test_heartbeat_endpoint(self):
        resp = self.client.post(
            "/api/v1/edge/heartbeat",
            json={"device_id": "pi-cam-1", "detector": "motion"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")
        self.assertTrue(state.is_connected())

    def test_status_endpoint(self):
        state.record_heartbeat({"device_id": "pi-cam-1", "detector": "yolo"})
        resp = self.client.get("/api/v1/edge/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["connected"])
        self.assertIn("config", data)

    def test_alert_disabled(self):
        with patch("api.routes.edge.get_edge_inspection_cfg", return_value={"enabled": False}):
            resp = self.client.post(
                "/api/v1/edge/inspection-alert",
                json={"confidence": 95.0, "label": "Spaghetti Failure", "detector": "yolo"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["status"], "disabled")

    def test_alert_below_threshold(self):
        cfg = {"enabled": True, "threshold_pct": 80.0, "cooldown_s": 60.0}
        with patch("api.routes.edge.get_edge_inspection_cfg", return_value=cfg):
            resp = self.client.post(
                "/api/v1/edge/inspection-alert",
                json={"confidence": 65.0, "label": "Spaghetti Failure", "detector": "yolo"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["status"], "below_threshold")

    def test_alert_not_printing(self):
        cfg = {"enabled": True, "threshold_pct": 70.0, "cooldown_s": 60.0}
        mock_worker = MagicMock()
        mock_worker.latest = {"print_state": "idle"}
        with patch("api.routes.edge.get_edge_inspection_cfg", return_value=cfg), \
             patch("api.server._worker", return_value=mock_worker):
            resp = self.client.post(
                "/api/v1/edge/inspection-alert",
                json={"confidence": 90.0, "label": "Spaghetti Failure", "detector": "yolo"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["status"], "not_printing")

    def test_alert_z_squish_babystep(self):
        cfg = {"enabled": True, "threshold_pct": 70.0, "cooldown_s": 60.0}
        mock_worker = MagicMock()
        mock_worker.latest = {"print_state": "printing"}
        type(mock_worker).__name__ = "SimulatedTelemetryWorker"

        with patch("api.routes.edge.get_edge_inspection_cfg", return_value=cfg), \
             patch("api.server._worker", return_value=mock_worker), \
             patch("api.routes.edge._log_action"):
            resp = self.client.post(
                "/api/v1/edge/inspection-alert",
                json={"confidence": 85.0, "label": "z_too_high", "detector": "yolo"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "executed")
            self.assertEqual(data["action"], "babystep_down")
            mock_worker.inject_gcode.assert_called_with("SET_GCODE_OFFSET Z_ADJUST=-0.01 MOVE=1")

    def test_alert_defect_warning_no_abort(self):
        cfg = {"enabled": True, "threshold_pct": 70.0, "cooldown_s": 60.0}
        mock_worker = MagicMock()
        mock_worker.latest = {"print_state": "printing"}

        with patch("api.routes.edge.get_edge_inspection_cfg", return_value=cfg), \
             patch("api.server._worker", return_value=mock_worker), \
             patch("api.routes.edge.notify"), \
             patch("api.routes.edge._log_action"):
            resp = self.client.post(
                "/api/v1/edge/inspection-alert",
                json={"confidence": 88.0, "label": "Severe Stringing", "detector": "yolo"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "warning_logged")

    def test_alert_catastrophic_spaghetti_pauses(self):
        cfg = {"enabled": True, "threshold_pct": 70.0, "cooldown_s": 60.0}
        mock_worker = MagicMock()
        mock_worker.latest = {"print_state": "printing"}
        type(mock_worker).__name__ = "SimulatedTelemetryWorker"

        with patch("api.routes.edge.get_edge_inspection_cfg", return_value=cfg), \
             patch("api.server._worker", return_value=mock_worker), \
             patch("api.routes.edge.notify"), \
             patch("api.routes.edge._log_action"):
            resp = self.client.post(
                "/api/v1/edge/inspection-alert",
                json={"confidence": 92.0, "label": "Spaghetti Failure", "detector": "yolo"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "executed")
            mock_worker.inject_gcode.assert_called_with("PAUSE")
            self.assertTrue(state.in_cooldown(60.0))


if __name__ == "__main__":
    unittest.main()
