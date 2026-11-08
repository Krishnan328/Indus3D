"""
core/notifications.py
-----------------------
Outbound notifications (Discord webhook, Telegram bot, and UI toasts) for
print lifecycle events, quality exclusions, and critical alerts.
Supports rich embeds, PZEM-004T energy statistics, and live camera snapshot
attachments.

Delivery never runs on the caller's thread: every notify* function adds the
UI toast immediately (cheap, local) and enqueues the network work (snapshot
capture, Discord, Telegram, plugin channels) onto one bounded background
worker. Pass ``wait=True`` to deliver inline (tests, scripts).
"""

import html
import json
import logging
import threading
import time
import requests
from collections import deque
from typing import Callable, Optional, Dict, Any
from datetime import datetime, timezone
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

# Discord hard limits (https://discord.com/developers/docs/resources/message)
_D_TITLE, _D_DESC, _D_FIELD_NAME, _D_FIELD_VALUE, _D_FOOTER, _D_CONTENT, _D_FIELDS = 256, 4096, 256, 1024, 2048, 2000, 25
_NAME_MAX = 200      # filenames / reasons are clipped to this when interpolated
_REASON_MAX = 300
_NO_MENTIONS = {"parse": []}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: Any, limit: int) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def _h(value: Any, limit: int = _NAME_MAX) -> str:
    """HTML-escape (and clip) a value for Telegram's parse_mode=HTML."""
    return html.escape(_clip(value, limit), quote=False)


def _md(value: Any, limit: int = _NAME_MAX) -> str:
    """Clip a value for use inside a Discord `code span` (a backtick would end the span)."""
    return _clip(value, limit).replace("`", "'")


def _clip_embed(embed: Dict[str, Any]) -> Dict[str, Any]:
    """Truncate an embed to Discord's limits so a long filename cannot make the whole post fail."""
    out = dict(embed)
    if "title" in out:
        out["title"] = _clip(out["title"], _D_TITLE)
    if "description" in out:
        out["description"] = _clip(out["description"], _D_DESC)
    if "fields" in out:
        out["fields"] = [
            dict(f, name=_clip(f.get("name"), _D_FIELD_NAME) or "-", value=_clip(f.get("value"), _D_FIELD_VALUE) or "-")
            for f in out["fields"][:_D_FIELDS]
        ]
    if isinstance(out.get("footer"), dict) and "text" in out["footer"]:
        out["footer"] = dict(out["footer"], text=_clip(out["footer"]["text"], _D_FOOTER))
    return out


# ── background delivery worker ───────────────────────────────────────────────
class _DeliveryWorker:
    """One daemon thread draining a bounded FIFO. When full, the OLDEST pending item is dropped (and logged):
    a fresh alert matters more than a stale one. Exceptions in a job never kill the thread."""

    def __init__(self, maxsize: int = 64):
        self.maxsize = maxsize
        self._q: deque = deque()
        self._cond = threading.Condition()
        self._busy = False
        self._thread: Optional[threading.Thread] = None
        self.dropped = 0

    def put(self, fn: Callable[[], Any], label: str = "") -> None:
        with self._cond:
            while len(self._q) >= self.maxsize:
                old = self._q.popleft()
                self.dropped += 1
                logger.warning(f"Notification queue full ({self.maxsize}); dropped oldest item '{old[1]}'")
            self._q.append((fn, label))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="notify-delivery", daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._q:
                    self._cond.wait()
                fn, label = self._q.popleft()
                self._busy = True
            try:
                fn()
            except BaseException as e:  # noqa: BLE001 - the worker must survive anything a channel does
                logger.warning(f"Notification delivery '{label}' raised: {e!r}")
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until everything queued so far has been delivered. True if drained within the timeout."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._q or self._busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True


_worker = _DeliveryWorker()


def flush(timeout: float = 5.0) -> bool:
    """Wait for queued notifications to be delivered (used by tests and shutdown)."""
    return _worker.flush(timeout)


