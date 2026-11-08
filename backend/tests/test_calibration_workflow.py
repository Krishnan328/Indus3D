import importlib.util
import sqlite3
from pathlib import Path

import pytest

import workers
from api.server import app
import api.routes.calibration_workflow as workflow_routes
from workers.simulator import SimulatedTelemetryWorker


def _install_schema(path):
    migration_path = Path(__file__).resolve().parents[1] / "db" / "migrations" / "012_calibration_workflows.py"
    spec = importlib.util.spec_from_file_location("workflow_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    conn = sqlite3.connect(path)
    migration.up(conn)
    conn.close()


@pytest.fixture
def workflow_client(tmp_path, monkeypatch):
    db_path = tmp_path / "workflow.sqlite"
    _install_schema(str(db_path))
    monkeypatch.setattr(workflow_routes, "get_connection", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(workflow_routes, "_rollback_snapshot", lambda: {"profile": {"bed": {"size_x_mm": 250}}})
    monkeypatch.setattr(workers, "_active_worker", SimulatedTelemetryWorker())
    app.config["TESTING"] = True
    return app.test_client()


PRECHECK = {"operator_present": True, "bed_clear": True, "emergency_stop_accessible": True,
            "no_active_job_confirmed": True, "rollback_snapshot_confirmed": True}


def test_workflow_requires_preflight_and_generates_only_a_review_plan(workflow_client):
    rejected = workflow_client.post("/api/v1/calibration/workflow/sessions", json={"preflight": {}})
    assert rejected.status_code == 400

    created = workflow_client.post("/api/v1/calibration/workflow/sessions", json={"preflight": PRECHECK})
    assert created.status_code == 201
    workflow_id = created.json["workflow"]["id"]
    assert created.json["workflow"]["rollback"]["profile"]["bed"]["size_x_mm"] == 250

    planned = workflow_client.post(f"/api/v1/calibration/workflow/sessions/{workflow_id}/command-plan", json={"phase": "pid_hotend", "target": 200})
    assert planned.status_code == 200
    assert planned.json["plan"]["command"] == "PID_CALIBRATE HEATER=extruder TARGET=200"
    assert planned.json["plan"]["execution"] == "not performed"


def test_workflow_requires_final_evidence_before_persistence_approval(workflow_client):
    created = workflow_client.post("/api/v1/calibration/workflow/sessions", json={"preflight": PRECHECK})
    workflow_id = created.json["workflow"]["id"]
    early = workflow_client.post(f"/api/v1/calibration/workflow/sessions/{workflow_id}/persistence-approval", json={"operator": "tester"})
    assert early.status_code == 409

    validation = workflow_client.post(f"/api/v1/calibration/workflow/sessions/{workflow_id}/validation", json={
        "report_path": "/var/lib/indus3d/lab/reports/validation/report.md", "operator_reviewed_part": True,
        "predictions": {"energy_wh": 10}, "measurements": {"energy_wh": 12},
    })
    assert validation.status_code == 200
    assert validation.json["workflow"]["evidence"]["final_validation"]["analysis"]["actions_applied"] == []

    approved = workflow_client.post(f"/api/v1/calibration/workflow/sessions/{workflow_id}/persistence-approval", json={"operator": "tester"})
    assert approved.status_code == 200
    assert approved.json["workflow"]["persistence_approval"]["scope"].startswith("approval record only")


def test_legacy_direct_calibration_endpoint_is_disabled(workflow_client):
    response = workflow_client.post("/api/v1/calibration/run", json={"step": "home", "confirmed": True})
    assert response.status_code == 410
