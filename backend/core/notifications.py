"""
core/notifications.py
-----------------------
Outbound notifications (Discord webhook, Telegram bot, and UI toasts) for
print lifecycle events, quality exclusions, and critical alerts.
Supports rich embeds, PZEM-004T energy statistics, and live camera snapshot
attachments.
"""

import json
import logging
import time
import requests
from collections import deque
from typing import Optional, Dict, Any
from datetime import datetime
from config.settings import settings

logger = logging.getLogger("indus3d.notifications")

# In-memory queue for UI toasts/browser notifications
_ui_notifications = deque(maxlen=25)


def pop_ui_notifications():
    global _ui_notifications
    out = list(_ui_notifications)
    _ui_notifications.clear()
    return out


def _send_ui(message: str, meta: Optional[Dict] = None) -> str:
    item = {"message": message, "ts": time.time()}
    if meta:
        item.update(meta)
    _ui_notifications.append(item)
    return "sent"


_TIMEOUT = 5


def capture_snapshot() -> Optional[bytes]:
    """Captures a single JPEG snapshot from the webcam stream."""
    stream_url = settings.webcam_stream_url
    if not stream_url:
        return None
    snap_url = stream_url.replace("action=stream", "action=snapshot") if "action=stream" in stream_url else stream_url
    try:
        res = requests.get(snap_url, timeout=3)
        if res.ok and len(res.content) > 100:
            return res.content
    except Exception as e:
        logger.debug(f"Snapshot capture for notification skipped: {e}")
    return None


def _send_discord(
    message: str,
    embed: Optional[Dict[str, Any]] = None,
    image_bytes: Optional[bytes] = None,
) -> str:
    """Sends notification to Discord webhook with optional embed and snapshot attachment."""
    if not settings.DISCORD_WEBHOOK_URL:
        return "skipped"

    try:
        payload = {}
        if message and not embed:
            payload["content"] = message
        elif message and embed:
            payload["content"] = message

        if embed:
            if image_bytes:
                embed["image"] = {"url": "attachment://snapshot.jpg"}
            payload["embeds"] = [embed]

        if image_bytes:
            files = {
                "file": ("snapshot.jpg", image_bytes, "image/jpeg"),
                "payload_json": (None, json.dumps(payload), "application/json"),
            }
            res = requests.post(
                settings.DISCORD_WEBHOOK_URL,
                files=files,
                timeout=_TIMEOUT,
            )
        else:
            res = requests.post(
                settings.DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=_TIMEOUT,
            )
        return "sent" if res.ok else "failed"
    except Exception as e:
        logger.warning(f"🔴 Discord notification failed: {e}")
        return "failed"


