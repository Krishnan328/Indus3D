"""The esp_bed_hub plugin against the REAL hub daemon (serial side faked by the daemon's own test double),
so a change on either side that breaks the other is caught here."""
import importlib.util
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parents[2] / "helpers" / "filament_sensor" / "esp8266_sensor_hub"
sys.path.insert(0, str(HUB / "scripts"))
_spec = importlib.util.spec_from_file_location("bedhub_fakes", HUB / "tests" / "conftest.py")
fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fakes)

import esp_bed_monitor_daemon as dm  # noqa: E402
from plugins import esp_bed_hub as eh  # noqa: E402


def wait_for(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stack(tmp_path):
    hub, moon = fakes.FakeHub(), fakes.MoonrakerStub()
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     data_dir=tmp_path, csv_log=False, async_actions=False, sleep=lambda s: time.sleep(0.001))
    threading.Thread(target=d.run_forever, daemon=True).start()
    srv = dm.serve(d, "127.0.0.1", 0)
    notes, audits = [], []
    plugin = eh.EspHub(url=f"http://127.0.0.1:{srv.server_address[1]}", notify=notes.append,
                       audit=lambda *a: audits.append(a),
                       store=eh.TelemetryStore(connect=lambda: sqlite3.connect(tmp_path / "t.db")))
    yield hub, moon, d, plugin, notes, audits
    d.stop()
    srv.shutdown()


def test_telemetry_chamber_and_storage_flow_through(stack):
    hub, moon, d, plugin, notes, audits = stack
    hub.push_telemetry()
    assert wait_for(lambda: d.last_update is not None)
    st = plugin.poll_once()
    assert st is not None and plugin.hub_ok
    assert plugin.chamber() == {"temp_c": 26.0, "humidity_pct": 45.5, "pressure_hpa": 1007.3}
    assert plugin.status()["bed_accel"]["y_mg"] == -395 and plugin.status()["crash_threshold_mg"] == 2000
    plugin.store.flush()
    conn = sqlite3.connect(plugin.store._conn().execute("PRAGMA database_list").fetchone()[2])
    row = conn.execute("SELECT chamber_temp_c, bed_accel_z_mg, crash_detected FROM telemetry_samples").fetchone()
    assert row == (26.0, -848.0, 0)


def test_crash_end_to_end_pause_notification_hold_and_reset(stack):
    hub, moon, d, plugin, notes, audits = stack
    hub.push_telemetry()
    assert wait_for(lambda: d.last_update is not None)
    plugin.poll_once()
    hub.push_crash_alert(jerk=2450)
    hub.push_telemetry()
    assert wait_for(lambda: any("/printer/print/pause" in c[1] for c in moon.calls))
    assert any("BED_CRASH_HANDLER JERK=2450" in str(c[2]) for c in moon.calls)
    assert wait_for(lambda: (plugin.poll_once(), plugin.crash_latched)[1])
    assert len(notes) == 1 and "2450" in notes[0] and "paused" in notes[0]
    assert audits and audits[0][2] == "paused"
    assert plugin.filter_commands(["M104 S210"], {}) == []                     # held while latched
    code, body = plugin.run_action("reset_crash", confirmed=True)              # real HTTP, real guard header
    assert (code, body["ok"]) == (200, True) and hub.latched is False
    hub.push_telemetry()
    assert wait_for(lambda: (plugin.poll_once(), not plugin.crash_latched)[1])
    assert plugin.filter_commands(["M104 S210"], {}) == ["M104 S210"]


def test_threshold_action_reaches_the_hub(stack):
    hub, moon, d, plugin, *_ = stack
    hub.push_telemetry()
    assert wait_for(lambda: d.last_update is not None)
    assert plugin.run_action("set_threshold", 2600, True)[0] == 200
    assert hub.threshold == 2600


def test_unplugged_hub_is_visible_through_the_daemon(stack):
    hub, moon, d, plugin, *_ = stack
    d.stale_after_s = 0.05
    hub.push_telemetry()
    assert wait_for(lambda: d.last_update is not None)
    time.sleep(0.2)
    plugin.poll_once()
    assert plugin.connected and not plugin.hub_ok and plugin.chamber() is None
