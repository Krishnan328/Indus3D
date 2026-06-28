import time
from db.models import get_connection

def log_snapshot(printer_snap, kinematic_metrics, thermal_metrics, extrusion_metrics):
    try:
        conn=get_connection(); c=conn.cursor()
        c.execute("""INSERT INTO twin_snapshots (
            timestamp, cmd_x,cmd_y,cmd_z,cmd_e, live_x,live_y,live_z,
            velocity_mm_s, ext_temp,ext_target,ext_pwm, bed_temp,bed_target,
            print_state,filename
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            time.time(),
            printer_snap.get("cmd_x",0),printer_snap.get("cmd_y",0),
            printer_snap.get("cmd_z",0),printer_snap.get("cmd_e",0),
            printer_snap.get("live_x",0),printer_snap.get("live_y",0),printer_snap.get("live_z",0),
            printer_snap.get("velocity",0),
            printer_snap.get("ext_temp",0),printer_snap.get("ext_target",0),printer_snap.get("ext_pwm",0),
            printer_snap.get("bed_temp",0),printer_snap.get("bed_target",0),
            printer_snap.get("print_state","unknown"),printer_snap.get("filename",""),
        ))
        conn.commit(); conn.close()
    except Exception as e: print(f"⚠️ snapshot_logger: {e}")

def get_recent_snapshots(limit=200):
    try:
        conn=get_connection(); c=conn.cursor()
        c.execute("""SELECT timestamp,cmd_x,cmd_y,cmd_z,cmd_e,live_x,live_y,live_z,
            velocity_mm_s,ext_temp,ext_target,ext_pwm,bed_temp,bed_target,print_state,filename
            FROM twin_snapshots ORDER BY id DESC LIMIT ?""",(limit,))
        cols=[d[0] for d in c.description]
        rows=[dict(zip(cols,r)) for r in c.fetchall()]
        conn.close(); return list(reversed(rows))
    except: return []
