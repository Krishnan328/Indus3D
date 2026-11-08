"""GET /api/v1/printer/thermal_history and GET /api/v1/printer/sensors (api/routes/thermal.py)."""
import sqlite3
import time
from datetime import datetime, timezone

import pytest
from flask import Flask

from api import moonraker_util as mu
from api.routes import thermal

NOW = 1_800_000_000.0


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE twin_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL,
        ext_temp REAL, ext_target REAL, bed_temp REAL, bed_target REAL, print_state TEXT)""")
    conn.execute("""CREATE TABLE telemetry_samples (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_utc TEXT NOT NULL,
        chamber_temp_c REAL, chamber_humidity_pct REAL, chamber_pressure_hpa REAL)""")
    conn.commit()
    conn.close()
    monkeypatch.setattr(thermal, "_conn", lambda: sqlite3.connect(path))
    return path


def put_twin(path, rows):
    c = sqlite3.connect(path)
    c.executemany("INSERT INTO twin_snapshots (timestamp, ext_temp, ext_target, bed_temp, bed_target, print_state) VALUES (?,?,?,?,?,?)", rows)
    c.commit(); c.close()


def put_hub(path, rows):
    c = sqlite3.connect(path)
    c.executemany("INSERT INTO telemetry_samples (timestamp_utc, chamber_temp_c, chamber_humidity_pct) VALUES (?,?,?)",
                  [(iso(t), temp, hum) for t, temp, hum in rows])
    c.commit(); c.close()


def store(n=1200, chamber=False):
    s = {"extruder": {"temperatures": [200.0] * n, "targets": [210.0] * n, "powers": [0.5] * n},
         "heater_bed": {"temperatures": [60.0] * n, "targets": [60.0] * n, "powers": [0.2] * n},
         "temperature_sensor mcu": {"temperatures": [40.0] * n},
         "temperature_fan pi_fan": {"temperatures": [45.0] * n, "targets": [50.0] * n, "speeds": [0.3] * n}}
    if chamber:
        s["heater_generic chamber"] = {"temperatures": [35.0] * n, "targets": [40.0] * n}
    return s


@pytest.fixture
def client(monkeypatch, db):
    import workers
    monkeypatch.setattr(workers, "_active_worker", None)
    monkeypatch.setattr(thermal.time, "time", lambda: NOW)
    state = {"store": store(), "sensors": None}
    monkeypatch.setattr(mu, "get_json", lambda path, timeout=5: state_get(state, path))
    app = Flask(__name__)
    app.register_blueprint(thermal.thermal_bp, url_prefix="/api/v1/printer")
    c = app.test_client()
    c.state, c.db, c.mp = state, db, monkeypatch
    return c


def state_get(state, path):
    value = state["store"] if path == "/server/temperature_store" else state.get(path)
    if isinstance(value, Exception):
        raise value
    if value is None:
        raise mu.MoonrakerError(f"Moonraker answered 404 for {path}")
    return value


def hist(c, **params):
    return c.get("/api/v1/printer/thermal_history", query_string=params)


# ── pure helpers ──────────────────────────────────────────────────────────────
def test_bucket_averages_and_skips_nones():
    ts = [0, 1, 2, 3, 4, 5]
    t, v = thermal.bucket(ts, [1, 3, None, 5, 7, 9], 2)
    assert t == [0, 2, 4] and v == [2.0, 5.0, 8.0]
    assert thermal.bucket(ts, [1, 2, 3, 4, 5, 6], 1) == (ts, [1, 2, 3, 4, 5, 6])
    assert thermal.bucket([], [], 5) == ([], [])


def test_moonraker_series_names_timestamps_and_extras():
    out = thermal.moonraker_series(store(n=3), NOW)
    assert set(out) >= {"extruder", "extruder.target", "extruder.power", "heater_bed", "temperature_sensor mcu",
                        "temperature_fan pi_fan", "temperature_fan pi_fan.target", "temperature_fan pi_fan.speed"}
    assert out["extruder"]["t"] == [NOW - 2, NOW - 1, NOW]
    assert thermal.moonraker_series({}, NOW) == {} and thermal.moonraker_series({"x": "bad"}, NOW) == {}


# ── validation ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("params", [{"minutes": "abc"}, {"minutes": 0}, {"minutes": 1441}, {"minutes": -5},
                                    {"minutes": "nan"}, {"minutes": 5, "max_points": "x"}])
def test_bad_parameters_are_400(client, params):
    assert hist(client, **params).status_code == 400


# ── short range: Moonraker store ──────────────────────────────────────────────
def test_short_range_comes_from_the_moonraker_store(client):
    d = hist(client, minutes=5).get_json()
    assert d["ok"] and d["sources"]["moonraker"]["ok"] and "twin_snapshots" not in d["sources"]
    s = d["series"]
    assert {"extruder", "extruder.target", "extruder.power", "heater_bed", "temperature_sensor mcu"} <= set(s)
    assert s["extruder"]["t"][-1] == NOW and min(s["extruder"]["t"]) >= NOW - 300
    assert len(s["extruder"]["t"]) <= 600 and len(s["extruder"]["t"]) == len(s["extruder"]["v"])
    assert s["temperature_fan pi_fan.speed"]["v"][0] == 0.3


def test_max_points_bounds_the_series(client):
    d = hist(client, minutes=20, max_points=50).get_json()
    assert len(d["series"]["extruder"]["t"]) <= 50 + 1
    d = hist(client, minutes=20, max_points=5).get_json()           # clamped up to the minimum
    assert len(d["series"]["extruder"]["t"]) >= 20


# ── long range: SQLite ────────────────────────────────────────────────────────
def test_long_range_fills_the_time_before_the_moonraker_window_from_twin_snapshots(client):
    put_twin(client.db, [(NOW - 3000 + i * 10, 150 + i % 5, 200, 55, 60, "printing") for i in range(200)])
    put_twin(client.db, [(NOW - 100, 0, 0, 0, 0, "offline")])             # a disconnected sample is not a 0 °C reading
    d = hist(client, minutes=60).get_json()
    assert d["ok"] and d["sources"]["twin_snapshots"]["ok"]
    t, v = d["series"]["extruder"]["t"], d["series"]["extruder"]["v"]
    assert t == sorted(t) and t[0] < NOW - 1500 and t[-1] == NOW
    assert 0 not in v[: len(v) // 2]
    assert 150 <= v[0] <= 155 and v[-1] == 200.0                           # DB first, then the Moonraker values
    assert "heater_bed.target" in d["series"]


def test_chamber_falls_back_to_the_hub_when_klipper_has_none(client):
    put_hub(client.db, [(NOW - 600 + i * 10, 28 + i * 0.01, 41.0) for i in range(60)])
    d = hist(client, minutes=60).get_json()
    assert d["chamber_source"] == "esp_bed_hub"
    assert d["series"]["esp_bed_hub.chamber"]["v"][0] == 28.0
    assert d["series"]["esp_bed_hub.humidity"]["v"][0] == 41.0
    assert d["sources"]["esp_bed_hub"]["ok"]


def test_klipper_chamber_sensor_wins_but_hub_humidity_is_kept(client):
    client.state["store"] = store(chamber=True)
    put_hub(client.db, [(NOW - 600 + i * 10, 28.0, 41.0) for i in range(30)])
    d = hist(client, minutes=60).get_json()
    assert d["chamber_source"] == "klipper"
    assert "heater_generic chamber" in d["series"] and "esp_bed_hub.chamber" not in d["series"]
    assert "esp_bed_hub.humidity" in d["series"]


def test_long_range_is_bucketed_to_max_points(client):
    put_twin(client.db, [(NOW - 86000 + i * 5, 100.0, 100.0, 50.0, 50.0, "printing") for i in range(17000)])
    d = hist(client, minutes=1440, max_points=100).get_json()
    assert d["step_s"] == round(86400 / 100)
    assert len(d["series"]["extruder"]["t"]) <= 100 + 25         # <= 100 DB buckets + the 20-min Moonraker window
    assert max(d["series"]["extruder"]["t"]) <= NOW


# ── Moonraker down ────────────────────────────────────────────────────────────
def test_moonraker_down_still_returns_what_the_database_has(client):
    client.state["store"] = mu.MoonrakerError("Moonraker unreachable: down")
    put_twin(client.db, [(NOW - 600 + i * 10, 200.0, 200, 60, 60, "printing") for i in range(60)])
    d = hist(client, minutes=30).get_json()
    assert d["ok"] and d["sources"]["moonraker"]["ok"] is False and "unreachable" in d["sources"]["moonraker"]["error"]
    assert len(d["series"]["extruder"]["t"]) >= 55


def test_moonraker_down_and_nothing_stored_is_a_502(client):
    client.state["store"] = mu.MoonrakerError("Moonraker unreachable: down")
    r = hist(client, minutes=30)
    assert r.status_code == 502 and r.get_json()["ok"] is False and "unreachable" in r.get_json()["error"]


def test_missing_tables_do_not_break_the_endpoint(client, monkeypatch):
    def broken():
        raise sqlite3.OperationalError("no such table")
    monkeypatch.setattr(thermal, "_conn", broken)
    d = hist(client, minutes=60).get_json()
    assert d["ok"] and d["sources"]["twin_snapshots"]["ok"] is False and d["sources"]["esp_bed_hub"]["ok"] is False
    assert "extruder" in d["series"]


def test_simulator_skips_moonraker(client, monkeypatch):
    import workers

    class Sim:
        def inject_gcode(self, s):
            pass
    monkeypatch.setattr(workers, "_active_worker", Sim())
    monkeypatch.setattr(mu, "get_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Moonraker in the simulator")))
    put_twin(client.db, [(NOW - 600 + i * 10, 200.0, 200, 60, 60, "printing") for i in range(60)])
    d = hist(client, minutes=30).get_json()
    assert d["ok"] and d["sources"]["moonraker"]["ok"] is False and len(d["series"]["extruder"]["t"]) >= 55


def test_simulator_with_nothing_stored_is_an_empty_200_not_a_502(client, monkeypatch):
    import workers

    class Sim:
        def inject_gcode(self, s):
            pass
    monkeypatch.setattr(workers, "_active_worker", Sim())
    r = hist(client, minutes=30)
    assert r.status_code == 200 and r.get_json()["series"] == {}


# ── sensors ───────────────────────────────────────────────────────────────────
LISTING = {"sensors": {"bed_hub": {"id": "bed_hub", "friendly_name": "Bed hub", "type": "mqtt",
                                   "values": {"temperature": 31.2, "humidity": 44.0},
                                   "parameter_info": [{"units": "°C"}, {"units": "%"}]}}}
MEAS = {"bed_hub": {"temperature": [30.0 + i * 0.01 for i in range(1200)], "humidity": [44.0] * 5}}


def test_sensors_proxy_listing_and_thin_history(client):
    client.state["/server/sensors/list"] = LISTING
    client.state["/server/sensors/measurements"] = MEAS
    d = client.get("/api/v1/printer/sensors").get_json()
    assert d["ok"] and d["moonraker"]["ok"]
    row = d["sensors"][0]
    assert row["id"] == "bed_hub" and row["friendly_name"] == "Bed hub" and row["values"]["temperature"] == 31.2
    assert row["keys"] == ["temperature", "humidity"]
    assert row["source"] == "moonraker" and 1 < len(row["history"]["temperature"]) <= thermal.SENSOR_HISTORY_POINTS
    assert row["history"]["temperature"][-1] == pytest.approx(30.0 + 1199 * 0.01, abs=0.2)
    assert row["history"]["humidity"] == [44.0] * 5


def test_sensors_without_measurements_still_lists_readings(client):
    client.state["/server/sensors/list"] = LISTING
    d = client.get("/api/v1/printer/sensors").get_json()
    assert d["ok"] and d["sensors"][0]["history"] == {}


class FakeHub:
    enabled = True

    def chamber(self, max_age_s=10.0):
        return {"temp_c": 29.5, "humidity_pct": 40.0, "pressure_hpa": 1005.0}

    class store:                                           # noqa: N801
        @staticmethod
        def recent(minutes, limit):
            return [{"chamber_temp_c": 29.0 + i * 0.1, "chamber_humidity_pct": 40.0, "chamber_pressure_hpa": None} for i in range(5)]


def test_sensors_fall_back_to_the_esp_bed_hub_plugin(client, monkeypatch):
    import plugins.esp_bed_hub as hubmod
    monkeypatch.setattr(hubmod, "hub", FakeHub())
    client.state["/server/sensors/list"] = {"sensors": {}}                 # Moonraker has no bed_hub sensor
    d = client.get("/api/v1/printer/sensors").get_json()
    row = next(r for r in d["sensors"] if r["id"] == "esp_bed_hub")
    assert row["source"] == "esp_bed_hub" and row["values"] == {"temperature": 29.5, "humidity": 40.0, "pressure": 1005.0}
    assert len(row["history"]["temperature"]) == 5 and "pressure" in row["values"]
    assert len(row["history"]["humidity"]) == 5


def test_hub_fallback_when_moonraker_is_down_and_502_when_nothing(client, monkeypatch):
    import plugins.esp_bed_hub as hubmod
    monkeypatch.setattr(hubmod, "hub", FakeHub())
    client.state["/server/sensors/list"] = mu.MoonrakerError("Moonraker unreachable: down")
    d = client.get("/api/v1/printer/sensors").get_json()
    assert d["ok"] and d["moonraker"]["ok"] is False and d["sensors"][0]["id"] == "esp_bed_hub"

    class Off(FakeHub):
        def chamber(self, max_age_s=10.0):
            return None
    monkeypatch.setattr(hubmod, "hub", Off())
    r = client.get("/api/v1/printer/sensors")
    assert r.status_code == 502 and "unreachable" in r.get_json()["error"]


def test_moonraker_bed_hub_sensor_suppresses_the_plugin_fallback(client, monkeypatch):
    import plugins.esp_bed_hub as hubmod
    monkeypatch.setattr(hubmod, "hub", FakeHub())
    client.state["/server/sensors/list"] = LISTING
    d = client.get("/api/v1/printer/sensors").get_json()
    assert [r["id"] for r in d["sensors"]] == ["bed_hub"]


def test_registered_in_the_app():
    from api import server
    rules = {r.rule for r in server.app.url_map.iter_rules()}
    assert "/api/v1/printer/thermal_history" in rules and "/api/v1/printer/sensors" in rules
