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

from cmd_queue.command_queue import CommandQueue
from workers.queue_worker import QueueWorker
from api.server import run_server
from api.routes.control import set_queue
from db.models import init_db


def main():
    init_db()

    cmd_queue = CommandQueue()
    worker    = QueueWorker(cmd_queue)
    worker.start()
    set_queue(cmd_queue)

    if SIM_MODE:
        # Parse shape and layers from CLI
        shape  = "benchy"
        layers = 40
        for i, arg in enumerate(sys.argv):
            if arg == "--shape"  and i + 1 < len(sys.argv): shape  = sys.argv[i + 1]
            if arg == "--layers" and i + 1 < len(sys.argv): layers = int(sys.argv[i + 1])

        print(f"⚠️  SIMULATION MODE — shape={shape}, layers={layers}")
        if _profile_arg:
            print(f"   Profile: {_profile_arg}")

        from workers.simulator import SimulatedTelemetryWorker
        tw = SimulatedTelemetryWorker()
    else:
        from workers.telemetry_worker import TelemetryWorker
        tw = TelemetryWorker()

    tw.start()

    import workers
    workers._active_worker = tw

    mode_str = f"[SIM/{shape if SIM_MODE else ''}]" if SIM_MODE else "[LIVE]"
    print(f"🧠 Indus3D {mode_str} started")

    api_thread = threading.Thread(target=run_server, daemon=True)
    api_thread.start()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
