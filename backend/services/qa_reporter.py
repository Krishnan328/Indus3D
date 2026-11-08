import os
import threading
import logging
import time
import hashlib
from datetime import datetime
from services.quality_metrics import EXCURSION_ALERT_IDS
from db.models import get_connection
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

def _generate_report_task(history_id: int, start_ts: float, end_ts: float, filename: str):
    logging.info(f"Generating QA Report for Job {history_id}...")
    try:
        conn = get_connection()
        c = conn.cursor()
        
        c.execute("""
            SELECT timestamp, 
                   ext_temp, ext_target, 
                   bed_temp, bed_target, 
                   velocity_mm_s,
                   live_x, live_y, live_z
            FROM twin_snapshots 
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (start_ts, end_ts))
        
        rows = c.fetchall()
        
        if not rows:
            logging.info("QA Report aborted: No telemetry data found for timeframe.")
            conn.close()
            return
            
        times = [(row[0] - start_ts) / 60.0 for row in rows] # Minutes
        ext_temps = [row[1] for row in rows]
        ext_targs = [row[2] for row in rows]
        bed_temps = [row[3] for row in rows]
        bed_targs = [row[4] for row in rows]
        velocities = [row[5] for row in rows]
        
        # Calculate CMM Physical Bounding Box from actual telemetry
        xs = [row[6] for row in rows if row[6] is not None]
        ys = [row[7] for row in rows if row[7] is not None]
        zs = [row[8] for row in rows if row[8] is not None]
        
        max_x = max(xs) if xs else 0.0
        min_x = min(xs) if xs else 0.0
        max_y = max(ys) if ys else 0.0
        min_y = min(ys) if ys else 0.0
        max_z = max(zs) if zs else 0.0
        
        dim_x = max_x - min_x
        dim_y = max_y - min_y
        dim_z = max_z
        
        c.execute("""
            SELECT measured_x, measured_y, measured_z, work_order_id, operator_name,
                   timelapse_id, timelapse_path, timelapse_hash
            FROM print_history WHERE id = ?
        """, (history_id,))
        hist_row = c.fetchone()
        meas_x = hist_row[0] if hist_row and hist_row[0] is not None else "N/A"
        meas_y = hist_row[1] if hist_row and hist_row[1] is not None else "N/A"
        meas_z = hist_row[2] if hist_row and hist_row[2] is not None else "N/A"
        work_order = hist_row[3] if hist_row and hist_row[3] else "N/A"
        operator = hist_row[4] if hist_row and hist_row[4] else "N/A"
        timelapse_id = hist_row[5] if hist_row and len(hist_row) > 5 and hist_row[5] else None
        timelapse_path = hist_row[6] if hist_row and len(hist_row) > 6 and hist_row[6] else None
        timelapse_hash = hist_row[7] if hist_row and len(hist_row) > 7 and hist_row[7] else "not recorded"
        
        # Get active spool details for AS9100 Certificate
        c.execute("SELECT name, material, lot_number, manufacturer, material_grade FROM spools WHERE is_active = 1 LIMIT 1")
        spool = c.fetchone()
        spool_name = spool[0] if spool else "Unknown"
        spool_mat = spool[1] if spool else "Unknown"
        spool_lot = spool[2] if spool and spool[2] else "N/A"
        spool_mfg = spool[3] if spool and spool[3] else "N/A"
        spool_grade = spool[4] if spool and spool[4] else "N/A"
        
        # Get Excursions and Actions for Hashing
        c.execute("SELECT timestamp, alert_id, description FROM action_log WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC", (start_ts, end_ts))
        actions = c.fetchall()
        
        excursion_count = len([a for a in actions if a[1] in EXCURSION_ALERT_IDS])
        
        # SHA-256 of the telemetry and action rows, stored in print_history so the report can be checked against it
        hasher = hashlib.sha256()
        hasher.update(str(rows).encode('utf-8'))
        hasher.update(str(actions).encode('utf-8'))
        telemetry_hash = hasher.hexdigest()
        
        # Update print history with hash
        c.execute("UPDATE print_history SET telemetry_hash = ?, excursions_count = ? WHERE id = ?", (telemetry_hash, excursion_count, history_id))
        conn.commit()

        
        report_filename = f"qa_report_{history_id}_{int(time.time())}.pdf"
        report_path = os.path.join(REPORTS_DIR, report_filename)
        
        with PdfPages(report_path) as pdf:
            # 1. Thermal Variance Page
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 10))
            fig.suptitle(f"QA Thermal Analysis - {filename}", fontsize=16)
            
            ax1.plot(times, ext_temps, label='Extruder Temp', color='red', alpha=0.8)
            ax1.plot(times, ext_targs, label='Target', color='black', linestyle='--')
            ax1.set_ylabel('Temperature (°C)')
            ax1.set_title('Extruder Thermal Performance')
            ax1.legend()
            ax1.grid(True)
            
            ax2.plot(times, bed_temps, label='Bed Temp', color='blue', alpha=0.8)
            ax2.plot(times, bed_targs, label='Target', color='black', linestyle='--')
            ax2.set_ylabel('Temperature (°C)')
            ax2.set_xlabel('Time (Minutes)')
            ax2.set_title('Heated Bed Thermal Performance')
            ax2.legend()
            ax2.grid(True)
            
            pdf.savefig(fig)
            plt.close(fig)
            
            # 2. Kinematics Page
            fig, ax = plt.subplots(figsize=(8, 6))
            fig.suptitle(f"QA Kinematics - {filename}", fontsize=16)
            ax.plot(times, velocities, label='Velocity (mm/s)', color='green', alpha=0.7)
            ax.set_ylabel('Velocity (mm/s)')
            ax.set_xlabel('Time (Minutes)')
            ax.set_title('Toolhead Speed Variance')
            ax.grid(True)
            
            pdf.savefig(fig)
            plt.close(fig)
            
            # 3. AS9100 Certificate of Conformance Page
            fig = plt.figure(figsize=(8, 10))
            fig.suptitle(f"Certificate of Conformance (CoC)", fontsize=18, fontweight='bold', y=0.95)
            
            coc_text = (
                f"Print Job ID: {history_id}\n"
                f"File: {filename}\n"
                f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                
                f"--- MATERIAL TRACEABILITY ---\n"
                f"Work Order: {work_order}\n"
                f"Operator: {operator}\n"
                f"Spool Name: {spool_name}\n"
                f"Material: {spool_mat}\n"
                f"Manufacturer: {spool_mfg}\n"
                f"Material Grade: {spool_grade}\n"
                f"Lot / Batch Number: {spool_lot}\n\n"
                
                f"--- QUALITY COMPLIANCE ---\n"
                f"Critical Excursions (Out-of-Spec): {excursion_count}\n"
                f"Total Interventions Logged: {len(actions)}\n\n"
                
                f"--- CMM DIMENSIONAL INSPECTION GUIDE ---\n"
                f"Maximum Physical Toolhead Bounds (Computed from Telemetry):\n"
                f"  X-Axis Width: {dim_x:.2f} mm    | Measured: {meas_x} mm\n"
                f"  Y-Axis Depth: {dim_y:.2f} mm    | Measured: {meas_y} mm\n"
                f"  Z-Axis Height: {dim_z:.2f} mm    | Measured: {meas_z} mm\n\n"
                f"--- INTEGRITY RECORD ---\n"
                f"Telemetry SHA-256 Hash:\n"
                f"{telemetry_hash}\n"
                f"(Compare with the value stored in the Indus3D database; this is a checksum, not a signature)\n\n"
                f"--- VISUAL TRACEABILITY & TIMELAPSE ---\n"
                + (
                    f"Timelapse Session: {timelapse_id}\n"
                    f"Video SHA-256 Hash:\n"
                    f"{timelapse_hash}\n"
                    if timelapse_id else
                    "Timelapse: unavailable\n"
                )
            )
            
            fig.text(0.1, 0.88, coc_text, fontsize=10, family='monospace', verticalalignment='top')
            
            pdf.savefig(fig)
            plt.close(fig)

            # 4. Optional Visual Keyframes Page (if timelapse frames exist)
            if timelapse_path:
                job_dir = os.path.dirname(timelapse_path)
                k_first = os.path.join(job_dir, "keyframe_first.jpg")
                k_last = os.path.join(job_dir, "keyframe_last.jpg")
                if os.path.isfile(k_first) or os.path.isfile(k_last):
                    try:
                        import matplotlib.image as mpimg
                        fig_v, axes = plt.subplots(1, 2, figsize=(10, 5))
                        fig_v.suptitle(f"Visual In-Process Audit Keyframes - Job {history_id}", fontsize=14)
                        
                        if os.path.isfile(k_first):
                            axes[0].imshow(mpimg.imread(k_first))
                            axes[0].set_title("First Layer / Initial Phase")
                            axes[0].axis('off')
                        else:
                            axes[0].text(0.5, 0.5, "Initial frame unavailable", ha='center')
                            axes[0].axis('off')
                            
                        if os.path.isfile(k_last):
                            axes[1].imshow(mpimg.imread(k_last))
                            axes[1].set_title("Final Layer / Completion Phase")
                            axes[1].axis('off')
                        else:
                            axes[1].text(0.5, 0.5, "Final frame unavailable", ha='center')
                            axes[1].axis('off')

                        pdf.savefig(fig_v)
                        plt.close(fig_v)
                    except Exception as ve:
                        logging.warning(f"Could not render visual audit keyframes: {ve}")
            
        # Update print history
        c.execute("UPDATE print_history SET report_path = ? WHERE id = ?", (report_filename, history_id))
        conn.commit()
        conn.close()
        logging.info(f"QA Report generated: {report_filename}")
        
        # Also trigger the annotated G-Code PDF generation
        try:
            from services.gcode_annotator import generate_annotated_gcode_pdf
            generate_annotated_gcode_pdf(history_id, start_ts, end_ts, filename)
        except ImportError:
            logging.warning("ReportLab not installed, skipping annotated G-code PDF generation.")

        
    except Exception as e:
        logging.error(f"Failed to generate QA report: {e}")

def trigger_qa_report(history_id: int, start_ts: float, end_ts: float, filename: str):
    # Run in background thread so it doesn't block telemetry loop
    threading.Thread(target=_generate_report_task, args=(history_id, start_ts, end_ts, filename), daemon=True).start()
