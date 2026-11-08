"""
Migration 004: Add report_path column to print_history
"""
def up(conn):
    try:
        conn.execute("ALTER TABLE print_history ADD COLUMN report_path TEXT")
        conn.commit()
    except Exception as e:
        # Ignore if column already exists
        if "duplicate column" not in str(e).lower():
            raise
