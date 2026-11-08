"""
digital_twin/snapshot_logger.py
---------------------------------
log_snapshot() used to open a new SQLite connection, INSERT, commit
(blocking fsync), and close -- every single call, on the same thread that
polls Moonraker and runs the quality controller. On an SD card, fsync
latency is unpredictable (10-50ms+ isn't unusual) and that latency landed
directly on the telemetry loop's critical path.

Now log_snapshot() just appends to an in-memory buffer under a lock -- no
I/O at all -- and a background thread flushes the buffer to SQLite in one
batched executemany() every FLUSH_INTERVAL_S seconds, using a single
persistent connection instead of reconnecting every time.

Trade-off, and it's a real one: the most recent up-to-FLUSH_INTERVAL_S
seconds of snapshots live only in memory until the next flush. A replay
request (get_recent_snapshots) during that window won't see them yet.
Given replay is a look-back tool, not a live view (the WebSocket firehose
already covers "right now"), this is the correct trade to make. A clean
process exit flushes whatever's still buffered via atexit, so a normal
shutdown doesn't lose data -- a hard kill (SIGKILL) still can, same as it
always could with the previous implementation's un-flushed writes in
flight.
"""

import logging
import atexit
import threading
import time
from db.models import get_connection

FLUSH_INTERVAL_S = 2.0

_buffer = []
_buffer_lock = threading.Lock()
_conn = None
_flush_thread_started = False
_flush_thread_lock = threading.Lock()

_INSERT_SQL = """INSERT INTO twin_snapshots (
    timestamp, cmd_x,cmd_y,cmd_z,cmd_e, live_x,live_y,live_z,
    velocity_mm_s, ext_temp,ext_target,ext_pwm, bed_temp,bed_target,
    print_state,filename
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _row_from_snapshot(printer_snap, kinematic_metrics, thermal_metrics, extrusion_metrics):
    return (
        time.time(),
        printer_snap.get("cmd_x", 0), printer_snap.get("cmd_y", 0),
        printer_snap.get("cmd_z", 0), printer_snap.get("cmd_e", 0),
        printer_snap.get("live_x", 0), printer_snap.get("live_y", 0), printer_snap.get("live_z", 0),
        printer_snap.get("velocity", 0),
        printer_snap.get("ext_temp", 0), printer_snap.get("ext_target", 0), printer_snap.get("ext_pwm", 0),
        printer_snap.get("bed_temp", 0), printer_snap.get("bed_target", 0),
        printer_snap.get("print_state", "unknown"), printer_snap.get("filename", ""),
    )


def _flush():
    global _conn
    with _buffer_lock:
        if not _buffer:
            return
        rows, _buffer[:] = list(_buffer), []
    try:
        if _conn is None:
            _conn = get_connection()
        _conn.executemany(_INSERT_SQL, rows)
        _conn.commit()
    except Exception as e:
        logging.info(f"snapshot_logger: flush of {len(rows)} rows failed: {e}")


def _flush_loop():
    while True:
        time.sleep(FLUSH_INTERVAL_S)
        _flush()


def _ensure_flush_thread():
    global _flush_thread_started
    with _flush_thread_lock:
        if _flush_thread_started:
            return
        _flush_thread_started = True
        threading.Thread(target=_flush_loop, daemon=True).start()
        atexit.register(_flush)


def log_snapshot(printer_snap, kinematic_metrics, thermal_metrics, extrusion_metrics):
    """Called from the telemetry loop every tick. Must stay fast -- this is
    on the same thread as the Moonraker poll and the quality controller."""
    _ensure_flush_thread()
    row = _row_from_snapshot(printer_snap, kinematic_metrics, thermal_metrics, extrusion_metrics)
    with _buffer_lock:
        _buffer.append(row)


def get_recent_snapshots(limit=200):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""SELECT timestamp,cmd_x,cmd_y,cmd_z,cmd_e,live_x,live_y,live_z,
            velocity_mm_s,ext_temp,ext_target,ext_pwm,bed_temp,bed_target,print_state,filename
            FROM twin_snapshots ORDER BY id DESC LIMIT ?""", (limit,))
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, row)) for row in c.fetchall()]
        conn.close()
        return list(reversed(rows))
    except Exception as e:
        logging.info(f"snapshot_logger: {e}")
        return []
