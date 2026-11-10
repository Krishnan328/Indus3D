"""Host daemon of the bed sensor hub, exercised against a software model of the hub."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import esp_bed_monitor_daemon as dm
import hub_protocol as hp


def make(hub, moon, clock, tmp_path, **kw):
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake",
                     http=moon, clock=clock, sleep=lambda s: None, data_dir=tmp_path, csv_log=False,
                     async_actions=False, **kw)
    return d


def connect(d):
    assert d._connect()
    return d


def running(d):
    t = threading.Thread(target=d.run_forever, daemon=True)
    t.start()
    return t


# ── protocol helpers ──────────────────────────────────────────────────────────
def test_crash_line_is_parsed_including_the_real_jerk():
    c = hp.parse_crash_line("// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[-420, +1850, -910] mg) -> Auto-pausing print!")
    assert c == {"jerk_mg": 2450, "accel": {"x": -420, "y": 1850, "z": -910}}
    assert hp.parse_crash_line("// STATUS: adxl=OK") is None


def test_frames_roundtrip_resync_checksum_gaps_and_clock_wrap():
    frames = b"".join(hp.pack_frame(i, 625 * i, i, -i, 256) for i in range(20))
    samples, st = hp.unpack_frames(b"\xde\xad" + frames[:15 * 5] + b"\x00\x01\x02" + frames[15 * 5:])
    assert st["packets"] >= 19 and st["resyncs"] >= 1
    assert abs(samples[1][0] - 0.000625) < 1e-9 and abs(samples[1][3] - 1.0) < 1e-9

    bad = bytearray(frames)
    bad[25] ^= 0xFF                                    # corrupt a data byte of packet #1 (bytes 15-29)
    _, st = hp.unpack_frames(bytes(bad))
    assert st["bad_checksum"] >= 1

    gappy = b"".join(hp.pack_frame(i, 1000 * i, 0, 0, 0) for i in (0, 1, 2, 5, 6))
    assert hp.unpack_frames(gappy)[1]["lost_packets"] == 2

    wrap = hp.pack_frame(0, 0xFFFFFF00, 0, 0, 0) + hp.pack_frame(1, 0x100, 0, 0, 0)
    t = hp.unpack_frames(wrap)[0]
    assert 0 < t[1][0] < 0.001                          # 32-bit microsecond clock wrapped, time still increases


def test_split_capture_keeps_a_trailing_0x0a_data_byte():
    f = hp.pack_frame(0, 0, 0, 0, 0x0A00 >> 8)         # last data byte arrangement irrelevant; checksum may be 0x0A
    payload, ended = hp.split_capture(f + b"\n// SHAPER_SESSION_ENDED: collected 1 samples\n")
    assert ended and payload == f
    payload, ended = hp.split_capture(b"// SHAPER_SESSION_STARTED: x\n" + f)
    assert not ended and payload == f


# ── telemetry & staleness ─────────────────────────────────────────────────────
def test_telemetry_is_served_with_its_age_and_goes_stale(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_line(json.dumps({"bed_accel": {"jerk_mg": 7}, "chamber": {"temp_c": 26.0}, "uptime_sec": 5}))
    s = d.snapshot()
    assert s["connected"] and s["age_s"] == 0 and s["chamber"]["temp_c"] == 26.0
    clock.t += 30                                       # the hub went silent
    s = d.snapshot()
    assert not s["connected"] and s["age_s"] == 30       # never served as if it were fresh


def test_garbage_and_boot_banner_lines_are_ignored(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    for line in ("", "=====", "[INIT] Connecting ADXL345", "{not json}", "\x00\x01"):
        d.handle_line(line)
    assert d.latest == {}


def test_csv_log_rotates(tmp_path):
    log = dm.TelemetryCsv(tmp_path / "t.csv", max_bytes=300, keep=2)
    data = {"bed_accel": {"x_mg": 1, "y_mg": 2, "z_mg": 3, "jerk_mg": 4}, "chamber": {"temp_c": None}, "uptime_sec": 1}
    for i in range(30):
        log.write(data, 1_000_000 + i)
    assert (tmp_path / "t.csv.1").exists() and (tmp_path / "t.csv").stat().st_size <= 600
    assert ",,,False" in (tmp_path / "t.csv").read_text()   # missing sensors are blank, not 0


# ── crash response ────────────────────────────────────────────────────────────
def posts(moon):
    return [(c[1], c[2]) for c in moon.calls if c[0] == "POST"]


def test_crash_while_printing_pauses_first_then_runs_the_handler_with_the_real_jerk(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_line("// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[-420, +1850, -910] mg) -> Auto-pausing print!")
    assert posts(moon) == [("/printer/print/pause", {}),
                           ("/printer/gcode/script", {"script": "BED_CRASH_HANDLER JERK=2450"})]
    assert d.last_crash["action"]["result"] == "paused" and d.last_crash["jerk_mg"] == 2450


def test_the_latched_flag_in_telemetry_does_not_trigger_a_second_response(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_telemetry({"crash_detected": False, "uptime_sec": 1})
    d.handle_line("// Klipper: BED_CRASH_DETECTED jerk=3000 mg (accel=[0, 0, 0] mg) -> x")
    n = len(posts(moon))
    d.handle_telemetry({"crash_detected": True, "crash_info": {"peak_jerk_mg": 3000}, "uptime_sec": 2})
    d.handle_telemetry({"crash_detected": True, "uptime_sec": 3})
    assert len(posts(moon)) == n == 2


def test_alert_line_lost_but_telemetry_latch_still_triggers_once(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_telemetry({"crash_detected": False, "uptime_sec": 1})                # first sample after connect
    d.handle_telemetry({"crash_detected": True, "crash_info": {"peak_jerk_mg": 2800}, "uptime_sec": 2})
    assert ("/printer/gcode/script", {"script": "BED_CRASH_HANDLER JERK=2800"}) in posts(moon)


def test_a_latch_that_was_already_set_when_the_daemon_connected_is_not_a_new_crash(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_telemetry({"crash_detected": True, "crash_info": {"peak_jerk_mg": 4000}, "uptime_sec": 900})
    assert posts(moon) == []                                                        # stale latch from an earlier crash


@pytest.mark.parametrize("state,why", [("standby", "no print running"), ("complete", "no print running"),
                                       ("paused", "already paused")])
def test_crash_without_an_active_print_never_moves_the_machine(hub, moon, clock, tmp_path, state, why):
    moon.state = state
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_line("// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[0, 0, 0] mg) -> x")
    assert posts(moon) == [] and why in d.last_crash["action"]["result"]


def test_moonraker_down_is_reported_loudly_not_swallowed(hub, moon, clock, tmp_path):
    moon.fail = True
    d = connect(make(hub, moon, clock, tmp_path))
    d.handle_line("// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[0, 0, 0] mg) -> x")
    assert "FAILED" in d.last_crash["action"]["result"]


def test_pause_is_retried_then_reported_failed(hub, clock, tmp_path):
    calls = {"n": 0}

    def flaky(method, url, body=None, timeout=2.0):
        if "print_stats" in url:
            return {"result": {"status": {"print_stats": {"state": "printing"}}}}
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError("busy")
        return {}
    d = connect(make(hub, flaky, clock, tmp_path))
    d.handle_line("// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[0, 0, 0] mg) -> x")
    assert d.last_crash["action"]["pause"] is True and calls["n"] >= 3


def test_duplicate_crash_inside_the_cooldown_is_suppressed(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path, crash_cooldown_s=10))
    line = "// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[0, 0, 0] mg) -> x"
    d.handle_line(line)
    clock.t += 2
    d.handle_line(line)
    assert len(posts(moon)) == 2                                                    # one response only
    clock.t += 20
    d.handle_line(line)
    assert len(posts(moon)) == 4


def test_act_on_crash_can_be_disabled(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path, act_on_crash=False))
    d.handle_line("// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[0, 0, 0] mg) -> x")
    assert posts(moon) == [] and d.last_crash["action"]["result"] == "disabled"


# ── commands over the serial link ─────────────────────────────────────────────
def test_reset_crash_reaches_the_hub_and_clears_local_state(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    hub.latched = True
    running(d)
    d.latest = {"crash_detected": True, "crash_info": {"peak_jerk_mg": 1}}
    res = d.reset_crash()
    d.stop()
    assert res["ok"] and "RESET_CRASH" in hub.written and not hub.latched
    assert d.latest["crash_detected"] is False and "crash_info" not in d.latest


def test_threshold_is_validated_sent_persisted_and_reapplied_after_a_reconnect(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    running(d)
    assert not d.set_threshold(100)["ok"] and not d.set_threshold(True)["ok"] and not d.set_threshold("9")["ok"]
    assert d.set_threshold(2500)["ok"] and hub.threshold == 2500
    d.stop()
    d2 = make(hub, moon, clock, tmp_path)                                           # new process, same data dir
    assert d2.threshold_mg == 2500
    hub.threshold = 2000                                                            # the ESP was reset by the reconnect
    d2._connect()
    assert hub.threshold == 2500


def test_an_esp_reset_is_noticed_and_the_threshold_reapplied(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path, threshold_mg=3000))
    d.handle_telemetry({"uptime_sec": 500})
    hub.threshold = 2000
    d.handle_telemetry({"uptime_sec": 3})
    assert d.esp_resets == 1 and hub.threshold == 3000


def test_old_firmware_that_ignores_commands_fails_cleanly(hub, moon, tmp_path):
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     data_dir=tmp_path, csv_log=False, sleep=lambda s: None)     # real clock: this test times out
    d._connect()
    hub.silent = True
    t = time.time()
    res = d._do_command("RESET_CRASH", ("// CRASH_RESET",), timeout=0.2)
    assert not res["ok"] and "no answer" in res["response"] and time.time() - t < 2


# ── shaper capture ────────────────────────────────────────────────────────────
def test_capture_switches_baud_collects_everything_and_restores_the_link(hub, moon, clock, tmp_path):
    real = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                        data_dir=tmp_path, csv_log=False, sleep=lambda s: None)
    real._connect()
    running(real)
    res = real.capture_shaper(duration=2, rate=1600)
    real.stop()
    assert res["ok"], res
    assert "START_SHAPER 2 1600 460800" in hub.written                    # smallest standard baud that carries 1600 Hz
    assert res["baud"] == 460800 and res["rate_hz"] == 1600 and res["samples"] == 3200
    assert res["loss_pct"] == 0 and res["quality"] == "good" and res["ended_marker"]
    assert hub.baudrate == 115200                                          # link restored for telemetry
    csv_lines = open(res["csv"]).read().splitlines()
    assert csv_lines[0] == "time,accel_x,accel_y,accel_z" and len(csv_lines) == 3201


def test_capture_at_the_default_baud_is_clamped_by_the_hub_and_reported(hub, moon, tmp_path):
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     data_dir=tmp_path, csv_log=False, sleep=lambda s: None)
    d._connect()
    running(d)
    res = d.capture_shaper(duration=2, rate=1600, baud=115200)
    d.stop()
    assert res["ok"] and res["rate_hz"] == 400 and res["requested_rate_hz"] == 1600     # 115200 baud carries 400 Hz


def test_capture_reports_packet_loss_as_poor_quality(hub, moon, tmp_path):
    hub.drop_packets = 5
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     data_dir=tmp_path, csv_log=False, sleep=lambda s: None)
    d._connect()
    running(d)
    res = d.capture_shaper(duration=2, rate=1600)
    d.stop()
    assert res["ok"] and res["quality"] == "poor" and 15 < res["loss_pct"] < 25


def test_capture_parameters_are_validated(hub, moon, clock, tmp_path):
    d = make(hub, moon, clock, tmp_path)
    assert not d.capture_shaper(duration=99)["ok"]
    assert not d.capture_shaper(duration=5, rate=1234)["ok"]
    assert not d.capture_shaper(duration=5, rate=1600, baud=9600)["ok"]


def test_capture_fails_clearly_when_the_hub_does_not_answer(hub, moon, tmp_path):
    hub.silent = True
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     data_dir=tmp_path, csv_log=False, sleep=lambda s: None)
    d._connect()
    t0 = time.time()
    res = d._do_capture(1, 1600, None)
    assert not res["ok"] and "STARTED" in res["error"] and time.time() - t0 < 6


# ── link management ───────────────────────────────────────────────────────────
def test_the_link_is_re_established_after_a_disconnect(hub, moon, clock, tmp_path):
    d = connect(make(hub, moon, clock, tmp_path))
    hub.fail_reads = 1
    d.handle_line(d._read_line())
    assert d.ser is None and "read error" in d.last_error
    assert d._connect() and d.reconnects == 2


def test_missing_hub_is_a_status_not_a_crash(moon, clock, tmp_path):
    d = dm.HubDaemon(port="auto", finder=lambda a, o: None, http=moon, clock=clock, sleep=lambda s: None,
                     data_dir=tmp_path, csv_log=False)
    assert not d._connect() and "not found" in d.last_error
    assert d.snapshot()["connected"] is False and d.snapshot()["daemon"]["link_open"] is False


def test_find_port_prefers_an_explicit_port_then_the_udev_link_then_probes():
    assert dm.find_port("/dev/ttyUSB7") == "/dev/ttyUSB7"
    assert dm.find_port("auto", link="/dev/x", exists=lambda p: True) == "/dev/x"
    probed = []

    def probe(p, opener):
        probed.append(p)
        return p == "/dev/serial/by-id/usb-ESP"
    got = dm.find_port("auto", exists=lambda p: False, candidates=lambda: ["/dev/serial/by-id/usb-A", "/dev/serial/by-id/usb-ESP"],
                       probe=probe)
    assert got == "/dev/serial/by-id/usb-ESP" and probed == ["/dev/serial/by-id/usb-A", "/dev/serial/by-id/usb-ESP"]
    assert dm.find_port("auto", exists=lambda p: False, candidates=lambda: [], probe=probe) is None


def test_probe_is_passive_it_never_writes_to_an_unknown_device(hub):
    hub.push_telemetry()
    assert dm.probe_port("/dev/x", opener=lambda p, b: hub, listen_s=1.0) is True
    assert hub.written == []
    other = type(hub)()
    assert dm.probe_port("/dev/y", opener=lambda p, b: other, listen_s=0.1) is False and other.written == []
    assert dm.probe_port("/dev/z", opener=lambda p, b: (_ for _ in ()).throw(OSError("busy"))) is False


def test_candidate_ports_never_include_klipper_mcus(monkeypatch):
    # Mock glob to return a Klipper toolhead MCU, a CH340 mainboard MCU, and an ESP8266 device
    monkeypatch.setattr(dm.glob, "glob", lambda pat: [
        "/dev/serial/by-id/usb-Klipper_stm32g0b1xx-if00",
        "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
        "/dev/serial/by-id/usb-Silicon_Labs_CP2102_ESP8266_Hub-if00"
    ] if "by-id" in pat else [
        "/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0-port0"
    ])
    # Mock realpaths: Klipper toolhead and its by-path point to /dev/ttyACM0, mainboard points to /dev/ttyUSB0, ESP points to /dev/ttyUSB1
    def mock_realpath(path):
        if "stm32" in path or "1.3:1.0" in path:
            return "/dev/ttyACM0"
        if "1a86" in path:
            return "/dev/ttyUSB0"
        if "ESP8266" in path:
            return "/dev/ttyUSB1"
        return path

    monkeypatch.setattr(dm.os.path, "realpath", mock_realpath)
    # The Klipper MCU, mainboard CH340, and by-path link to Klipper must all be excluded
    assert dm.candidate_ports() == ["/dev/serial/by-id/usb-Silicon_Labs_CP2102_ESP8266_Hub-if00"]


# ── HTTP API ──────────────────────────────────────────────────────────────────
@pytest.fixture
def api(hub, moon, tmp_path):
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     data_dir=tmp_path, csv_log=False, sleep=lambda s: None)
    d._connect()
    running(d)
    srv = dm.serve(d, "127.0.0.1", 0)
    hub.push_telemetry()
    time.sleep(0.2)
    yield d, f"http://127.0.0.1:{srv.server_address[1]}"
    d.stop()
    srv.shutdown()


def http(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_api_serves_telemetry_chamber_and_health(api):
    d, url = api
    code, body = http(url + "/telemetry")
    assert code == 200 and body["connected"] and body["chamber"]["humidity_pct"] == 45.5
    assert http(url + "/chamber")[1]["temp_c"] == 26.0
    assert http(url + "/health")[1]["connected"] is True
    assert http(url + "/nope")[0] == 404


def test_api_binds_to_loopback_only(api):
    d, url = api
    assert url.startswith("http://127.0.0.1:")


def test_api_post_requires_the_action_header(api, hub):
    d, url = api
    assert http(url + "/reset_crash", "POST", {})[0] == 403
    assert http(url + "/threshold", "POST", {"mg": 2500})[0] == 403
    assert "RESET_CRASH" not in hub.written
    h = {"X-Indus3D-Action": "1"}
    assert http(url + "/reset_crash", "POST", {}, h)[0] == 200
    assert http(url + "/threshold", "POST", {"mg": 2500}, h)[0] == 200 and hub.threshold == 2500
    code, body = http(url + "/threshold", "POST", {"mg": 99999}, h)
    assert code == 502 and not body["ok"]
    assert http(url + "/shaper/capture", "POST", {"duration": 99}, h)[0] == 502


def test_api_rejects_invalid_json(api):
    d, url = api
    req = urllib.request.Request(url + "/reset_crash", data=b"{broken", method="POST",
                                 headers={"X-Indus3D-Action": "1", "Content-Length": "7"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_crash_while_idle_is_ignored_and_the_latch_is_cleared_so_the_hub_stays_armed(hub, moon, clock, tmp_path):
    moon.state = "standby"
    d = dm.HubDaemon(port="/dev/fake", opener=lambda p, b: hub, finder=lambda a, o: "/dev/fake", http=moon,
                     clock=time.time, sleep=lambda s: time.sleep(0.001), data_dir=tmp_path, csv_log=False,
                     async_actions=True)
    running(d)
    try:
        hub.push_telemetry()
        end = time.time() + 5
        while d.last_update is None and time.time() < end:
            time.sleep(0.01)
        hub.push_crash_alert(jerk=2450)
        while (d.last_crash is None or d.last_crash.get("action") is None) and time.time() < end:
            time.sleep(0.01)
        act = d.last_crash["action"]
        assert act["result"].startswith("ignored: no print running") and act["latch_cleared"] is True
        assert hub.latched is False
        assert not any("print/pause" in c[1] for c in moon.calls)             # nothing paused
        assert not any("BED_CRASH_HANDLER" in str(c[2]) for c in moon.calls)  # handler never runs on an idle printer
    finally:
        d.stop()
