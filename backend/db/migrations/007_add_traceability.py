def up(conn):
    print("Migration 007: Add traceability fields to spools and print_history")
    
    # Check if lot_number exists in spools to avoid duplicate column errors
    c = conn.cursor()
    c.execute("PRAGMA table_info(spools)")
    columns = [col[1] for col in c.fetchall()]
    
    if "lot_number" not in columns:
        conn.execute("ALTER TABLE spools ADD COLUMN lot_number TEXT DEFAULT NULL")
        conn.execute("ALTER TABLE spools ADD COLUMN manufacturer TEXT DEFAULT NULL")
        conn.execute("ALTER TABLE spools ADD COLUMN material_grade TEXT DEFAULT NULL")
        conn.execute("ALTER TABLE spools ADD COLUMN cert_url TEXT DEFAULT NULL")
    
    c.execute("PRAGMA table_info(print_history)")
    ph_columns = [col[1] for col in c.fetchall()]
    
    if "telemetry_hash" not in ph_columns:
        conn.execute("ALTER TABLE print_history ADD COLUMN telemetry_hash TEXT DEFAULT NULL")
        conn.execute("ALTER TABLE print_history ADD COLUMN excursions_count INTEGER DEFAULT 0")

if __name__ == "__main__":
    import sqlite3, os
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "flight_record.db"))
    run_migration(conn)
    conn.commit()
    conn.close()
