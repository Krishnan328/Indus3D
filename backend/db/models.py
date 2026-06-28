import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "flight_record.db")


def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn   = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS command_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            command   TEXT,
            source    TEXT,
            status    TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odometry (
            id            INTEGER PRIMARY KEY,
            axis          TEXT UNIQUE,
            travel_meters REAL DEFAULT 0.0
        )
    """)
    for axis in ['X', 'Y', 'Z', 'E']:
        cursor.execute(
            "INSERT OR IGNORE INTO odometry (axis, travel_meters) VALUES (?, 0.0)", (axis,)
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS print_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            filename  TEXT,
            status    TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS twin_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    REAL,
            cmd_x        REAL, cmd_y  REAL, cmd_z REAL, cmd_e REAL,
            live_x       REAL, live_y REAL, live_z REAL,
            velocity_mm_s REAL,
            ext_temp     REAL, ext_target REAL, ext_pwm REAL,
            bed_temp     REAL, bed_target REAL,
            print_state  TEXT,
            filename     TEXT
        )
    """)

    # New: action log — records every automated corrective action taken
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL,
            alert_id    TEXT,
            gcode       TEXT,
            description TEXT,
            status      TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("🗄️  Database initialized.")
