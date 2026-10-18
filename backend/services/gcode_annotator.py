import os
import logging
import time
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor

from db.models import get_connection

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

COLORS = {
    "file": HexColor("#666688"),     # Original Slicer
    "indus": HexColor("#d35400"),    # Indus QC correction
    "crit": HexColor("#c0392b"),     # Critical Action
    "user": HexColor("#2980b9"),     # User Command
    "comment": HexColor("#7f8c8d"),  # Informational
}

def _classify_line(text):
    t = text.strip()
    if not t:
        return "file", "comment"
    if t.startswith("[INDUS]") or t.startswith("[QC]"):
        if "M112" in t:
            return "indus", "crit"
        return "indus", "indus"
    if t.startswith(">>>"):
        return "user", "user"
    if t.startswith(";"):
        return "file", "comment"
    return "file", "file"

def generate_annotated_gcode_pdf(history_id: int, start_ts: float, end_ts: float, filename: str):
    logging.info(f"Generating Annotated G-Code PDF for Job {history_id}...")
    try:
        conn = get_connection()
        c = conn.cursor()
        
        # 1. Fetch action log interventions for this timeframe
        c.execute("""
            SELECT timestamp, alert_id, gcode, description, status
            FROM action_log 
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (start_ts, end_ts))
        cols = [desc[0] for desc in c.description]
        actions = [dict(zip(cols, r)) for r in c.fetchall()]
        
        # 2. Try to load the original G-code file if it exists locally
        # Since we're in the backend, Moonraker might have it in ~/printer_data/gcodes/
        # Or we can just fetch it from Moonraker API, but doing HTTP req from background thread might be tricky if we don't have settings loaded.
        # Let's import settings
        from config.settings import settings
        import requests
        
        gcode_lines = []
        try:
            res = requests.get(f"{settings.moonraker_url}/server/files/gcodes/{filename}", timeout=30)
            if res.ok:
                gcode_lines = res.text.split("\\n")
        except Exception:
            pass
            
        if not gcode_lines:
            # Fallback for simulator
            if "sim_" in filename:
                # Can't easily grab simulator G-code from here, let's just use action log
                gcode_lines = ["; Simulator mode - full original G-code not available here", 
                               "; Displaying action log injections only"]

        # Merge
        merged = []
        for i, line in enumerate(gcode_lines):
            line = line.rstrip("\\n").rstrip("\\r")
            src, cls = _classify_line(line)
            merged.append({"ln": str(i+1), "text": line, "cls": cls})
            
        total_file = len(merged)
        actions_sorted = sorted(actions, key=lambda a: a.get("timestamp", 0))
        offset = 0
        for action in actions_sorted:
            if not action.get("gcode"):
                continue
            is_crit = action.get("alert_id", "") in ("ext_runaway", "bed_runaway") or "M112" in (action.get("gcode") or "")
            frac = min(1.0, max(0.0, (actions_sorted.index(action)) / max(len(actions_sorted), 1)))
            pos = min(int(frac * total_file) + offset, len(merged))
            merged.insert(pos, {
                "ln": "►",
                "text": f"{action['gcode']}    ; {action.get('description', '')}",
                "cls": "crit" if is_crit else "indus",
            })
            offset += 1
            
        # 3. Build PDF
        report_filename = f"annotated_gcode_{history_id}_{int(time.time())}.pdf"
        report_path = os.path.join(REPORTS_DIR, report_filename)
        
        doc = SimpleDocTemplate(report_path, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        styles = getSampleStyleSheet()
        
        title_style = styles["Heading1"]
        title_style.textColor = HexColor("#2c3e50")
        
        meta_style = ParagraphStyle(
            'Meta',
            parent=styles['Normal'],
            fontSize=10,
            textColor=HexColor("#7f8c8d"),
            spaceAfter=20
        )
        
        legend_style = ParagraphStyle(
            'Legend',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=5
        )
        
        code_styles = {}
        for k, v in COLORS.items():
            code_styles[k] = ParagraphStyle(
                f'Code_{k}',
                parent=styles['Normal'],
                fontName='Courier',
                fontSize=8,
                textColor=v,
                leading=10
            )
            
        story = []
        
        # Header
        story.append(Paragraph("Indus3D — Annotated G-Code Export", title_style))
        story.append(Paragraph(f"File: <b>{filename}</b> | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", meta_style))
        
        # Legend
        story.append(Paragraph("<b>Colour Legend:</b>", styles["Heading3"]))
        story.append(Paragraph(f"<font color='{COLORS['file']}'>■</font> Original Slicer G-code", legend_style))
        story.append(Paragraph(f"<font color='{COLORS['indus']}'>■</font> Indus3D QC Correction (e.g. Speed/Flow adjustments)", legend_style))
        story.append(Paragraph(f"<font color='{COLORS['crit']}'>■</font> Indus3D Critical Action (e.g. Emergency Stop)", legend_style))
        story.append(Paragraph(f"<font color='{COLORS['user']}'>■</font> User Manual Command", legend_style))
        story.append(Paragraph(f"<font color='{COLORS['comment']}'>■</font> Informational / Comment", legend_style))
        story.append(Spacer(1, 20))
        
        # Stats
        story.append(Paragraph(f"<b>Print Intervention Summary</b>", styles["Heading3"]))
        story.append(Paragraph(f"Original lines: {len(gcode_lines)}", legend_style))
        story.append(Paragraph(f"Indus3D injections: {len(actions)}", legend_style))
        story.append(Spacer(1, 20))
        
        # G-Code lines
        # Due to ReportLab performance, we can't create 100,000 Paragraphs.
        # We will group lines by color if possible, or just render the whole thing.
        # Actually, if the file is massive, we will only show lines around the interventions.
        
        if len(merged) > 2000 and len(actions) > 0:
            story.append(Paragraph("<i>Note: File is very large. Showing only snippets around Indus3D interventions.</i>", meta_style))
            story.append(Spacer(1, 10))
            
            snippet_range = 10
            shown_indices = set()
            for i, line in enumerate(merged):
                if line["ln"] == "►":
                    for j in range(max(0, i - snippet_range), min(len(merged), i + snippet_range + 1)):
                        shown_indices.add(j)
                        
            last_idx = -1
            for idx in sorted(list(shown_indices)):
                if last_idx != -1 and idx > last_idx + 1:
                    story.append(Paragraph("...", code_styles["comment"]))
                line = merged[idx]
                story.append(Paragraph(f"{line['ln']:>5} | {line['text']}", code_styles[line['cls']]))
                last_idx = idx
                
        elif len(merged) > 2000 and len(actions) == 0:
            story.append(Paragraph("<i>Note: File is very large and had no interventions. Showing first 500 lines only.</i>", meta_style))
            story.append(Spacer(1, 10))
            for i in range(min(500, len(merged))):
                line = merged[i]
                story.append(Paragraph(f"{line['ln']:>5} | {line['text']}", code_styles[line['cls']]))
                
        else:
            for line in merged:
                story.append(Paragraph(f"{line['ln']:>5} | {line['text']}", code_styles[line['cls']]))
                
        doc.build(story)
        
        # 4. Update DB
        c.execute("UPDATE print_history SET annotated_gcode_path = ? WHERE id = ?", (report_filename, history_id))
        conn.commit()
        conn.close()
        
        logging.info(f"Annotated G-Code PDF generated: {report_filename}")
        
    except Exception as e:
        logging.error(f"Failed to generate annotated G-code PDF: {e}")