def capture_snapshot() -> Optional[bytes]:
    """Captures a single JPEG snapshot from the webcam stream (blocks up to 3 s: call from the worker)."""
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
        payload: Dict[str, Any] = {"allowed_mentions": _NO_MENTIONS}   # a filename like "@everyone" must not ping
        if message:
            payload["content"] = _clip(message, _D_CONTENT)

        if embed:
            embed = _clip_embed(embed)
            if image_bytes:
                embed["image"] = {"url": "attachment://snapshot.jpg"}
            payload["embeds"] = [embed]

        if image_bytes:
            files = {
                "file": ("snapshot.jpg", image_bytes, "image/jpeg"),
                "payload_json": (None, json.dumps(payload), "application/json"),
            }
            res = requests.post(settings.DISCORD_WEBHOOK_URL, files=files, timeout=_TIMEOUT)
        else:
            res = requests.post(settings.DISCORD_WEBHOOK_URL, json=payload, timeout=_TIMEOUT)
        return "sent" if res.ok else "failed"
    except Exception as e:
        logger.warning(f"🔴 Discord notification failed: {e}")
        return "failed"


def _send_telegram(
    message: str,
    caption: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
) -> str:
    """Sends notification to Telegram bot with optional photo attachment.

    ``caption`` (when given) is ready-made HTML built by the rich notify_* functions, with every value already
    escaped. ``message`` on its own is plain text (the generic channel signature) and is escaped here.
    """
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        return "skipped"

    try:
        base_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        text_content = caption if caption is not None else html.escape(message or "", quote=False)

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
                "text": text_content[:4096],
                "parse_mode": "HTML",
            }
            res = requests.post(f"{base_url}/sendMessage", json=data, timeout=_TIMEOUT)
        return "sent" if res.ok else "failed"
    except Exception as e:
        logger.warning(f"🔴 Telegram notification failed: {e}")
        return "failed"


# Extra outbound channels registered by plugins (webhook_events appends _send_webhook). Each is
# fn(message: str) -> "sent" | "skipped" | "failed", and enforces its own network timeout.
# Discord, Telegram and the UI toast queue are built in.
_CHANNELS = [_send_discord, _send_telegram]
_BUILTIN = (_send_discord, _send_telegram)


def _ch_name(fn) -> str:
    return getattr(fn, "__name__", str(fn)).replace("_send_", "")


def _extra_channels():
    return [ch for ch in list(_CHANNELS) if ch not in _BUILTIN]


def _new_outcome() -> dict:
    return {"sent": [], "skipped": [], "failed": []}


def _run_plugin_channels(message: str, outcome: dict) -> None:
    for channel in _extra_channels():
        try:
            status = channel(message)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Notification channel {_ch_name(channel)} raised: {e}")
            status = "failed"
        outcome.setdefault(status, []).append(_ch_name(channel))


def _deliver_rich(embed: Dict[str, Any], tg_html: str, plain: str, with_snapshot: bool = True) -> dict:
    """Synchronous delivery of one rich event. Runs on the worker (or inline with wait=True)."""
    image_bytes = capture_snapshot() if with_snapshot else None
    outcome = _new_outcome()
    for name, call in (
        ("discord", lambda: _send_discord("", embed=embed, image_bytes=image_bytes)),
        ("telegram", lambda: _send_telegram(tg_html, caption=tg_html, image_bytes=image_bytes)),
    ):
        try:
            outcome.setdefault(call(), []).append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Notification {name} raised: {e}")
            outcome["failed"].append(name)
    _run_plugin_channels(plain, outcome)
    return outcome


def _deliver_plain(message: str) -> dict:
    outcome = _new_outcome()
    for fn in list(_CHANNELS):
        try:
            status = fn(message)
        except Exception as e:
            logger.warning(f"Notification {_ch_name(fn)} raised: {e}")
            status = "failed"
        outcome.setdefault(status, []).append(_ch_name(fn))
    return outcome


def _dispatch(deliver: Callable[[], dict], plain: str, wait: bool, label: str) -> dict:
    """UI toast now; the network work on the worker (or inline when wait=True)."""
    _send_ui(plain)
    if wait:
        outcome = deliver()
        outcome["sent"].append("ui")
        return outcome
    _worker.put(deliver, label)
    return {"sent": ["ui"], "queued": ["discord", "telegram"] + [_ch_name(c) for c in _extra_channels()]}


