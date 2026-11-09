"""
tests/test_macro_prompts.py
---------------------------
Unit tests for the Klipper action:prompt_* protocol parser, state manager, and endpoints.
"""

from unittest import mock
import pytest

from api.routes.macro_prompts import (
    parse_prompt_line,
    MacroPromptManager,
    macro_prompt_manager,
)


# ── Parser Tests ─────────────────────────────────────────────────────────────

def test_parse_prompt_line_non_prompt():
    assert parse_prompt_line("ok") is None
    assert parse_prompt_line("// Klipper state: ready") is None
    assert parse_prompt_line(123) is None
    assert parse_prompt_line("") is None


def test_parse_prompt_line_begin():
    res = parse_prompt_line("action:prompt_begin Confirm filament load?")
    assert res == {"type": "begin", "payload": "Confirm filament load?"}


def test_parse_prompt_line_text():
    res = parse_prompt_line("action:prompt_text Is the filament purged?")
    assert res == {"type": "text", "payload": "Is the filament purged?"}


def test_parse_prompt_line_buttons():
    # Normal button
    b1 = parse_prompt_line("action:prompt_button Confirm|LOAD_CONFIRM")
    assert b1 == {
        "type": "button",
        "payload": {"label": "Confirm", "command": "LOAD_CONFIRM", "style": "normal"},
    }

    # Warning button
    b2 = parse_prompt_line("action:prompt_button Skip Purge|M117 Skipped|warning")
    assert b2 == {
        "type": "button",
        "payload": {"label": "Skip Purge", "command": "M117 Skipped", "style": "warning"},
    }

    # Error button
    b3 = parse_prompt_line("action:prompt_button Abort|CANCEL_PRINT|error")
    assert b3 == {
        "type": "button",
        "payload": {"label": "Abort", "command": "CANCEL_PRINT", "style": "error"},
    }

    # Unknown style defaults to normal
    b4 = parse_prompt_line("action:prompt_button Test|TEST_CMD|foobar")
    assert b4["payload"]["style"] == "normal"


def test_parse_prompt_line_footer_button():
    res = parse_prompt_line("action:prompt_footer_button E-Stop|M112|error")
    assert res == {
        "type": "footer_button",
        "payload": {"label": "E-Stop", "command": "M112", "style": "error"},
    }


def test_parse_prompt_line_show_and_end():
    assert parse_prompt_line("action:prompt_show") == {"type": "show", "payload": None}
    assert parse_prompt_line("action:prompt_end") == {"type": "end", "payload": None}


# ── Manager Tests ────────────────────────────────────────────────────────────

def test_macro_prompt_manager_lifecycle():
    mgr = MacroPromptManager()
    assert mgr.get_state() is None

    # Feed sequence before show: not active yet
    mgr.feed("action:prompt_begin Change Filament")
    mgr.feed("action:prompt_text Please insert new filament and purge.")
    mgr.feed("action:prompt_button Purge More|PURGE_MORE|warning")
    mgr.feed("action:prompt_button Ready|RESUME|normal")
    mgr.feed("action:prompt_footer_button Abort|CANCEL_PRINT|error")
    assert mgr.get_state() is None

    # Show: now active
    mgr.feed("action:prompt_show")
    state = mgr.get_state()
    assert state is not None
    assert state["active"] is True
    assert state["title"] == "Change Filament"
    assert state["text"] == ["Please insert new filament and purge."]
    assert len(state["buttons"]) == 2
    assert state["buttons"][0]["command"] == "PURGE_MORE"
    assert len(state["footer_buttons"]) == 1
    assert state["footer_buttons"][0]["command"] == "CANCEL_PRINT"

    assert mgr.get_valid_commands() == ["PURGE_MORE", "RESUME", "CANCEL_PRINT"]

    # End clears prompt
    mgr.feed("action:prompt_end")
    assert mgr.get_state() is None


def test_macro_prompt_manager_feed_dict():
    mgr = MacroPromptManager()
    mgr.feed({"text": "action:prompt_begin Quick Dialog"})
    mgr.feed({"text": "action:prompt_button OK|M117 OK"})
    mgr.feed({"text": "action:prompt_show"})
    assert mgr.get_state() is not None
    assert mgr.get_state()["title"] == "Quick Dialog"


# ── Route Integration Tests ──────────────────────────────────────────────────

@pytest.fixture
def client():
    from api.server import app
    macro_prompt_manager.close()
    yield app.test_client()
    macro_prompt_manager.close()


def test_get_prompt_inactive(client):
    r = client.get("/api/v1/printer/prompt")
    assert r.status_code == 200
    data = r.get_json()
    assert data["active"] is False
    assert data["prompt"] is None


def test_get_prompt_active(client):
    macro_prompt_manager.feed("action:prompt_begin Title")
    macro_prompt_manager.feed("action:prompt_text Line 1")
    macro_prompt_manager.feed("action:prompt_button OK|M117 OK")
    macro_prompt_manager.feed("action:prompt_show")

    r = client.get("/api/v1/printer/prompt")
    assert r.status_code == 200
    data = r.get_json()
    assert data["active"] is True
    assert data["prompt"]["title"] == "Title"
    assert data["prompt"]["buttons"][0]["command"] == "M117 OK"


def test_respond_to_prompt_success(client):
    macro_prompt_manager.feed("action:prompt_begin Prompt")
    macro_prompt_manager.feed("action:prompt_button Yes|CONFIRM_CMD")
    macro_prompt_manager.feed("action:prompt_show")

    with mock.patch("api.moonraker_util.run_script") as mock_run:
        r = client.post("/api/v1/printer/prompt/respond", json={"command": "CONFIRM_CMD"})
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"
        mock_run.assert_called_once_with("CONFIRM_CMD")

    # Prompt should be closed after responding
    assert macro_prompt_manager.get_state() is None


def test_respond_to_prompt_invalid_command(client):
    macro_prompt_manager.feed("action:prompt_begin Prompt")
    macro_prompt_manager.feed("action:prompt_button Yes|CONFIRM_CMD")
    macro_prompt_manager.feed("action:prompt_show")

    r = client.post("/api/v1/printer/prompt/respond", json={"command": "MALICIOUS_CMD"})
    assert r.status_code == 400
    assert "Unknown command" in r.get_json()["error"]
    assert macro_prompt_manager.get_state() is not None


def test_respond_no_active_prompt(client):
    r = client.post("/api/v1/printer/prompt/respond", json={"command": "CONFIRM_CMD"})
    assert r.status_code == 404


def test_dismiss_prompt(client):
    macro_prompt_manager.feed("action:prompt_begin Prompt")
    macro_prompt_manager.feed("action:prompt_show")
    assert macro_prompt_manager.get_state() is not None

    r = client.delete("/api/v1/printer/prompt")
    assert r.status_code == 200
    assert macro_prompt_manager.get_state() is None
