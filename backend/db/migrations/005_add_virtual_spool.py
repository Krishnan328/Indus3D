"""
Migration 005: Add virtual spool defaults
"""
def up(conn):
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_weight_g', '1000')")
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_used_g', '0')")
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_color', '#ff0000')")
    conn.execute("INSERT OR IGNORE INTO printer_config (key, value) VALUES ('virtual_spool_material', 'PLA')")
    conn.commit()
