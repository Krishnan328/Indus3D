import logging
import sqlite3
import os
from config.settings import settings

# settings.py owns all environment-backed configuration. Keeping the database
# path here in sync with it makes isolated simulations and test deployments
# possible without changing the production flight recorder.
DB_PATH = settings.DB_PATH


def get_connection():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
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
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            print_time_seconds REAL DEFAULT 0.0,
            filament_used_g REAL DEFAULT 0.0,
            power_used_wh REAL DEFAULT 0.0,
            cost_usd REAL DEFAULT 0.0,
            report_path TEXT,
            annotated_gcode_path TEXT
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


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_counters (
            task_id TEXT PRIMARY KEY,
            value REAL DEFAULT 0.0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            timestamp REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS printer_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('nozzle_material', 'Brass')")
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('filament_type', 'Standard')")
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('structural_material', 'PETG')")
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_weight_g', '1000')")
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_used_g', '0')")
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_color', '#ff0000')")
    cursor.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_material', 'PLA')")


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            material TEXT NOT NULL,
            color_hex TEXT NOT NULL,
            starting_weight_g REAL NOT NULL,
            used_weight_g REAL DEFAULT 0.0,
            density_g_cm3 REAL DEFAULT 1.24,
            is_active INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM spools")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO spools (name, material, color_hex, starting_weight_g, is_active) VALUES (\'Generic Black PLA\', \'PLA\', \'#111111\', 1000.0, 1)")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()
    logging.info("🗄️  Database initialized.")
