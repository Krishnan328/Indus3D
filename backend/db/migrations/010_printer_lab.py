"""Add persistent, user-owned Printer Lab experiment records."""

import logging


def up(conn):
    """Create tables without coupling experiments to live printer control."""
    logging.info("Migration 010: Adding Printer Lab experiment records")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lab_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            kind TEXT NOT NULL,
            label TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            printer_profile TEXT NOT NULL DEFAULT '',
            material TEXT NOT NULL DEFAULT '',
            gcode_filename TEXT NOT NULL DEFAULT '',
            slicer_estimated_seconds REAL,
            notes TEXT NOT NULL DEFAULT '',
            measurements_json TEXT NOT NULL DEFAULT '{}',
            artifacts_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lab_runs_created_at ON lab_runs(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lab_runs_kind ON lab_runs(kind)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lab_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            run_id INTEGER NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            budgets_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(run_id) REFERENCES lab_runs(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
