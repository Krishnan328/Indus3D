"""Persist offline predictions and their measured comparison for Printer Lab."""

import logging


def _add_column(conn, name, definition):
    try:
        conn.execute(f"ALTER TABLE lab_runs ADD COLUMN {name} {definition}")
    except Exception as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def up(conn):
    logging.info("Migration 011: Adding Printer Lab prediction analysis")
    _add_column(conn, "predictions_json", "TEXT NOT NULL DEFAULT '{}'")
    _add_column(conn, "analysis_json", "TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
