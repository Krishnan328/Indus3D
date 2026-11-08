#!/usr/bin/env python3
"""Index an existing passive capture and service accounting in a separate SQLite DB.

No printer/network APIs are used here. Run beside capture_print_telemetry.py.
The database is independent of the production flight recorder.
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

from collect_system_stats import _service


def initialize(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS telemetry (
            line_number INTEGER PRIMARY KEY, captured_at TEXT, monotonic_seconds REAL,
            print_state TEXT, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY, monotonic_seconds REAL NOT NULL,
            service TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, monotonic_seconds REAL NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL
        );
    """)
    conn.commit()


def ingest(conn, line_number, record):
    telemetry = record.get("telemetry", {})
    state = telemetry.get("print_state", telemetry.get("state"))
    previous = conn.execute("SELECT print_state FROM telemetry ORDER BY line_number DESC LIMIT 1").fetchone()
    inserted = conn.execute(
        "INSERT OR IGNORE INTO telemetry VALUES (?, ?, ?, ?, ?)",
        (line_number, record.get("captured_at"), record.get("monotonic_seconds"), state, json.dumps(record)),
    ).rowcount
    if inserted and (not previous or previous[0] != state):
        conn.execute("INSERT INTO events(monotonic_seconds, kind, detail) VALUES (?, 'state', ?)",
                     (time.monotonic(), f"{previous[0] if previous else 'initial'} -> {state}"))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=1800)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--completion-tail", type=float, default=120)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60 or not 1 <= args.duration <= 7200 or not 0 <= args.completion_tail <= 600:
        parser.error("interval must be 1–60s, duration 1–7200s, completion tail 0–600s")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.database)
    initialize(conn)
    deadline = time.monotonic() + args.duration
    terminal_since = None
    seen_print = False
    line_number = 0
    # Only consume complete lines: the producer may currently be appending one.
    with args.capture.open(encoding="utf-8") as stream:
        try:
            while True:
                while True:
                    offset = stream.tell()
                    line = stream.readline()
                    if not line.endswith("\n"):
                        stream.seek(offset)
                        break
                    line_number += 1
                    try:
                        state = ingest(conn, line_number, json.loads(line))
                    except (ValueError, TypeError, AttributeError) as error:
                        conn.execute("INSERT INTO events(monotonic_seconds, kind, detail) VALUES (?, 'invalid_sample', ?)",
                                     (time.monotonic(), f"line {line_number}: {error}"))
                        continue
                    seen_print = seen_print or state in ("printing", "paused")
                    if seen_print and state in ("complete", "cancelled", "error", "standby"):
                        terminal_since = terminal_since or time.monotonic()
                    elif state in ("printing", "paused"):
                        terminal_since = None
                now = time.monotonic()
                for name in ("indus3d", "nginx", "moonraker", "klipper"):
                    conn.execute("INSERT INTO resources(monotonic_seconds, service, payload_json) VALUES (?, ?, ?)",
                                 (now, name, json.dumps(_service(name))))
                conn.commit()
                if now >= deadline or (terminal_since is not None and now - terminal_since >= args.completion_tail):
                    break
                time.sleep(min(args.interval, max(0, deadline - now)))
        finally:
            conn.commit()
            print(f"Indexed {conn.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]} samples into {args.database}", flush=True)
            conn.close()


if __name__ == "__main__":
    main()
