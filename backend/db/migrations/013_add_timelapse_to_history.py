"""
Migration 013: Add timelapse_id, timelapse_path, and timelapse_hash to print_history
for visual QA audit trail.
"""

import logging


def up(conn):
    logging.info("Migration 013: Adding timelapse fields to print_history")
    c = conn.cursor()
    c.execute("PRAGMA table_info(print_history)")
    existing_cols = [row[1] for row in c.fetchall()]

    if "timelapse_id" not in existing_cols:
        conn.execute("ALTER TABLE print_history ADD COLUMN timelapse_id TEXT DEFAULT NULL")
    if "timelapse_path" not in existing_cols:
        conn.execute("ALTER TABLE print_history ADD COLUMN timelapse_path TEXT DEFAULT NULL")
    if "timelapse_hash" not in existing_cols:
        conn.execute("ALTER TABLE print_history ADD COLUMN timelapse_hash TEXT DEFAULT NULL")

    conn.commit()
