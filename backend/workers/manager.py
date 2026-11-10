"""
workers/manager.py
-------------------
Orchestrates switching the active Moonraker connection at runtime: stops the
current TelemetryWorker, repoints settings.MOONRAKER_HOST/PORT, reloads the
printer profile cache, and starts a fresh worker against the new address.

Only one TelemetryWorker runs at a time (see config/printers.py for why this
is the right model, not N simultaneous connections). Not available in
simulation mode — a sim run has no real second Moonraker to switch to.

workers._switching is checked by main.py's watchdog loop, so the few seconds
where the old worker has stopped and the new one hasn't started yet don't
look like a crashed thread and trigger an unwanted process restart.
"""

import logging
import threading

import workers
from config.settings import settings
from config import loader as config_loader

_SWITCH_TIMEOUT_S = 10
_lock = threading.Lock()


def switch_active_printer(host: str, port: int) -> None:
    """Blocking — stops the old worker, switches settings, reloads the
    profile, and starts a new worker before returning. Callers (the API
    route) run this synchronously so the HTTP response only succeeds once
    the switch has actually completed."""
    if settings.SIM_MODE:
        raise RuntimeError("Cannot switch printers while running in simulation mode")

    with _lock:
        from workers.telemetry_worker import TelemetryWorker

        old = workers._active_worker
        workers._switching = True
        try:
            if old is not None:
                old.stop()
                old._thread.join(timeout=_SWITCH_TIMEOUT_S)
                if old._thread.is_alive():
                    logging.info("⚠️  Previous telemetry worker did not stop within "
                                 f"{_SWITCH_TIMEOUT_S}s — switching anyway; the old "
                                 "thread will exit on its own once its current tick finishes.")

            settings.MOONRAKER_HOST = host
            settings.MOONRAKER_PORT = port

            try:
                config_loader.reload()
            except Exception as e:
                # Non-fatal: the new printer might be briefly unreachable
                # right after a switch (still booting, network hiccup). The
                # profile will pick up correctly next time reload() runs —
                # it isn't required for the worker itself to start.
                logging.info(f"⚠️  Profile reload after printer switch failed (will retry later): {e}")

            new_worker = TelemetryWorker()
            new_worker.start()
            workers._active_worker = new_worker
            logging.info(f"🔀 Switched active printer to {host}:{port}")
        finally:
            workers._switching = False
