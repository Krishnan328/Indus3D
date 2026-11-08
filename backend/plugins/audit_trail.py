"""
plugins/audit_trail.py  (A2)
-----------------------------
Writes every corrective command to the database so "what did Indus3D send,
when and why" can be answered after the fact.

* command_log — one row per command: source "qc" / "qc-shadow", status
  "ok", "failed", "shadow" or "vetoed:<plugin>: <reason>".
* action_log  — one row per correction with its reason, alert_id
  "qc:<type>" (or "qc_shadow:<type>"), so the dashboard's Action Log shows the
  explanation next to the command.

Database errors are logged and swallowed: auditing must never affect control.
"""

import logging
import time

PLUGIN_INFO = {
    "title": "Command audit trail",
    "description": "Persists every corrective command, correction reason and veto to command_log / action_log.",
}


def _rows(sql_rows: list, table: str) -> None:
    if not sql_rows:
        return
    try:
        from db.models import get_connection
        conn = get_connection()
        try:
            if table == "command_log":
                conn.executemany(
                    "INSERT INTO command_log (timestamp, command, source, status) VALUES (?, ?, ?, ?)", sql_rows)
            else:
                conn.executemany(
                    "INSERT INTO action_log (timestamp, alert_id, gcode, description, status) "
                    "VALUES (?, ?, ?, ?, ?)", sql_rows)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logging.info(f"⚠️  audit_trail: could not write {table}: {e}")


def _corrections_rows(corrections: list, prefix: str, status: str) -> list:
    return [
        (c.get("ts", time.time()), f"{prefix}:{c.get('type')}", str(c.get("value")),
         c.get("reason", ""), status)
        for c in corrections
    ]


def on_sent(results: list, ctx: dict) -> None:
    now = ctx.get("now", time.time())
    _rows([(r.get("ts", now), r["command"], "qc", "ok" if r["ok"] else "failed") for r in results],
          "command_log")
    _rows(_corrections_rows(ctx.get("corrections", []), "qc", "applied"), "action_log")


def on_vetoed(vetoes: list, ctx: dict) -> None:
    now = ctx.get("now", time.time())
    _rows([(now, v["command"], "qc", f"vetoed:{v['plugin']}: {v['reason']}") for v in vetoes],
          "command_log")


def on_shadow(commands: list, ctx: dict) -> None:
    now = ctx.get("now", time.time())
    _rows([(now, c, "qc-shadow", "shadow") for c in commands], "command_log")
    _rows(_corrections_rows(ctx.get("corrections", []), "qc_shadow", "shadow"), "action_log")


def register_hooks(hooks) -> None:
    hooks.on("commands.sent", on_sent, priority=90)
    hooks.on("commands.vetoed", on_vetoed, priority=90)
    hooks.on("shadow.commands", on_shadow, priority=90)
