"""Seams between independently developed parts: the rich notifications and the plugin channel registry."""
from core import notifications as n


def test_rich_notifications_also_reach_plugin_registered_channels(monkeypatch):
    got = []

    def _send_probe(message):
        got.append(message)
        return "sent"
    monkeypatch.setattr(n, "_CHANNELS", [n._send_discord, n._send_telegram, _send_probe])
    monkeypatch.setattr(n, "capture_snapshot", lambda: None)
    n.notify_print_started("a.gcode")
    n.notify_print_completed("a.gcode", duration_s=3700)
    n.notify_print_halted("a.gcode", "error")
    n.notify_critical_alert("bed_runaway", "heater stuck on")
    n.notify_object_excluded("cube_1", reason="operator")
    assert n.flush(5)
    assert len(got) == 5 and "a.gcode" in got[0] and "1h" in got[1] and "cube_1" in got[4]


def test_plain_notify_uses_the_channel_registry(monkeypatch):
    seen = []

    def _send_probe(message):
        seen.append(message)
        return "sent"
    monkeypatch.setattr(n, "_CHANNELS", [_send_probe])
    out = n.notify("hello", wait=True)
    assert seen == ["hello"] and "probe" in out["sent"] and "ui" in out["sent"]


def test_a_failing_plugin_channel_never_breaks_a_print_notification(monkeypatch):
    def _send_bad(message):
        raise RuntimeError("down")
    monkeypatch.setattr(n, "_CHANNELS", [_send_bad])
    monkeypatch.setattr(n, "capture_snapshot", lambda: None)
    n.notify_print_completed("a.gcode")        # must not raise
    assert n.flush(5)
    assert n.notify("x", wait=True)["sent"].count("ui") == 1


def test_bed_crash_uses_the_rich_critical_alert_path(monkeypatch):
    from plugins import esp_bed_hub as eh
    seen = []
    monkeypatch.setattr(n, "notify_critical_alert", lambda alert_id, text: seen.append((alert_id, text)))
    hub = eh.EspHub(url="http://x", fetch=lambda u: {"connected": True, "crash_detected": True, "crash_info": {"peak_jerk_mg": 2450},
                    "bed_accel": {}, "chamber": {}, "last_update": 1.0, "daemon": {}},
                    store=eh.TelemetryStore(enabled=False), audit=lambda *a: None)
    hub.poll_once(now=1.0)
    assert len(seen) == 1 and seen[0][0] == "bed_crash" and "2450" in seen[0][1]
