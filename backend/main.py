import core.logger

import logging
import threading
import time
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

SIM_MODE = "--sim" in sys.argv

# ── Profile flag ──────────────────────────────────────────────────────────────
_profile_arg = None
for i, arg in enumerate(sys.argv):
    if arg == "--profile" and i + 1 < len(sys.argv):
        _profile_arg = sys.argv[i + 1]

if SIM_MODE and _profile_arg:
    os.environ["INDUS_SIM_PROFILE"] = os.path.join(BASE_DIR, "config", _profile_arg)

from api.server import run_server
from db.models import init_db


def main():
    init_db()

    # Run any pending database migrations before starting the telemetry
    # loop. If a migration fails, the process exits rather than running
    # with a half-migrated schema.
    from db.migrator import run_migrations
    run_migrations()

    if SIM_MODE:
        # Parse shape and layers from CLI
        shape  = "benchy"
        # The bundled Benchy source contains 0.4 mm contours; the simulator
        # expands it to a 0.2 mm virtual layer profile for a continuous model.
        layers = 240
        for i, arg in enumerate(sys.argv):
            if arg == "--shape"  and i + 1 < len(sys.argv): shape  = sys.argv[i + 1]
            if arg == "--layers" and i + 1 < len(sys.argv): layers = int(sys.argv[i + 1])

        logging.info(f"⚠️  SIMULATION MODE — shape={shape}, layers={layers}")
        if _profile_arg:
            logging.info(f"   Profile: {_profile_arg}")

        from workers.simulator import SimulatedTelemetryWorker
        tw = SimulatedTelemetryWorker()
    else:
        from workers.telemetry_worker import TelemetryWorker
        tw = TelemetryWorker()

    tw.start()

    import workers
    workers._active_worker = tw

    # Start the Rust DSP pipeline (no-op if binary not built)
    from workers.dsp_bridge import dsp_bridge
    dsp_bridge.start()

    mode_str = f"[SIM/{shape if SIM_MODE else ''}]" if SIM_MODE else "[LIVE]"
    logging.info(f"🧠 Indus3D {mode_str} started")

    api_thread = threading.Thread(target=run_server, daemon=True)
    api_thread.start()

    # Watchdog. api_thread and tw's own thread are both daemon threads — if
    # either dies for any reason (port conflict, an unhandled exception,
    # anything), Python does not exit the process on its own. Without this,
    # the loop below would just keep running forever with a dead subsystem
    # underneath it, completely invisible to systemd: Restart=always never
    # triggers because the process never exits, so `systemctl status`
    # shows "active" while the API or the digital twin is actually dead.
    # os._exit(), not sys.exit() — this needs to kill the whole process
    # regardless of which thread notices the problem.
    #
    # Reads workers._active_worker fresh every loop (not the local `tw`
    # above) because a multi-printer switch (workers/manager.py) replaces
    # the active worker at runtime with a brand new thread. workers._switching
    # is True for the brief window mid-switch where the old thread has
    # stopped and the new one hasn't started — that's an expected, momentary
    # gap, not a crash, so the check is skipped while it's set.
    while True:
        time.sleep(2)
        if not api_thread.is_alive():
            logging.info("🔴 API server thread died — exiting so systemd can restart cleanly")
            os._exit(1)
        if not getattr(workers, '_switching', False):
            active = workers._active_worker
            if active is not None and not active._thread.is_alive():
                logging.info("🔴 Telemetry worker thread died — exiting so systemd can restart cleanly")
                os._exit(1)


if __name__ == "__main__":
    main()
