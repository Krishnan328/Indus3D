import importlib.util
import sqlite3
from pathlib import Path

import pytest

from api.server import app
import api.routes.lab as lab_routes


def _apply_migration(conn, name):
    migration_path = Path(__file__).resolve().parents[1] / "db" / "migrations" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.up(conn)


def _install_lab_schema(path):
    conn = sqlite3.connect(path)
    _apply_migration(conn, "010_printer_lab")
    _apply_migration(conn, "011_lab_predictions")
    conn.close()


@pytest.fixture
def lab_client(tmp_path, monkeypatch):
    db_path = tmp_path / "lab.sqlite"
    _install_lab_schema(str(db_path))
    monkeypatch.setattr(lab_routes, "get_connection", lambda: sqlite3.connect(db_path))
    app.config["TESTING"] = True
    return app.test_client()


def test_record_and_compare_lab_runs(lab_client):
    first = lab_client.post("/api/v1/lab/runs", json={
        "kind": "idle", "label": "Idle baseline", "status": "complete",
        "measurements": {"indus_cpu_pct": 1.2, "indus_memory_mb": 76.4,
                         "mainsail_cpu_pct": 0.1, "mainsail_memory_mb": 10.8},
        "artifacts": {"telemetry_capture": "/var/lib/indus3d/lab/runs/idle.jsonl"},
    })
    assert first.status_code == 201
    run_id = first.json["run"]["id"]

    baseline = lab_client.post("/api/v1/lab/baselines", json={"name": "quiet idle", "run_id": run_id})
    assert baseline.status_code == 201
    assert baseline.json["baseline"]["run"]["measurements"]["indus_cpu_pct"] == 1.2

    follow_up = lab_client.post("/api/v1/lab/runs", json={
        "kind": "idle", "label": "Idle after change", "status": "complete",
        "measurements": {"indus_cpu_pct": 1.8, "indus_memory_mb": 77.0},
    })
    assert follow_up.status_code == 201

    summary = lab_client.get("/api/v1/lab/summary")
    assert summary.status_code == 200
    compared = next(run for run in summary.json["runs"] if run["id"] == follow_up.json["run"]["id"])
    assert compared["comparison"]["baseline_name"] == "quiet idle"
    assert compared["comparison"]["metrics"]["indus_cpu_pct"]["delta_pct"] == pytest.approx(50.0)
    assert compared["budget_evaluation"]["idle"]["indus_cpu_pct"]["pass"] is True


def test_lab_rejects_unknown_measurements(lab_client):
    response = lab_client.post("/api/v1/lab/runs", json={
        "kind": "idle", "label": "Invalid", "measurements": {"temperature": 24},
    })
    assert response.status_code == 400
    assert "Unknown measurement" in response.json["error"]


def test_baseline_budget_overrides_are_used_for_evaluation(lab_client):
    run = lab_client.post("/api/v1/lab/runs", json={
        "kind": "idle", "label": "Reference", "measurements": {"indus_cpu_pct": 1.5},
    }).json["run"]
    response = lab_client.post("/api/v1/lab/baselines", json={
        "name": "strict reference", "run_id": run["id"],
        "budgets": {"idle": {"indus_cpu_pct": 1.0}},
    })
    assert response.status_code == 201
    summary = lab_client.get("/api/v1/lab/summary").json
    assert summary["active_budgets"]["idle"]["indus_cpu_pct"] == 1.0
    assert summary["runs"][0]["budget_evaluation"]["idle"]["indus_cpu_pct"]["pass"] is False


def test_prediction_reality_analysis_is_persisted_and_never_applies_actions(lab_client):
    response = lab_client.post("/api/v1/lab/runs", json={
        "kind": "print", "label": "Prediction check", "slicer_estimated_seconds": 100,
        "predictions": {"energy_wh": 10, "filament_g": 5},
        "measurements": {"actual_time_s": 130, "energy_wh": 14, "filament_g": 4.5},
    })
    assert response.status_code == 201
    analysis = response.json["run"]["analysis"]
    assert analysis["comparisons"]["elapsed_time_s"]["error_pct"] == pytest.approx(30.0)
    assert analysis["comparisons"]["energy_wh"]["within_tolerance"] is False
    assert analysis["actions_applied"] == []
    assert "never sends commands" in analysis["safety_note"]


def test_standalone_analysis_rejects_unknown_prediction(lab_client):
    response = lab_client.post("/api/v1/lab/analyze", json={
        "predictions": {"mystery": 1}, "measurements": {},
    })
    assert response.status_code == 400
    assert "Unknown prediction" in response.json["error"]
