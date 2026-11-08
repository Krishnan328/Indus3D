"""
tests/test_notifications.py
----------------------------
Unit tests for the rich outbound notification module.
"""

from unittest.mock import patch
from core.notifications import (
    notify,
    notify_print_started,
    notify_print_completed,
    notify_print_halted,
    notify_critical_alert,
    notify_object_excluded,
    pop_ui_notifications,
)


def test_ui_toast_queue():
    pop_ui_notifications()  # Clear queue
    outcome = notify("Test notification message")
    assert "ui" in outcome["sent"]

    toasts = pop_ui_notifications()
    assert len(toasts) >= 1
    assert "Test notification message" in toasts[-1]["message"]


@patch("core.notifications.requests.post")
def test_rich_print_started(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_print_started(
        filename="benchy.gcode",
        bed_temp=60.0,
        ext_temp=210.0,
        spool_name="PolyLite PLA",
    )
    assert "ui" in outcome["sent"]


@patch("core.notifications.requests.post")
def test_rich_print_completed(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_print_completed(
        filename="calicat.gcode",
        duration_s=850.0,
        energy_wh=18.4,
        cost_usd=0.45,
        filament_g=9.2,
        excursions=0,
    )
    assert "ui" in outcome["sent"]


@patch("core.notifications.requests.post")
def test_rich_print_halted(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_print_halted(
        filename="bracket.gcode",
        status="error",
        reason="Lost communication with MCU",
    )
    assert "ui" in outcome["sent"]


@patch("core.notifications.requests.post")
def test_object_excluded(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_object_excluded(
        object_name="Part_B_Bracket",
        reason="Nozzle collision / vibration spike",
    )
    assert "ui" in outcome["sent"]
