"""
core/notifications.py
-----------------------
Outbound notifications (Discord webhook, Telegram bot) for print completion,
failure, and critical alerts. Both channels are optional and independent —
configure either, both, or neither via .env (see config/settings.py).

Deliberately NOT the same pattern as core/alert_actions.py's ALERT_ACTIONS
table: notifications are a side effect of an event, not a corrective action,
so this module has no dedup/re-arm state of its own. Callers (telemetry_
worker.py for print-state transitions, alert_actions.py for critical alerts)
are responsible for only calling this once per real event — see each call
site for how it avoids repeat-firing on every tick.

Adding a new channel: write a _send_<name>(message) -> bool function next to
the two below, add it to _CHANNELS, add its config to settings.py. That's it.
"""

import logging
import requests
import time
from collections import deque
from config.settings import settings

# In-memory queue for UI toasts/browser notifications
_ui_notifications = deque(maxlen=20)

def pop_ui_notifications():
    global _ui_notifications
    out = list(_ui_notifications)
    _ui_notifications.clear()
    return out

def _send_ui(message: str) -> str:
    _ui_notifications.append({"message": message, "ts": time.time()})
    return "sent"


_TIMEOUT = 5


def _send_discord(message: str) -> str:
    """Returns 'sent', 'skipped' (not configured), or 'failed'."""
    if not settings.DISCORD_WEBHOOK_URL:
        return "skipped"
    try:
        res = requests.post(
            settings.DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=_TIMEOUT,
        )
        return "sent" if res.ok else "failed"
    except Exception as e:
        logging.info(f"🔴 Discord notification failed: {e}")
        return "failed"


def _send_telegram(message: str) -> str:
    """Returns 'sent', 'skipped' (not configured), or 'failed'."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        return "skipped"
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": message},
            timeout=_TIMEOUT,
        )
        return "sent" if res.ok else "failed"
    except Exception as e:
        logging.info(f"🔴 Telegram notification failed: {e}")
        return "failed"


_CHANNELS = [_send_discord, _send_telegram, _send_ui]


def notify(message: str) -> dict:
    """
    Send `message` to every configured channel. Never raises — a
    notification failure must never be allowed to interrupt the telemetry
    loop or the alert-action pipeline that called this.
    Returns {"sent": [...], "skipped": [...], "failed": [...]} for logging/
    debugging, not for control flow — callers should not branch on this.
    """
    outcome = {"sent": [], "skipped": [], "failed": []}
    for channel in _CHANNELS:
        try:
            status = channel(message)
        except Exception as e:
            logging.info(f"🔴 Notification channel {channel.__name__} raised: {e}")
            status = "failed"
        outcome[status].append(channel.__name__)
    return outcome


def any_channel_configured() -> bool:
    return bool(
        settings.DISCORD_WEBHOOK_URL
        or (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
    )