def _send_telegram(
    message: str,
    caption: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
) -> str:
    """Sends notification to Telegram bot with optional photo attachment."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        return "skipped"

    try:
        base_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        text_content = caption or message

        if image_bytes:
            files = {"photo": ("snapshot.jpg", image_bytes, "image/jpeg")}
            data = {
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "caption": text_content[:1024],
                "parse_mode": "HTML",
            }
            res = requests.post(f"{base_url}/sendPhoto", data=data, files=files, timeout=_TIMEOUT)
        else:
            data = {
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text_content,
                "parse_mode": "HTML",
            }
            res = requests.post(f"{base_url}/sendMessage", json=data, timeout=_TIMEOUT)
        return "sent" if res.ok else "failed"
    except Exception as e:
        logger.warning(f"🔴 Telegram notification failed: {e}")
        return "failed"


def notify(message: str) -> dict:
    """
    Standard plain-text notification backward compatible with existing code.
    Sends to Discord, Telegram, and UI toast queue.
    """
    outcome = {"sent": [], "skipped": [], "failed": []}
    for ch_name, fn in [("discord", _send_discord), ("telegram", _send_telegram)]:
        try:
            status = fn(message)
        except Exception as e:
            logger.warning(f"Notification {ch_name} raised: {e}")
            status = "failed"
        outcome[status].append(ch_name)

    _send_ui(message)
    outcome["sent"].append("ui")
    return outcome


def notify_print_started(
    filename: str,
    bed_temp: Optional[float] = None,
    ext_temp: Optional[float] = None,
    spool_name: Optional[str] = None,
) -> dict:
    """Dispatches a rich print-started notification."""
    now_str = datetime.now().strftime("%H:%M:%S")
    desc = f"**Job:** `{filename}`\n**Started:** `{now_str}`"
    fields = []
    if bed_temp:
        fields.append({"name": "Bed Target", "value": f"{bed_temp:.0f}°C", "inline": True})
    if ext_temp:
        fields.append({"name": "Extruder Target", "value": f"{ext_temp:.0f}°C", "inline": True})
    if spool_name:
        fields.append({"name": "Filament Spool", "value": str(spool_name), "inline": True})

    embed = {
        "title": "🚀 Indus3D: Print Started",
        "description": desc,
        "color": 0x3B82F6,  # Blue
        "fields": fields,
        "footer": {"text": "Indus3D Digital Twin"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    tg_msg = (
        f"<b>🚀 Indus3D: Print Started</b>\n"
        f"<b>Job:</b> <code>{filename}</code>\n"
        f"<b>Time:</b> {now_str}\n"
    )
    if bed_temp and ext_temp:
        tg_msg += f"<b>Targets:</b> Bed {bed_temp:.0f}°C | Hotend {ext_temp:.0f}°C\n"
    if spool_name:
        tg_msg += f"<b>Spool:</b> {spool_name}\n"

    image_bytes = capture_snapshot()
    outcome = {"sent": [], "skipped": [], "failed": []}

    try:
        s_d = _send_discord("", embed=embed, image_bytes=image_bytes)
        outcome[s_d].append("discord")
    except Exception:
        outcome["failed"].append("discord")

    try:
        s_t = _send_telegram(tg_msg, caption=tg_msg, image_bytes=image_bytes)
        outcome[s_t].append("telegram")
    except Exception:
        outcome["failed"].append("telegram")

    _send_ui(f"🚀 Print started: {filename}")
    outcome["sent"].append("ui")
    return outcome


def notify_print_completed(
    filename: str,
    duration_s: float = 0.0,
    energy_wh: float = 0.0,
    cost_usd: float = 0.0,
    filament_g: float = 0.0,
    excursions: int = 0,
) -> dict:
    """Dispatches a rich print-completed notification with PZEM energy metrics."""
    hours = int(duration_s // 3600)
    mins = int((duration_s % 3600) // 60)
    secs = int(duration_s % 60)
    dur_str = f"{hours}h {mins}m {secs}s" if hours > 0 else f"{mins}m {secs}s"

    energy_str = f"{energy_wh:.1f} Wh ({energy_wh/1000.0:.3f} kWh)" if energy_wh > 0 else "N/A"
    cost_str = f"${cost_usd:.3f}" if cost_usd > 0 else "$0.00"
    fil_str = f"{filament_g:.1f} g" if filament_g > 0 else "N/A"

    embed = {
        "title": "✅ Indus3D: Print Completed",
        "description": f"**Job:** `{filename}`\n**Status:** Successfully Finished",
        "color": 0x10B981,  # Emerald Green
        "fields": [
            {"name": "Duration", "value": dur_str, "inline": True},
            {"name": "Filament Used", "value": fil_str, "inline": True},
            {"name": "Energy Consumed", "value": energy_str, "inline": True},
            {"name": "Est. Cost", "value": cost_str, "inline": True},
            {"name": "Quality Audit", "value": f"{excursions} excursions" if excursions > 0 else "100% In-Spec", "inline": True},
        ],
        "footer": {"text": "Indus3D Digital Twin & AS9100 Quality Record"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    tg_msg = (
        f"<b>✅ Indus3D: Print Completed</b>\n"
        f"<b>Job:</b> <code>{filename}</code>\n"
        f"<b>Duration:</b> {dur_str}\n"
        f"<b>Energy:</b> {energy_str} | {cost_str}\n"
        f"<b>Filament:</b> {fil_str}\n"
        f"<b>Quality Audit:</b> {'⚠️ ' + str(excursions) + ' excursions' if excursions else '✨ 100% In-Spec'}\n"
    )

    image_bytes = capture_snapshot()
    outcome = {"sent": [], "skipped": [], "failed": []}

    try:
        s_d = _send_discord("", embed=embed, image_bytes=image_bytes)
        outcome[s_d].append("discord")
    except Exception:
        outcome["failed"].append("discord")

    try:
        s_t = _send_telegram(tg_msg, caption=tg_msg, image_bytes=image_bytes)
        outcome[s_t].append("telegram")
    except Exception:
        outcome["failed"].append("telegram")

    _send_ui(f"✅ Print completed: {filename} ({dur_str})")
    outcome["sent"].append("ui")
    return outcome


def notify_print_halted(
    filename: str,
    status: str,
    reason: Optional[str] = None,
) -> dict:
    """Dispatches a critical print-halted notification with attached snapshot."""
    image_bytes = capture_snapshot()
    reason_text = reason or f"Print transitioned to {status}"

    embed = {
        "title": f"🛑 Indus3D: Print {status.upper()}",
        "description": f"**Job:** `{filename}`\n**Reason:** {reason_text}",
        "color": 0xEF4444,  # Red
        "footer": {"text": "Indus3D Emergency Watchdog"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    tg_msg = (
        f"<b>🛑 Indus3D: Print {status.upper()}</b>\n"
        f"<b>Job:</b> <code>{filename}</code>\n"
        f"<b>Reason:</b> {reason_text}\n"
    )

    outcome = {"sent": [], "skipped": [], "failed": []}

    try:
        s_d = _send_discord("", embed=embed, image_bytes=image_bytes)
        outcome[s_d].append("discord")
    except Exception:
        outcome["failed"].append("discord")

    try:
        s_t = _send_telegram(tg_msg, caption=tg_msg, image_bytes=image_bytes)
        outcome[s_t].append("telegram")
    except Exception:
        outcome["failed"].append("telegram")

    _send_ui(f"🛑 Print {status}: {filename} - {reason_text}")
    outcome["sent"].append("ui")
    return outcome


def notify_critical_alert(
    alert_id: str,
    description: str,
) -> dict:
    """Dispatches a critical hardware/safety alarm notification with snapshot."""
    image_bytes = capture_snapshot()

    embed = {
        "title": f"⚠️ Indus3D Safety Alert: {alert_id}",
        "description": description,
        "color": 0xF59E0B,  # Amber/Warning
        "footer": {"text": "Indus3D Closed-Loop Safety Controller"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    tg_msg = (
        f"<b>⚠️ Indus3D Safety Alert: {alert_id}</b>\n"
        f"<b>Details:</b> {description}\n"
    )

    outcome = {"sent": [], "skipped": [], "failed": []}

    try:
        s_d = _send_discord("", embed=embed, image_bytes=image_bytes)
        outcome[s_d].append("discord")
    except Exception:
        outcome["failed"].append("discord")

    try:
        s_t = _send_telegram(tg_msg, caption=tg_msg, image_bytes=image_bytes)
        outcome[s_t].append("telegram")
    except Exception:
        outcome["failed"].append("telegram")

    _send_ui(f"⚠️ Alert [{alert_id}]: {description}")
    outcome["sent"].append("ui")
    return outcome


def notify_object_excluded(
    object_name: str,
    reason: Optional[str] = None,
) -> dict:
    """Dispatches a notification when an object is dynamically cancelled/excluded."""
    reason_str = f" ({reason})" if reason else ""
    msg = f"🚫 Indus3D: Object '{object_name}' was excluded from print{reason_str}"

    embed = {
        "title": "🚫 Indus3D: Object Excluded",
        "description": f"**Object:** `{object_name}`\n**Reason:** {reason or 'Manual / Automated defect exclusion'}",
        "color": 0xF59E0B,
        "footer": {"text": "Indus3D Adaptive Defect Exclusion"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    tg_msg = (
        f"<b>🚫 Indus3D: Object Excluded</b>\n"
        f"<b>Object:</b> <code>{object_name}</code>\n"
        f"<b>Reason:</b> {reason or 'Defect detected / Excluded by operator'}\n"
    )

    outcome = {"sent": [], "skipped": [], "failed": []}

    try:
        s_d = _send_discord("", embed=embed)
        outcome[s_d].append("discord")
    except Exception:
        outcome["failed"].append("discord")

    try:
        s_t = _send_telegram(tg_msg)
        outcome[s_t].append("telegram")
    except Exception:
        outcome["failed"].append("telegram")

    _send_ui(msg)
    outcome["sent"].append("ui")
    return outcome


def any_channel_configured() -> bool:
    return bool(
        settings.DISCORD_WEBHOOK_URL
        or (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
    )