def _publish_ui_and_extra(message: str) -> None:
    """UI toast plus every plugin-registered channel as plain text (kept for plugins/tests that call it)."""
    _send_ui(message)
    _run_plugin_channels(message, _new_outcome())


def notify(message: str, wait: bool = False) -> dict:
    """
    Plain-text notification to every registered channel plus the UI toast queue.
    Returns immediately with ``{"sent": ["ui"], "queued": [...]}``; ``wait=True`` delivers inline and returns the
    per-channel outcome (``sent``/``skipped``/``failed``).
    """
    return _dispatch(lambda: _deliver_plain(message), message, wait, "notify")


def notify_print_started(
    filename: str,
    bed_temp: Optional[float] = None,
    ext_temp: Optional[float] = None,
    spool_name: Optional[str] = None,
    wait: bool = False,
) -> dict:
    """Dispatches a rich print-started notification."""
    now_str = datetime.now().strftime("%H:%M:%S")
    desc = f"**Job:** `{_md(filename)}`\n**Started:** `{now_str}`"
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
        "timestamp": _now_iso(),
    }

    tg_msg = (
        f"<b>🚀 Indus3D: Print Started</b>\n"
        f"<b>Job:</b> <code>{_h(filename)}</code>\n"
        f"<b>Time:</b> {now_str}\n"
    )
    if bed_temp and ext_temp:
        tg_msg += f"<b>Targets:</b> Bed {bed_temp:.0f}°C | Hotend {ext_temp:.0f}°C\n"
    if spool_name:
        tg_msg += f"<b>Spool:</b> {_h(spool_name)}\n"

    plain = f"🚀 Print started: {filename}"
    return _dispatch(lambda: _deliver_rich(embed, tg_msg, plain), plain, wait, "print_started")


