"""
tests/test_history_routes.py
----------------------------
Unit tests for the Print History API (routes/history.py).
"""

from unittest import mock
import pytest
from db.models import get_connection, init_db


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM print_history")
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    from api.server import app
    return app.test_client()


def _insert_job(filename="benchy.gcode", status="completed", print_time_seconds=3600.0,
                filament_used_g=45.0, power_used_wh=150.0, cost_usd=1.50):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO print_history (filename, status, print_time_seconds, filament_used_g, power_used_wh, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (filename, status, print_time_seconds, filament_used_g, power_used_wh, cost_usd))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id


def test_get_history_empty(client):
    r = client.get("/api/v1/history")
    assert r.status_code == 200
    data = r.get_json()
    assert data["jobs"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["stats"]["total_jobs"] == 0
    assert data["stats"]["success_rate_pct"] == 0.0


def test_get_history_with_records_and_stats(client):
    _insert_job("cube.gcode", "completed", 1800.0, 20.0, 50.0, 0.50)
    _insert_job("benchy.gcode", "completed", 3600.0, 40.0, 100.0, 1.00)
    _insert_job("failed.gcode", "error", 600.0, 5.0, 20.0, 0.20)

    r = client.get("/api/v1/history")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 3
    assert len(data["jobs"]) == 3
    # Ordered DESC by id
    assert data["jobs"][0]["filename"] == "failed.gcode"
    assert data["jobs"][0]["status"] == "error"
    assert "10m" in data["jobs"][0]["print_time_formatted"]

    stats = data["stats"]
    assert stats["total_jobs"] == 3
    assert stats["completed_count"] == 2
    assert stats["error_count"] == 1
    assert stats["success_rate_pct"] == 66.7
    assert stats["total_seconds"] == 6000.0
    assert stats["total_filament_g"] == 65.0


def test_get_history_filtering_and_search(client):
    _insert_job("voron_cube.gcode", "completed")
    _insert_job("voron_dragon.gcode", "cancelled")
    _insert_job("benchy.gcode", "completed")

    # Filter by status
    r = client.get("/api/v1/history?status=cancelled")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 1
    assert data["jobs"][0]["filename"] == "voron_dragon.gcode"

    # Search by filename
    r = client.get("/api/v1/history?search=voron")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 2
    filenames = [j["filename"] for j in data["jobs"]]
    assert "voron_cube.gcode" in filenames
    assert "voron_dragon.gcode" in filenames


def test_get_history_pagination(client):
    for i in range(5):
        _insert_job(f"job_{i}.gcode", "completed")

    r = client.get("/api/v1/history?page=1&limit=2")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 5
    assert len(data["jobs"]) == 2
    assert data["pages"] == 3
    assert data["page"] == 1

    r2 = client.get("/api/v1/history?page=3&limit=2")
    assert r2.status_code == 200
    data2 = r2.get_json()
    assert len(data2["jobs"]) == 1


def test_export_csv(client):
    _insert_job("gear.gcode", "completed", 1200.0, 15.5, 45.0, 0.40)
    _insert_job("bracket.gcode", "cancelled", 300.0, 4.0, 10.0, 0.10)

    r = client.get("/api/v1/history/export")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/csv")
    assert "attachment; filename=indus3d_print_history.csv" in r.headers["Content-Disposition"]

    text = r.get_data(as_text=True)
    lines = text.strip().split("\r\n" if "\r\n" in text else "\n")
    assert len(lines) == 3  # header + 2 jobs
    assert "filename" in lines[0]
    assert "print_time_formatted" in lines[0]
    assert "bracket.gcode" in lines[1]
    assert "gear.gcode" in lines[2]


def test_reprint_job_by_id_and_filename(client):
    jid = _insert_job("reprint_me.gcode", "completed")

    with mock.patch("api.moonraker_util.run_script") as mock_run:
        # Reprint by id
        r = client.post("/api/v1/history/reprint", json={"id": jid})
        assert r.status_code == 200
        assert r.get_json()["filename"] == "reprint_me.gcode"
        mock_run.assert_called_with('SDCARD_PRINT_FILE FILENAME="reprint_me.gcode"', timeout=10)

    with mock.patch("api.moonraker_util.run_script") as mock_run:
        # Reprint by filename
        r = client.post("/api/v1/history/reprint", json={"filename": "direct.gcode"})
        assert r.status_code == 200
        mock_run.assert_called_with('SDCARD_PRINT_FILE FILENAME="direct.gcode"', timeout=10)


def test_reprint_rejects_malformed_filename(client):
    r = client.post("/api/v1/history/reprint", json={"filename": "bad\nfile.gcode"})
    assert r.status_code == 400


def test_delete_job(client):
    jid = _insert_job("to_delete.gcode", "error")

    r = client.delete(f"/api/v1/history/{jid}")
    assert r.status_code == 200
    assert r.get_json()["deleted_id"] == jid

    # Second delete returns 404
    r2 = client.delete(f"/api/v1/history/{jid}")
    assert r2.status_code == 404
