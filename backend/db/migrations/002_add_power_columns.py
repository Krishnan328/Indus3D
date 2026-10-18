"""
Migration 002: Add power columns to twin_snapshots
------------------------------------------------------
Adds columns for PZEM-004T power readings to the twin_snapshots table so
power telemetry is recorded alongside the existing kinematic/thermal data
during active prints.
"""


def up(conn):
    # SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
    # so check if the column already exists first.
    cursor = conn.execute("PRAGMA table_info(twin_snapshots)")
    existing = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("power_voltage",      "REAL"),
        ("power_current",      "REAL"),
        ("power_watts",        "REAL"),
        ("power_energy_wh",    "INTEGER"),
        ("power_frequency",    "REAL"),
        ("power_factor",       "REAL"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE twin_snapshots ADD COLUMN {col_name} {col_type}")

    conn.commit()