def notify_print_completed(
    filename: str,
    duration_s: float = 0.0,
    energy_wh: float = 0.0,
    cost_usd: float = 0.0,
    filament_g: float = 0.0,
    excursions: Optional[int] = None,
    wait: bool = False,
) -> dict:
    """Dispatches a rich print-completed notification with PZEM energy metrics.

    ``excursions`` is the number of logged quality excursions during the print. ``None`` (the default) means the
    quality audit was not evaluated: nothing is claimed about quality and the AS9100 footer is omitted.
    """
    hours = int(duration_s // 3600)
    mins = int((duration_s % 3600) // 60)
    secs = int(duration_s % 60)
    dur_str = f"{hours}h {mins}m {secs}s" if hours > 0 else f"{mins}m {secs}s"

    energy_str = f"{energy_wh:.1f} Wh ({energy_wh/1000.0:.3f} kWh)" if energy_wh > 0 else "N/A"
    cost_str = f"${cost_usd:.3f}" if cost_usd > 0 else "$0.00"
    fil_str = f"{filament_g:.1f} g" if filament_g > 0 else "N/A"

    if excursions is None:
        audit_plain, audit_tg = "not evaluated", "not evaluated"
        footer = "Indus3D Digital Twin"
    elif excursions > 0:
        audit_plain, audit_tg = f"{excursions} excursions logged", f"⚠️ {excursions} excursions logged"
        footer = "Indus3D Digital Twin & AS9100 Quality Record"
    else:
        audit_plain, audit_tg = "0 excursions logged", "0 excursions logged"
        footer = "Indus3D Digital Twin & AS9100 Quality Record"

    embed = {
        "title": "✅ Indus3D: Print Completed",
        "description": f"**Job:** `{_md(filename)}`\n**Status:** Successfully Finished",
        "color": 0x10B981,  # Emerald Green
        "fields": [
            {"name": "Duration", "value": dur_str, "inline": True},
            {"name": "Filament Used", "value": fil_str, "inline": True},
            {"name": "Energy Consumed", "value": energy_str, "inline": True},
            {"name": "Est. Cost", "value": cost_str, "inline": True},
            {"name": "Quality audit", "value": audit_plain, "inline": True},
        ],
        "footer": {"text": footer},
        "timestamp": _now_iso(),
    }

    tg_msg = (
        f"<b>✅ Indus3D: Print Completed</b>\n"
        f"<b>Job:</b> <code>{_h(filename)}</code>\n"
        f"<b>Duration:</b> {dur_str}\n"
        f"<b>Energy:</b> {_h(energy_str)} | {cost_str}\n"
        f"<b>Filament:</b> {fil_str}\n"
        f"<b>Quality audit:</b> {audit_tg}\n"
    )

    plain = f"✅ Print completed: {filename} ({dur_str})"
    return _dispatch(lambda: _deliver_rich(embed, tg_msg, plain), plain, wait, "print_completed")


def notify_print_halted(
    filename: str,
    status: str,
    reason: Optional[str] = None,
    wait: bool = False,
) -> dict:
    """Dispatches a critical print-halted notification with attached snapshot."""
    reason_text = reason or f"Print transitioned to {status}"

    embed = {
        "title": f"🛑 Indus3D: Print {str(status).upper()}",
        "description": f"**Job:** `{_md(filename)}`\n**Reason:** {_clip(reason_text, _REASON_MAX)}",
        "color": 0xEF4444,  # Red
        "footer": {"text": "Indus3D Emergency Watchdog"},
        "timestamp": _now_iso(),
    }

    tg_msg = (
        f"<b>🛑 Indus3D: Print {_h(str(status).upper())}</b>\n"
        f"<b>Job:</b> <code>{_h(filename)}</code>\n"
        f"<b>Reason:</b> {_h(reason_text, _REASON_MAX)}\n"
    )

    plain = f"🛑 Print {status}: {filename} - {reason_text}"
    return _dispatch(lambda: _deliver_rich(embed, tg_msg, plain), plain, wait, "print_halted")


def notify_critical_alert(
    alert_id: str,
    description: str,
    wait: bool = False,
) -> dict:
    """Dispatches a critical hardware/safety alarm notification with snapshot."""
    embed = {
        "title": f"⚠️ Indus3D Safety Alert: {alert_id}",
        "description": description,
        "color": 0xF59E0B,  # Amber/Warning
        "footer": {"text": "Indus3D Closed-Loop Safety Controller"},
        "timestamp": _now_iso(),
    }

    tg_msg = (
        f"<b>⚠️ Indus3D Safety Alert: {_h(alert_id)}</b>\n"
        f"<b>Details:</b> {_h(description, 1500)}\n"
    )

    plain = f"⚠️ Alert [{alert_id}]: {description}"
    return _dispatch(lambda: _deliver_rich(embed, tg_msg, plain), plain, wait, "critical_alert")


def notify_object_excluded(
    object_name: str,
    reason: Optional[str] = None,
    wait: bool = False,
) -> dict:
    """Dispatches a notification when an object is dynamically cancelled/excluded."""
    reason_str = f" ({reason})" if reason else ""
    msg = f"🚫 Indus3D: Object '{object_name}' was excluded from print{reason_str}"

    embed = {
        "title": "🚫 Indus3D: Object Excluded",
        "description": f"**Object:** `{_md(object_name)}`\n**Reason:** {_clip(reason or 'Manual / Automated defect exclusion', _REASON_MAX)}",
        "color": 0xF59E0B,
        "footer": {"text": "Indus3D Adaptive Defect Exclusion"},
        "timestamp": _now_iso(),
    }

    tg_msg = (
        f"<b>🚫 Indus3D: Object Excluded</b>\n"
        f"<b>Object:</b> <code>{_h(object_name)}</code>\n"
        f"<b>Reason:</b> {_h(reason or 'Defect detected / Excluded by operator', _REASON_MAX)}\n"
    )

    return _dispatch(
        lambda: _deliver_rich(embed, tg_msg, msg, with_snapshot=False), msg, wait, "object_excluded")


def any_channel_configured() -> bool:
    return bool(
        settings.DISCORD_WEBHOOK_URL
        or (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
    )
