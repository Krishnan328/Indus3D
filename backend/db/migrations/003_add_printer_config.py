"""
Migration 003: Add printer_config table for material-aware predictive maintenance
"""

def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS printer_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Insert defaults
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('nozzle_material', 'Brass')")
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('filament_type', 'Standard')")
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('structural_material', 'PETG')")
    conn.commit()
