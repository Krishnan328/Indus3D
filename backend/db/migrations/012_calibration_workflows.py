"""Persist guarded calibration workflow sessions and their rollback evidence."""

import logging


def up(conn):
    logging.info("Migration 012: Adding guarded calibration workflow sessions")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calibration_workflows (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            status TEXT NOT NULL,
            preflight_json TEXT NOT NULL,
            rollback_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            persistence_approval_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calibration_workflows_created ON calibration_workflows(created_at DESC)")
    conn.commit()
