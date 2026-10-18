def up(conn):
    print("Migration 006: Create spools table")
    conn.execute("""
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
    # If there are no spools, insert a default one and make it active
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM spools")
    if c.fetchone()[0] == 0:
        conn.execute("""
            INSERT INTO spools (name, material, color_hex, starting_weight_g, is_active) 
            VALUES ('Generic Black PLA', 'PLA', '#111111', 1000.0, 1)
        """)
if __name__ == "__main__":
    import sqlite3, os
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "flight_record.db"))
    run_migration(conn)
    conn.commit()
    conn.close()
