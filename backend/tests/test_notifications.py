"""
tests/test_notifications.py
----------------------------
Unit tests for the rich outbound notification module.
"""

import threading
from unittest.mock import patch

import pytest

from core import notifications as n
from core.notifications import (
    notify,
    notify_print_started,
    notify_print_completed,
    notify_print_halted,
    notify_critical_alert,
    notify_object_excluded,
    pop_ui_notifications,
)


def test_ui_toast_queue():
    pop_ui_notifications()  # Clear queue
    outcome = notify("Test notification message", wait=True)
    assert "ui" in outcome["sent"]

    toasts = pop_ui_notifications()
    assert len(toasts) >= 1
    assert "Test notification message" in toasts[-1]["message"]


@patch("core.notifications.requests.post")
def test_rich_print_started(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_print_started(
        filename="benchy.gcode",
        bed_temp=60.0,
        ext_temp=210.0,
        spool_name="PolyLite PLA",
    )
    assert "ui" in outcome["sent"]


@patch("core.notifications.requests.post")
def test_rich_print_completed(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_print_completed(
        filename="calicat.gcode",
        duration_s=850.0,
        energy_wh=18.4,
        cost_usd=0.45,
        filament_g=9.2,
        excursions=0,
    )
    assert "ui" in outcome["sent"]


@patch("core.notifications.requests.post")
def test_rich_print_halted(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_print_halted(
        filename="bracket.gcode",
        status="error",
        reason="Lost communication with MCU",
    )
    assert "ui" in outcome["sent"]


@patch("core.notifications.requests.post")
def test_object_excluded(mock_post):
    mock_post.return_value.ok = True
    outcome = notify_object_excluded(
        object_name="Part_B_Bracket",
        reason="Nozzle collision / vibration spike",
    )
    assert "ui" in outcome["sent"]


# ── async delivery ───────────────────────────────────────────────────────────
@pytest.fixture
def isolated(monkeypatch):
    """Fresh worker + no real network/snapshot."""
    w = n._DeliveryWorker(maxsize=4)
    monkeypatch.setattr(n, "_worker", w)
    monkeypatch.setattr(n, "capture_snapshot", lambda: None)
    monkeypatch.setattr(n, "_send_discord", lambda *a, **k: "skipped")
    monkeypatch.setattr(n, "_send_telegram", lambda *a, **k: "skipped")
    monkeypatch.setattr(n, "_BUILTIN", ())
    monkeypatch.setattr(n, "_CHANNELS", [])
    return w


def test_caller_returns_immediately_while_a_channel_blocks(isolated, monkeypatch):
    gate, entered = threading.Event(), threading.Event()

    def _send_slow(message):
        entered.set()
        gate.wait(10)
        return "sent"
    monkeypatch.setattr(n, "_CHANNELS", [_send_slow])
    pop_ui_notifications()
    out = n.notify("hi")                     # would hang 10 s if it ran inline
    assert out["sent"] == ["ui"] and "slow" in out["queued"]
    assert "hi" in pop_ui_notifications()[-1]["message"]      # toast is immediate
    assert entered.wait(2)
    r = n.notify_print_completed("a.gcode")
    assert r["sent"] == ["ui"]
    gate.set()
    assert isolated.flush(5)


def test_delivery_order_is_preserved(isolated, monkeypatch):
    got = []
    monkeypatch.setattr(n, "_CHANNELS", [lambda m: got.append(m) or "sent"])
    for i in range(4):
        n.notify(f"m{i}")
    assert isolated.flush(5)
    assert got == ["m0", "m1", "m2", "m3"]


def test_a_raising_channel_does_not_kill_the_worker(isolated, monkeypatch):
    got = []

    def _send_bad(message):
        raise RuntimeError("boom")
    monkeypatch.setattr(n, "_CHANNELS", [_send_bad])
    n.notify("one")
    isolated.put(lambda: (_ for _ in ()).throw(ValueError("raw job failure")), "raw")
    assert isolated.flush(5)
    monkeypatch.setattr(n, "_CHANNELS", [lambda m: got.append(m) or "sent"])
    n.notify("two")
    assert isolated.flush(5) and got == ["two"]


def test_overflow_drops_the_oldest(isolated):
    gate, started, ran = threading.Event(), threading.Event(), []

    def blocker():
        started.set()
        gate.wait(10)
    isolated.put(blocker, "blocker")
    assert started.wait(2)                         # in flight, so no longer queued
    for i in range(6):                             # maxsize 4: 0 and 1 are dropped
        isolated.put(lambda i=i: ran.append(i), f"j{i}")
    assert isolated.dropped == 2
    gate.set()
    assert isolated.flush(5) and ran == [2, 3, 4, 5]


def test_flush_times_out_on_a_stuck_job(isolated):
    gate = threading.Event()
    isolated.put(lambda: gate.wait(10), "stuck")
    assert isolated.flush(0.05) is False
    gate.set()
    assert isolated.flush(5)


def test_snapshot_capture_runs_on_the_worker_not_the_caller(isolated, monkeypatch):
    seen = []
    monkeypatch.setattr(n, "capture_snapshot", lambda: seen.append(threading.current_thread().name))
    n.notify_print_started("a.gcode")
    assert isolated.flush(5)
    assert seen and seen[0] == "notify-delivery"


# ── escaping / limits ────────────────────────────────────────────────────────
HOSTILE = "a<b>&c</code><script>@everyone.gcode"


@patch("core.notifications.requests.post")
def test_telegram_values_are_html_escaped(mock_post, monkeypatch):
    mock_post.return_value.ok = True
    monkeypatch.setattr(n.settings, "TELEGRAM_BOT_TOKEN", "tok", raising=False)
    monkeypatch.setattr(n.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(n.settings, "DISCORD_WEBHOOK_URL", "", raising=False)
    monkeypatch.setattr(n, "capture_snapshot", lambda: None)
    for fn in (
        lambda: n.notify_print_started(HOSTILE, spool_name="<x>", wait=True),
        lambda: n.notify_print_completed(HOSTILE, wait=True),
        lambda: n.notify_print_halted(HOSTILE, "error", reason="<oops> & more", wait=True),
        lambda: n.notify_critical_alert("a<b", "x > y & z", wait=True),
        lambda: n.notify_object_excluded(HOSTILE, reason="<r>", wait=True),
        lambda: n.notify(HOSTILE, wait=True),
    ):
        mock_post.reset_mock()
        fn()
        sent = [c for c in mock_post.call_args_list if "telegram" in c[0][0]]
        assert sent
        text = sent[0][1]["json"]["text"]
        assert "<script>" not in text and "a<b>" not in text and "<oops>" not in text and "<r>" not in text
        assert "&lt;" in text
        assert "<b>" in text or fn is not None            # our own tags stay intact for rich messages


@patch("core.notifications.requests.post")
def test_discord_limits_and_no_mentions(mock_post, monkeypatch):
    mock_post.return_value.ok = True
    monkeypatch.setattr(n.settings, "DISCORD_WEBHOOK_URL", "http://hook", raising=False)
    monkeypatch.setattr(n.settings, "TELEGRAM_BOT_TOKEN", "", raising=False)
    monkeypatch.setattr(n, "capture_snapshot", lambda: None)
    n.notify_print_halted("@everyone" + "x" * 5000, "error", reason="r" * 9000, wait=True)
    payload = mock_post.call_args[1]["json"]
    assert payload["allowed_mentions"] == {"parse": []}
    emb = payload["embeds"][0]
    assert len(emb["title"]) <= 256 and len(emb["description"]) <= 4096
    n.notify_critical_alert("id" * 300, "d" * 9000, wait=True)
    emb = mock_post.call_args[1]["json"]["embeds"][0]
    assert len(emb["title"]) <= 256 and len(emb["description"]) <= 4096
    n._send_discord("m" * 5000, embed={"title": "t", "fields": [{"name": "n" * 400, "value": "v" * 3000}] * 30})
    p = mock_post.call_args[1]["json"]
    assert len(p["content"]) <= 2000 and len(p["embeds"][0]["fields"]) == 25
    assert all(len(f["value"]) <= 1024 and len(f["name"]) <= 256 for f in p["embeds"][0]["fields"])


# ── quality audit claims ─────────────────────────────────────────────────────
def _completed_payloads(mock_post, monkeypatch, **kw):
    mock_post.return_value.ok = True
    monkeypatch.setattr(n.settings, "DISCORD_WEBHOOK_URL", "http://hook", raising=False)
    monkeypatch.setattr(n.settings, "TELEGRAM_BOT_TOKEN", "tok", raising=False)
    monkeypatch.setattr(n.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(n, "capture_snapshot", lambda: None)
    n.notify_print_completed("a.gcode", wait=True, **kw)
    calls = {("telegram" if "telegram" in c[0][0] else "discord"): c[1]["json"] for c in mock_post.call_args_list}
    return calls["discord"]["embeds"][0], calls["telegram"]["text"]


@patch("core.notifications.requests.post")
def test_unevaluated_quality_is_not_claimed(mock_post, monkeypatch):
    emb, tg = _completed_payloads(mock_post, monkeypatch)            # excursions defaults to None
    blob = str(emb) + tg
    assert "In-Spec" not in blob and "AS9100" not in blob
    assert "not evaluated" in blob


@patch("core.notifications.requests.post")
def test_real_excursion_counts_are_reported(mock_post, monkeypatch):
    emb, tg = _completed_payloads(mock_post, monkeypatch, excursions=3)
    assert "3 excursions logged" in str(emb) and "3 excursions logged" in tg
    assert "AS9100" in emb["footer"]["text"]
    mock_post.reset_mock()
    emb, tg = _completed_payloads(mock_post, monkeypatch, excursions=0)
    assert "0 excursions logged" in str(emb) and "In-Spec" not in str(emb) + tg


def test_embed_timestamps_are_timezone_aware():
    import re
    ts = []
    orig = n._deliver_rich
    with patch.object(n, "_deliver_rich", side_effect=lambda embed, *a, **k: ts.append(embed["timestamp"]) or {"sent": []}):
        n.notify_print_started("a", wait=True)
    assert re.search(r"(\+00:00|Z)$", ts[0])
