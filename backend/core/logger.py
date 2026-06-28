import time
from db.models import get_connection

def log_command(command, source, status):
    conn=get_connection(); cursor=conn.cursor()
    cursor.execute("INSERT INTO command_log (timestamp,command,source,status) VALUES (?,?,?,?)",
        (time.time(),command,source,status))
    conn.commit(); conn.close()

def get_logs(limit=50):
    conn=get_connection(); cursor=conn.cursor()
    cursor.execute("SELECT timestamp,command,source,status FROM command_log ORDER BY id DESC LIMIT ?",(limit,))
    rows=cursor.fetchall(); conn.close()
    return [{"timestamp":r[0],"command":r[1],"source":r[2],"status":r[3]} for r in rows]
