"""Rate-selection tests for the live telemetry worker.

The print controller must retain its full sampling rate during a print, while
an idle or unavailable printer should not consume the same CPU budget.
"""

from workers.telemetry_worker import POLL_HZ, TelemetryWorker
from config.settings import settings


def test_active_print_keeps_full_rate():
    worker = TelemetryWorker()
    worker._moonraker_online = True
    worker._klippy_connected = True
    worker._klippy_state = "ready"
    worker._klipper_data = {"print_stats": {"state": "printing"}}

    assert worker._target_tick_hz() == POLL_HZ


def test_idle_printer_uses_lower_rate():
    worker = TelemetryWorker()
    worker._moonraker_online = True
    worker._klippy_connected = True
    worker._klippy_state = "ready"
    worker._klipper_data = {"print_stats": {"state": "standby"}}

    assert worker._target_tick_hz() == settings.TWIN_IDLE_TICK_HZ
    assert worker._target_tick_hz() < POLL_HZ


def test_unavailable_klipper_uses_recovery_rate():
    worker = TelemetryWorker()
    worker._moonraker_online = True
    worker._klippy_connected = False
    worker._klippy_state = "error"

    assert worker._target_tick_hz() == settings.TWIN_OFFLINE_TICK_HZ
    assert worker._target_tick_hz() < settings.TWIN_IDLE_TICK_HZ
