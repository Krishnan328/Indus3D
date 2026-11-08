"""
plugins/chat_actions.py  (E1)
------------------------------
Control the print from Telegram, not just receive alerts. OFF unless
INDUS3D_CHAT_ACTIONS=1 and both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set
(the same settings the notification channel uses).

Commands: /status  /pause  /resume  /cancel (then "/cancel confirm" within 60 s)
          /autopilot_off  /help
Safety:
  * only messages from TELEGRAM_CHAT_ID are accepted, and only from a private
    chat unless INDUS3D_CHAT_ALLOW_GROUP=1 (in a group, any member could act);
  * cancelling needs a second, explicit message;
  * the auto-pilot can be switched OFF remotely, never ON;
  * every accepted command is logged to action_log.

Telegram is the only chat service: Discord webhooks are send-only, so Discord
cannot receive commands.

GET /api/v1/plugins/chat_actions    status (never shows the token)
"""

import logging
import os
import time
from collections import deque

from plugins._common import Poller

PLUGIN_INFO = {
    "title": "Chat actions (Telegram)",
    "description": "Pause/resume/cancel and status from Telegram, restricted to your chat. Opt-in.",
}

CONFIRM_WINDOW_S = 60.0
HELP = ("/status — print state\n/pause\n/resume\n/cancel — then /cancel confirm\n"
        "/autopilot_off — disable the auto-pilot (cannot be enabled remotely)")


class PrinterActions:
    """Default implementation talking to Moonraker and the controller."""

    @staticmethod
    def _post(path):
        import requests
        from config.settings import settings
        return requests.post(f"{settings.moonraker_url}{path}", timeout=5).ok

    def pause(self):
        return self._post("/printer/print/pause")

    def resume(self):
        return self._post("/printer/print/resume")

    def cancel(self):
        return self._post("/printer/print/cancel")

    def autopilot_off(self):
        from digital_twin.quality_controller import quality_controller
        quality_controller.auto_pilot = False
        return True

    def status(self):
        from digital_twin.quality_controller import quality_controller as qc
        from plugins._common import latest_telemetry
        t = latest_telemetry()
        return (f"State: {t.get('print_state', 'unknown')} · {t.get('filename') or '-'}\n"
                f"Progress: {round((t.get('progress') or 0) * 100)}% · hotend {t.get('ext_temp')}/{t.get('ext_target')} °C "
                f"· bed {t.get('bed_temp')}/{t.get('bed_target')} °C\nAuto-pilot: {'on' if qc.auto_pilot else 'off'}")


class ChatActions:
    def __init__(self, token=None, chat_id=None, enabled=None, actions=None, send=None):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "") if token is None else token
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "") if chat_id is None else chat_id
        self.enabled = (os.environ.get("INDUS3D_CHAT_ACTIONS", "0") == "1") if enabled is None else enabled
        self.allow_group = os.environ.get("INDUS3D_CHAT_ALLOW_GROUP", "0") == "1"
        self.actions = actions or PrinterActions()
        self._send = send or self._telegram_send
        self.cancel_requested_at = None
        self.offset = 0
        self.log = deque(maxlen=50)
        self._poller = Poller(self.poll_once, 1.0, "chat-actions")

    @property
    def active(self):
        return bool(self.enabled and self.token and self.chat_id)

    # -- telegram io ---------------------------------------------------------
    def _telegram_send(self, text):
        import requests
        requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                      json={"chat_id": self.chat_id, "text": text}, timeout=10)

    def poll_once(self):
        import requests
        r = requests.get(f"https://api.telegram.org/bot{self.token}/getUpdates",
                         params={"timeout": 25, "offset": self.offset}, timeout=35)
        for u in r.json().get("result", []):
            self.offset = max(self.offset, u["update_id"] + 1)
            reply = self.handle(u)
            if reply:
                self._send(reply)

    # -- command handling (pure apart from `actions`) ------------------------
    def handle(self, update, now=None):
        now = now or time.time()
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        if str(chat.get("id")) != str(self.chat_id):
            logging.warning("chat_actions: ignored a message from an unauthorised chat")
            return None
        if chat.get("type") != "private" and not self.allow_group:
            return None
        text = (msg.get("text") or "").strip().lower()
        if not text.startswith("/"):
            return None
        cmd = text.split("@")[0] if " " not in text else text.split(None, 1)[0].split("@")[0]
        arg = text.split(None, 1)[1] if " " in text else ""

        if cmd in ("/start", "/help"):
            return HELP
        if cmd == "/status":
            return self.actions.status()
        if cmd == "/pause":
            return self._do("pause", self.actions.pause, now, "Print paused." )
        if cmd == "/resume":
            return self._do("resume", self.actions.resume, now, "Print resumed.")
        if cmd == "/autopilot_off":
            return self._do("autopilot_off", self.actions.autopilot_off, now, "Auto-pilot disabled.")
        if cmd == "/cancel":
            if arg == "confirm" and self.cancel_requested_at and now - self.cancel_requested_at <= CONFIRM_WINDOW_S:
                self.cancel_requested_at = None
                return self._do("cancel", self.actions.cancel, now, "Print cancelled.")
            self.cancel_requested_at = now
            return f"Send '/cancel confirm' within {int(CONFIRM_WINDOW_S)} s to cancel the print."
        return "Unknown command.\n" + HELP

    def _do(self, name, fn, now, ok_text):
        try:
            ok = bool(fn())
        except Exception as e:  # noqa: BLE001
            ok = False
            logging.error(f"chat_actions: {name} failed: {e}")
        self.log.appendleft({"t": now, "command": name, "ok": ok})
        self._audit(name, ok, now)
        return ok_text if ok else f"{name} failed — check the printer."

    @staticmethod
    def _audit(name, ok, now):
        try:
            from db.models import get_connection
            conn = get_connection()
            try:
                conn.execute("INSERT INTO action_log (timestamp, alert_id, gcode, description, status) "
                             "VALUES (?, ?, ?, ?, ?)",
                             (now, "chat_action", name.upper(), f"remote command from Telegram: {name}",
                              "executed" if ok else "failed"))
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            pass

    def tick(self, snap, ctx):
        if self.active:
            self._poller.start()

    def status(self):
        return {"enabled": self.enabled, "configured": bool(self.token and self.chat_id),
                "active": self.active, "allow_group": self.allow_group, "recent": list(self.log)}


chat = ChatActions()


def register_hooks(hooks) -> None:
    hooks.on("tick", chat.tick, priority=70)


def register_routes(app) -> None:
    from flask import Blueprint, jsonify

    bp = Blueprint("plugin_chat_actions", __name__, url_prefix="/api/v1/plugins/chat_actions")

    @bp.route("", methods=["GET"])
    def chat_status():
        return jsonify(chat.status())

    app.register_blueprint(bp)
