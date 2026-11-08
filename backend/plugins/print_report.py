"""
plugins/print_report.py  (E2)
------------------------------
A self-contained HTML report after every print (open it in a browser; "Print
to PDF" gives a PDF): summary, health score, model-vs-reality scores,
controller activity per parameter, a flow/speed-vs-progress chart and the
correction reasons. It complements services/qa_reporter.py (the telemetry
PDF) rather than replacing it.

Reports are written to <plugin data dir>/reports/. Generation runs a few
seconds after the print ends so the health and model scores exist first.

GET /api/v1/plugins/print_report              list
GET /api/v1/plugins/print_report/<run id>     the HTML (generated on demand if missing)
"""

import html
import logging
import time
from collections import Counter

from plugins._common import data_dir, delayed

PLUGIN_INFO = {
    "title": "Post-print report",
    "description": "Self-contained HTML report per print: scores, controller activity, timeline and reasons.",
}

DELAY_S = 8.0
MAX_ROWS = 100
CHART_FAMILIES = {"flow": "#2563eb", "speed": "#dc2626"}


def _e(v) -> str:
    return html.escape(str(v if v is not None else "—"))


def _fmt_dur(s):
    if s is None:
        return "—"
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60}m {s % 60}s"


def _chart(run) -> str:
    w, h, pad = 560, 160, 28
    lines = []
    for fam, color in CHART_FAMILIES.items():
        pts = [(c.get("progress") or 0.0, c["value"]) for c in run.get("commands", [])
               if c.get("ok") and c.get("family") == fam and c.get("value") is not None]
        if not pts:
            continue
        coords = " ".join(f"{pad + p * (w - 2 * pad):.1f},{h - pad - (v - 50) / 70.0 * (h - 2 * pad):.1f}"
                          for p, v in sorted(pts))
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coords}"/>'
                     f'<text x="{w - 70}" y="{14 + 14 * len(lines)}" fill="{color}" font-size="11">{fam} %</text>')
    if not lines:
        return "<p class='muted'>No flow/speed corrections were applied.</p>"
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Flow and speed commands over progress">'
            f'<rect x="{pad}" y="{pad / 2}" width="{w - 2 * pad}" height="{h - 1.5 * pad}" fill="none" stroke="#9ca3af"/>'
            f'<text x="{pad}" y="{h - 6}" font-size="10" fill="#6b7280">0 %</text>'
            f'<text x="{w - pad - 24}" y="{h - 6}" font-size="10" fill="#6b7280">100 % progress</text>'
            + "".join(lines) + "</svg>")


def build_html(run: dict, health=None, scores=None) -> str:
    dur = (run["ended"] - run["started"]) if run.get("ended") else None
    fam = Counter(c.get("family") or "other" for c in run.get("commands", []) if c.get("ok"))
    failed = sum(1 for c in run.get("commands", []) if not c.get("ok"))
    vetoes = Counter(v["plugin"] for v in run.get("vetoes", []))
    shadow = Counter(c.get("family") or "other" for c in run.get("shadow", []))

    def table(headers, rows):
        head = "".join(f"<th>{_e(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><tr>{head}</tr>{body}</table>" if rows else "<p class='muted'>None.</p>"

    health_html = "<p class='muted'>No health score for this print.</p>"
    if health:
        health_html = (f"<p class='big'>{_e(health['score'])} / 100 "
                       f"<span class='muted'>(source: {_e(health['data_source'])})</span></p>"
                       + table(["Component", "Penalty", "Detail"],
                               [(c["name"], c["penalty"], c["detail"]) for c in health["components"]]))
    score_html = "<p class='muted'>No model score yet.</p>"
    if scores:
        score_html = table(["Metric", "Predicted", "Actual", "Error %", "Status"],
                           [(m["metric"], m["predicted"], f"{m['actual']} {m['unit']}", m["error_pct"], m["status"])
                            for m in scores["metrics"]])
    reasons = [(round((c.get("progress") or 0) * 100, 1), c.get("type"), c.get("value"), c.get("reason"))
               for c in run.get("corrections", [])[:MAX_ROWS]]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Indus3D report — {_e(run.get('filename'))}</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#111827}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0}}th,td{{border:1px solid #d1d5db;padding:4px 8px;text-align:left}}
th{{background:#f3f4f6}}.muted{{color:#6b7280}}.big{{font-size:1.6rem;font-weight:600;margin:.2rem 0}}
@media(prefers-color-scheme:dark){{body{{background:#111827;color:#e5e7eb}}th{{background:#1f2937}}td,th{{border-color:#374151}}}}
</style></head><body>
<h1>Print report</h1>
<p><b>{_e(run.get('filename'))}</b> — {_e(run.get('final_state'))}<br>
Duration {_fmt_dur(dur)} · generated {_e(time.strftime('%Y-%m-%d %H:%M', time.localtime()))}</p>
<h2>Health score</h2>{health_html}
<h2>Model vs reality</h2>{score_html}
<h2>Controller activity</h2>
{table(['Family', 'Applied'], sorted(fam.items()))}
<p>Failed sends: {failed} · Vetoed: {_e(dict(vetoes) or 'none')} · Shadow (would-send): {_e(dict(shadow) or 'none')}</p>
<h2>Flow and speed over the print</h2>{_chart(run)}
<h2>Correction reasons{' (first ' + str(MAX_ROWS) + ')' if len(run.get('corrections', [])) > MAX_ROWS else ''}</h2>
{table(['Progress %', 'Type', 'Value', 'Reason'], reasons)}
</body></html>"""


def generate(run: dict) -> str:
    from plugins import health_score, model_scorer
    health = health_score.health.last_final
    scores = next((r for r in model_scorer.scorer.results if r["run"] == run["id"]), None)
    page = build_html(run, health, scores)
    path = data_dir("reports") / f"report-{run['id']}.html"
    path.write_text(page, encoding="utf-8")
    logging.info(f"📄 print report written: {path}")
    return page


def on_finish(run):
    if run.get("commands") or run.get("shadow") or run.get("vetoes") or run.get("corrections"):
        delayed(DELAY_S, generate, run)


def register_hooks(hooks) -> None:
    from plugins.run_recorder import recorder
    recorder.on_finish(on_finish)


def register_routes(app) -> None:
    from flask import Blueprint, Response, jsonify
    from plugins.run_recorder import recorder

    bp = Blueprint("plugin_print_report", __name__, url_prefix="/api/v1/plugins/print_report")

    @bp.route("", methods=["GET"])
    def reports():
        files = sorted(data_dir("reports").glob("report-*.html"), reverse=True)
        return jsonify({"reports": [{"run": int(f.stem.split("-")[1]), "bytes": f.stat().st_size} for f in files]})

    @bp.route("/<int:run_id>", methods=["GET"])
    def report(run_id):
        path = data_dir("reports") / f"report-{run_id}.html"
        if path.exists():
            return Response(path.read_text(encoding="utf-8"), mimetype="text/html")
        run = recorder.get(run_id)
        if run is None:
            return jsonify({"error": "run not found"}), 404
        return Response(generate(run), mimetype="text/html")

    app.register_blueprint(bp)
