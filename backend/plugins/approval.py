"""
plugins/approval.py  (B1)
--------------------------
Approval mode: instead of sending corrections straight to the printer, hold
them until a human approves. Intended for the first prints with the auto-pilot
on, until you trust the loop.

OFF by default (INDUS3D_APPROVAL_MODE=1 or POST /mode turns it on; the runtime
toggle is not persisted). When on:

* every command except safety commands (PAUSE / M112 / CANCEL_PRINT) is held,
* only the newest held command per family is kept (a newer M221 replaces an
  older, unapproved one),
* a held command expires after INDUS3D_APPROVAL_TTL_S seconds (default 30):
  corrections are time-sensitive, so a stale one is never sent,
* approving sends it through the same path as an automatic command and
  records it in the audit trail like one. Approval requires a printing job,
  enabled autopilot and telemetry from the last two seconds.

GET  /api/v1/plugins/approval
POST /api/v1/plugins/approval/mode            {"enabled": true|false}
POST /api/v1/plugins/approval/<id>/approve | reject
POST /api/v1/plugins/approval/approve_all
"""

import os
import threading
import time
from collections import OrderedDict, deque

from core.plugin_hooks import ctx_veto
from core.job_tracker import is_new_job, job_ref
from plugins.arbiter import family_of

PLUGIN_INFO = {
    "title": "Approval mode",
    "description": "Optionally holds corrective commands until a human approves them.",
}

ALWAYS_PASS = {"PAUSE", "M112", "CANCEL_PRINT"}
MAX_CONTEXT_AGE_S = 2.0


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class Approval:
    def __init__(self, enabled=None, ttl_s=None):
        self.enabled = _truthy(os.environ.get("INDUS3D_APPROVAL_MODE", "0")) if enabled is None else enabled
        self.ttl_s = float(os.environ.get("INDUS3D_APPROVAL_TTL_S", 30)) if ttl_s is None else ttl_s
        self.pending: "OrderedDict[int, dict]" = OrderedDict()
        self.history = deque(maxlen=100)
        self._context = None
        self._next = 1
        self._lock = threading.Lock()

    def _expire(self, now):
        for pid in [p for p, i in self.pending.items() if now - i["ts"] > self.ttl_s]:
            self.history.appendleft({**self.pending.pop(pid), "outcome": "expired", "at": now})

    # hook ---------------------------------------------------------------
    def tick(self, snap, ctx):
        # The worker does not run a quality cycle while paused or idle.
        with self._lock:
            if self._context is not None:
                if ctx.get("source") != self._context.get("source"):
                    self._context = None
                else:
                    self._context.update(snap=dict(snap), now=ctx.get("now", time.time()))

    def filter(self, commands, ctx):
        if ctx.get("approved"):
            return commands
        with self._lock:
            self._context = dict(ctx)
        if not self.enabled:
            return commands
        now = ctx.get("now", time.time())
        kept = []
        with self._lock:
            self._expire(now)
            for cmd in commands:
                token = cmd.strip().split(None, 1)[0].upper() if cmd.strip() else ""
                if token in ALWAYS_PASS:
                    kept.append(cmd)
                    continue
                fam = family_of(cmd) or token
                for pid in [p for p, i in self.pending.items() if i["family"] == fam]:
                    self.history.appendleft({**self.pending.pop(pid), "outcome": "superseded", "at": now})
                pid = self._next
                self._next += 1
                self.pending[pid] = {"id": pid, "command": cmd, "family": fam, "ts": now,
                                     "source": ctx.get("source"), "job": job_ref(ctx.get("snap") or {})}
                ctx_veto(ctx, cmd, "approval", f"awaiting approval (#{pid})")
        return kept

    # actions ------------------------------------------------------------
    def decide(self, pid: int, approve: bool, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._expire(now)
            item = self.pending.pop(pid, None)
            if item is None:
                return None, "not found (already decided or expired)"
            if not approve:
                self.history.appendleft({**item, "outcome": "rejected", "at": now})
                return item, None
            ctx = dict(self._context or {})
        controller = ctx.get("controller")
        snap = ctx.get("snap") or {}
        safe = (self.enabled and ctx.get("send")
                and 0 <= now - ctx.get("now", 0) <= MAX_CONTEXT_AGE_S
                and bool(getattr(controller, "auto_pilot", ctx.get("autopilot", False)))
                and snap.get("print_state") == "printing"
                and item["source"] == ctx.get("source")
                and not is_new_job(item["job"], snap))
        if not safe:
            with self._lock:
                self.history.appendleft({**item, "outcome": "blocked", "at": now})
            return None, "approval blocked: fresh telemetry, autopilot and the original active job are required"
        from core.command_pipeline import dispatch_commands
        ctx.update(now=now, source="approval", approved=True, vetoes=[], corrections=[])
        results = dispatch_commands([item["command"]], ctx)
        ok = bool(results and results[0]["ok"])
        outcome = "approved" if ok else "send_failed"
        if not results:
            outcome = "blocked"
        with self._lock:
            self.history.appendleft({**item, "outcome": outcome, "at": now})
        if not results:
            return None, "approval blocked by current safety checks"
        return {**item, "ok": ok}, None

    def status(self):
        with self._lock:
            self._expire(time.time())
            return {"enabled": self.enabled, "ttl_s": self.ttl_s,
                    "pending": list(self.pending.values()), "history": list(self.history)}


approval = Approval()


def register_hooks(h) -> None:
    h.on("tick", approval.tick, priority=30)
    h.on("commands.filter", approval.filter, priority=30)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify, request

    bp = Blueprint("plugin_approval", __name__, url_prefix="/api/v1/plugins/approval")

    @bp.route("", methods=["GET"])
    def approval_status():
        return jsonify(approval.status())

    @bp.route("/mode", methods=["POST"])
    def approval_mode():
        enabled = (request.get_json(force=True, silent=True) or {}).get("enabled")
        if not isinstance(enabled, bool):
            return jsonify({"error": "'enabled' must be true or false"}), 400
        approval.enabled = enabled
        return jsonify(approval.status())

    def _decide(pid, ok):
        item, err = approval.decide(pid, ok)
        if err:
            return jsonify({"error": err}), 404 if "not found" in err else 409
        return jsonify(item)

    @bp.route("/<int:pid>/approve", methods=["POST"])
    def approve(pid):
        return _decide(pid, True)

    @bp.route("/<int:pid>/reject", methods=["POST"])
    def reject(pid):
        return _decide(pid, False)

    @bp.route("/approve_all", methods=["POST"])
    def approve_all():
        done = []
        for pid in list(approval.pending):
            item, err = approval.decide(pid, True)
            done.append(item or {"id": pid, "error": err})
        return jsonify({"results": done})

    app.register_blueprint(bp)
