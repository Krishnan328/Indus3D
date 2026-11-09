from unittest.mock import Mock

import pytest
from flask import Flask

from api import moonraker_util as mu
from api.routes import history, macro_prompts as prompts, settings_sync as sync
from digital_twin.state import PrinterState


@pytest.fixture
def client(monkeypatch, tmp_path):
    import db.models as models
    import workers
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "db.sqlite"))
    models.init_db()
    monkeypatch.setattr(workers, "_active_worker", None)
    monkeypatch.setattr(prompts, "auth_required", lambda: False)
    monkeypatch.setattr(mu, "run_script", Mock(return_value=Mock(ok=True)))
    monkeypatch.setattr(sync.sh, "call", Mock(side_effect=sync.sh.Unreachable("offline")))
    prompts.macro_prompt_manager.close()
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-only")
    app.register_blueprint(prompts.prompt_bp, url_prefix="/prompt")
    app.register_blueprint(history.history_bp, url_prefix="/history")
    app.register_blueprint(sync.settings_sync_bp, url_prefix="/settings")
    yield app.test_client()
    prompts.macro_prompt_manager.close()


def show_prompt():
    for line in ("// action:prompt_begin Confirm", "// action:prompt_button OK|CONFIRM", "// action:prompt_show"):
        prompts.macro_prompt_manager.feed(line)


def test_real_klipper_prompt_format(client):
    show_prompt()
    assert client.get("/prompt").json["prompt"]["title"] == "Confirm"


@pytest.mark.parametrize("failure,status", [("rejected", 422), ("network", 502)])
def test_prompt_failure_is_not_success_and_keeps_dialog(client, monkeypatch, failure, status):
    show_prompt()
    if failure == "rejected":
        monkeypatch.setattr(mu, "run_script", Mock(return_value=Mock(ok=False)))
    else:
        monkeypatch.setattr(mu, "run_script", Mock(side_effect=mu.MoonrakerError("offline")))
    response = client.post("/prompt/respond", json={"command": "CONFIRM"})
    assert response.status_code == status
    assert client.get("/prompt").json["active"]


def test_stale_prompt_button_cannot_answer_a_new_dialog(client):
    show_prompt()
    old_id = client.get("/prompt").json["prompt"]["id"]
    show_prompt()
    response = client.post("/prompt/respond", json={"command": "CONFIRM", "prompt_id": old_id})
    assert response.status_code == 409
    mu.run_script.assert_not_called()


def test_claim_is_single_use_and_does_not_close_next_dialog(client):
    show_prompt()
    manager = prompts.macro_prompt_manager
    prompt, error, status = manager.claim("CONFIRM")
    assert error is None and status == 200
    assert manager.claim("CONFIRM")[2] == 404
    show_prompt()
    next_id = manager.get_state()["id"]
    manager.restore(prompt)
    assert manager.get_state()["id"] == next_id


@pytest.mark.parametrize("body", [[], {"command": 5}, {"command": None}])
def test_prompt_rejects_wrong_payload_types(client, body):
    assert client.post("/prompt/respond", json=body).status_code == 400


def test_new_telemetry_survives_snapshot_and_can_clear():
    state = PrinterState()
    values = {"filament_used": 100, "m73_progress": 20, "m73_remaining_s": 200,
              "mmu": {"enabled": True}, "afc": {"tool": 1}, "beacon": {"temperature": 25},
              "cartographer": {"temperature": 26}}
    state.update(values)
    assert all(state.snapshot()[key] == value for key, value in values.items())
    state.update({"mmu": None, "afc": None})
    assert state.snapshot()["mmu"] is None and state.snapshot()["afc"] is None


def test_real_completion_status_in_history_and_filters(client):
    from db.models import get_connection
    conn = get_connection()
    conn.execute("INSERT INTO print_history (filename,status,print_time_seconds) VALUES ('part.gcode','complete',100)")
    conn.commit()
    conn.close()
    data = client.get("/history?status=completed").json
    assert data["stats"]["completed_count"] == 1
    assert data["stats"]["success_rate_pct"] == 100
    assert data["jobs"][0]["status"] == "completed"
    assert "part.gcode" in client.get("/history/export?status=completed").text


def test_reprint_refusal_is_reported(client, monkeypatch):
    monkeypatch.setattr(mu, "run_script", Mock(return_value=Mock(ok=False)))
    assert client.post("/history/reprint", json={"filename": "part.gcode"}).status_code == 422


@pytest.mark.parametrize("filename", ['a" G1 X10', "../part.gcode", "/part.gcode", "a\n.gcode"])
def test_reprint_never_constructs_unsafe_script(client, filename):
    assert client.post("/history/reprint", json={"filename": filename}).status_code == 400
    mu.run_script.assert_not_called()


def test_reprint_during_paused_job_sends_nothing(client, monkeypatch):
    monkeypatch.setattr("api.routes.printer._printer_is_busy", lambda: True)
    assert client.post("/history/reprint", json={"filename": "part.gcode"}).status_code == 409
    mu.run_script.assert_not_called()


def test_settings_roundtrip_uses_saved_key(client, monkeypatch):
    database = {}
    def call(method, path, body=None):
        if method == "POST":
            database[body["key"]] = body["value"]
            return {}
        assert "key=preferences" in path
        return {"value": database["preferences"]}
    monkeypatch.setattr(sync.sh, "call", call)
    assert client.post("/settings", json={"settings": {"theme": "dark"}}).json["ok"]
    assert client.get("/settings").json["settings"] == {"theme": "dark"}


@pytest.mark.parametrize("body", [[], {"settings": []}, {"settings": "not-an-object"}])
def test_invalid_settings_are_rejected(client, body):
    assert client.post("/settings", json=body).status_code == 400


def test_unavailable_settings_stores_do_not_claim_success(client, monkeypatch):
    import sqlite3
    monkeypatch.setattr(sync, "get_connection", Mock(side_effect=sqlite3.OperationalError("unavailable")))
    assert client.post("/settings", json={"settings": {"theme": "dark"}}).status_code == 503


def test_local_fallback_is_explicit(client):
    response = client.post("/settings", json={"settings": {"theme": "dark"}})
    assert response.json["source"] == "local"
    assert response.json["warning"]
    assert client.get("/settings").json["settings"] == {"theme": "dark"}


@pytest.mark.parametrize("body", [{"spool_id": True}, {"spool_id": "1"}, {"spool_id": 1, "tool_id": "1\nM112"}])
def test_invalid_spool_identifiers_are_rejected_before_io(client, monkeypatch, body):
    from api.routes.printer import printer_bp
    client.application.register_blueprint(printer_bp, url_prefix="/printer")
    sent = Mock()
    monkeypatch.setattr("api.routes.printer.requests.post", sent)
    assert client.post("/printer/spoolman/active", json=body).status_code == 400
    sent.assert_not_called()
