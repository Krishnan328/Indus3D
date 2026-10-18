import logging

def up(conn):
    logging.info("Migration 008: Adding closed-loop dimensions and work-order tracking to print_history")
    
    # Klipper/SQLite does not support "ADD COLUMN IF NOT EXISTS" easily,
    # but we can try/except each one for idempotency.
    columns = [
        ("measured_x", "REAL DEFAULT NULL"),
        ("measured_y", "REAL DEFAULT NULL"),
        ("measured_z", "REAL DEFAULT NULL"),
        ("work_order_id", "TEXT DEFAULT NULL"),
        ("operator_name", "TEXT DEFAULT NULL"),
        ("customer", "TEXT DEFAULT NULL")
    ]
    
    for col_name, col_type in columns:
        try:
            conn.execute(f"ALTER TABLE print_history ADD COLUMN {col_name} {col_type}")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                raise e
    
    conn.commit()
