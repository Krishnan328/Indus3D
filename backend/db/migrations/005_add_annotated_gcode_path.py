def run_migration(conn):
    print("Migration 005: Add annotated_gcode_path column to print_history")
    try:
        conn.execute("ALTER TABLE print_history ADD COLUMN annotated_gcode_path TEXT")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            raise
