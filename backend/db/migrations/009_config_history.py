import logging

def up(conn):
    logging.info("Migration 009: Adding config_history table and config_id to print_history")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            operator_name TEXT,
            config_snapshot_json TEXT,
            diff_summary TEXT
        )
    """)
    
    # Try to add config_id to print_history
    try:
        conn.execute("ALTER TABLE print_history ADD COLUMN config_id INTEGER DEFAULT NULL")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise e
            
    conn.commit()
