"""
plugins/host_alerts.py
-----------------------
Pushes host and Moonraker problems to the notification channels (Discord / Telegram / browser toast) even when
nobody has the System page open: Raspberry Pi under-voltage or throttling, component updates that became
available, a Moonraker older than the supported minimum, high-priority Moonraker announcements and Moonraker
components that failed to start.

Edge-triggered: every condition notifies ONCE when it appears and is re-armed when it clears (an update is
keyed on the version it would install, so the next release notifies again). The set of active conditions is
persisted in the plugin data dir, so a backend restart does not repeat notifications.

Read-only: it only asks Moonraker questions (the same ones as GET /api/v1/system/alerts). Skipped in
simulator mode and while Moonraker is unreachable (a switched-off printer is not an alert; the active set is
kept so nothing is re-announced when it comes back).

Environment
  INDUS3D_HOST_ALERTS=0              disable (default on)
  INDUS3D_HOST_ALERTS_INTERVAL_S     check period, default 300, minimum 30
  INDUS3D_MIN_MOONRAKER              minimum Moonraker version, default v0.9.0

GET /api/v1/plugins/host_alerts   active alert ids, last check
"""

import logging
import os
import threading
import time
from typing import Callable, List, Optional

from plugins._common import Poller, data_dir, notify_safe, read_json, write_json

PLUGIN_INFO = {
    "title": "Host alerts",
    "description": "Notifies once about under-voltage, throttling, pending updates, old Moonraker, announcements and failed components.",
}

DEFAULT_INTERVAL_S = 300.0
MIN_INTERVAL_S = 30.0
MAX_NOTES_PER_CHECK = 4
ICONS = {"critical": "🛑", "warning": "⚠️", "info": "ℹ️"}


def interval_s() -> float:
    try:
        return max(MIN_INTERVAL_S, float(os.environ.get("INDUS3D_HOST_ALERTS_INTERVAL_S", DEFAULT_INTERVAL_S)))
    except ValueError:
        return DEFAULT_INTERVAL_S


def enabled() -> bool:
    return os.environ.get("INDUS3D_HOST_ALERTS", "1") != "0"


class HostAlerts:
    def __init__(self, notify: Callable[[str], None] = notify_safe, state_path=None,
                 fetch: Optional[Callable[[], List[dict]]] = None):
        self.notify = notify
        self._state_path = state_path
        self._fetch = fetch or self._fetch_alerts
        self._lock = threading.Lock()
        self.active: dict = {}                # every alert id currently present (notified or not) -> its source
        self.last_check: Optional[float] = None
        self.last_error: Optional[str] = None
        self._loaded = False

    # -- persistence -------------------------------------------------------------
    def _file(self):
        return self._state_path or (data_dir() / "host_alerts.json")

    def _load(self):
        if not self._loaded:
            self._loaded = True
            saved = read_json(self._file(), {}).get("active", {})
            self.active = dict(saved) if isinstance(saved, dict) else {i: "" for i in saved}

    def _save(self):
        try:
            write_json(self._file(), {"active": self.active})
        except OSError as e:
            logging.info(f"host_alerts: could not save state: {e}")

    # -- data ----------------------------------------------------------------------
    @staticmethod
    def _fetch_alerts():
        """``(alerts, failed_sources)``: a section that errored must not make its alerts look cleared."""
        from api import system_host as sh
        secs = sh.fetch_sections(["proc_stats", "server_info", "updates", "announcements"], use_cache=False)
        source = {"proc_stats": "host", "server_info": "moonraker", "updates": "updates", "announcements": "announcements"}
        failed = {source[n] for n, s in secs.items() if not s["ok"] and not s["unsupported"]}
        return sh.compute_alerts(secs), failed

    # -- the check -------------------------------------------------------------------
    def check(self, now: Optional[float] = None) -> List[dict]:
        """One pass. Returns the alerts that were newly notified."""
        from api import system_host as sh
        now = now or time.time()
        with self._lock:
            self._load()
            self.last_check = now
            if sh.is_sim():
                self.last_error = "simulator"
                return []
            try:
                res = self._fetch()
                alerts, failed = res if isinstance(res, tuple) else (res, set())
            except sh.Unreachable as e:
                self.last_error = str(e)                      # printer off / Moonraker restarting: not an alert
                return []
            self.last_error = None
            current = {a["id"]: a["source"] for a in alerts}
            for aid, src in self.active.items():              # unknown while its section failed: keep as is
                if src in failed:
                    current.setdefault(aid, src)
            fresh = [a for a in alerts if a["id"] not in self.active and a["notify"]]
            changed = current != self.active
            self.active = current                             # anything that cleared is re-armed
            if changed:
                self._save()
        sent = fresh[:MAX_NOTES_PER_CHECK]
        for a in sent:
            self.notify(f"{ICONS.get(a['severity'], '')} Indus3D host: {a['title']}. {a['detail']}".strip())
        if len(fresh) > len(sent):
            self.notify(f"ℹ️ Indus3D host: {len(fresh) - len(sent)} more alert(s): see the System page")
        return fresh

    def status(self) -> dict:
        with self._lock:
            self._load()
            return {"enabled": enabled(), "interval_s": interval_s(), "active": sorted(self.active),
                    "last_check": self.last_check, "last_error": self.last_error}


monitor = HostAlerts()
_poller = Poller(lambda: monitor.check(), interval_s(), "host-alerts")


def _tick(snap, ctx):
    if enabled():
        _poller.start()


def register_hooks(hooks) -> None:
    hooks.on("tick", _tick, priority=51)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_host_alerts", __name__, url_prefix="/api/v1/plugins/host_alerts")

    @bp.route("", methods=["GET"])
    def host_alerts_status():
        return jsonify(monitor.status())

    app.register_blueprint(bp)
