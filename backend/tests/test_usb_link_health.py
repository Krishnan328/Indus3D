"""Tests for the usb_link_health plugin, using a fake sysfs tree and fake kernel log."""
import shutil

import pytest

from plugins import usb_link_health as u


@pytest.fixture(autouse=True)
def plugin_data(tmp_path, monkeypatch):
    monkeypatch.setenv("INDUS3D_PLUGIN_DATA", str(tmp_path / "plug"))


# ── fake sysfs ────────────────────────────────────────────────────────────────
class Sysfs:
    def __init__(self, root):
        self.root = root
        root.mkdir(exist_ok=True)
        (root / "usb3").mkdir()                                  # root hub entry: must be ignored

    def add(self, path, product="dev", manufacturer="", hub=False, devnum="1", vid="1234", pid="0001"):
        d = self.root / path
        d.mkdir(exist_ok=True)
        for k, v in (("devnum", devnum), ("idVendor", vid), ("idProduct", pid), ("product", product),
                     ("manufacturer", manufacturer), ("serial", "S"), ("speed", "480"),
                     ("bDeviceClass", "09" if hub else "ef")):
            (d / k).write_text(v + "\n")
        (self.root / f"{path}:1.0").mkdir(exist_ok=True)          # interface entry: ignored

    def remove(self, path):
        shutil.rmtree(self.root / path)


def build_printer(fs):
    """Topology like the real host: hub A -> hub B (mainboard, Pico) and hub C -> hub D -> EBB36; eddy on A."""
    fs.add("3-2", "USB2.0 HUB", hub=True)
    fs.add("3-2.1", "USB2.0 HUB", hub=True)
    fs.add("3-2.1.2", "USB Serial")
    fs.add("3-2.1.3", "Pico", "Raspberry Pi")
    fs.add("3-2.3", "USB 2.0 Hub", hub=True)
    fs.add("3-2.3.1", "USB 2.0 Hub", hub=True)
    fs.add("3-2.3.1.3", "stm32g0b1xx", "Klipper", devnum="42")
    fs.add("3-2.4", "rp2040", "Klipper")


@pytest.fixture
def env(tmp_path):
    fs = Sysfs(tmp_path / "sys")
    build_printer(fs)
    notes = []
    mon = u.UsbLinkHealth(sysfs=str(fs.root), read_klog=lambda since: None, notify=notes.append,
                          state_path=tmp_path / "state.json", burst=5)
    mon.poll_sysfs(now=100.0)                                    # baseline
    return fs, mon, notes


# ── pure helpers ──────────────────────────────────────────────────────────────
def test_path_helpers():
    assert u.parent_of("3-2.3.1") == "3-2.3" and u.parent_of("3-2") is None
    assert u.top_of("3-2.3.1.3") == "3-2" and u.top_of("1-4") == "1-4"
    assert u.depth_of("3-2") == 0 and u.depth_of("3-2.3.1.3") == 3


@pytest.mark.parametrize("line,expected", [
    ("1794114864.1 host kernel: usb 3-2.1: clear tt 1 (90a1) error -71", (1794114864.1, "tt", "3-2.1")),
    ("1794114864.2 host kernel: usb 3-2: USB disconnect, device number 33", (1794114864.2, "disconnect", "3-2")),
    ("1794114864.3 host kernel: usb 3-2.3-port1: Cannot enable. Maybe the USB cable is bad?", (1794114864.3, "cable", "3-2.3")),
    ("1.0 h kernel: usb 3-2.3: device not accepting address 16, error -71", (1.0, "enum", "3-2.3")),
    ("1.0 h kernel: usb 3-2.4: unable to enumerate USB device", (1.0, "enum", "3-2.4")),
    ("1.0 h kernel: usb 3-2.1: over-current condition on port", (1.0, "overcurrent", "3-2.1")),
])
def test_parse_real_kernel_lines(line, expected):
    assert u.parse_klog_line(line) == expected


def test_parse_ignores_unrelated_lines():
    assert u.parse_klog_line("1.0 h kernel: usb 3-2.1.3: Product: Pico") is None
    assert u.parse_klog_line("garbage") is None


def test_scan_skips_interfaces_and_root_hubs(env):
    fs, mon, _ = env
    found = u.scan_sysfs(str(fs.root))
    assert "usb3" not in found and not any(":" in p for p in found)
    assert found["3-2.3.1.3"]["manufacturer"] == "Klipper" and found["3-2"]["is_hub"] is True
    assert u.scan_sysfs("/nonexistent") == {}


# ── device loss classification ────────────────────────────────────────────────
def kinds(mon):
    return [e["kind"] for e in mon.events]


def test_klipper_mcu_lost_during_print_is_critical_and_notifies(env):
    fs, mon, notes = env
    mon.print_state = "printing"
    fs.remove("3-2.3.1.3")
    mon.poll_sysfs(now=110.0)
    ev = mon.events[0]
    assert ev["kind"] == "device_lost" and ev["severity"] == "critical" and ev["paths"] == ["3-2.3.1.3"]
    assert len(notes) == 1 and "stm32g0b1xx" in notes[0] and "3 hub tier" in notes[0]


def test_loss_while_idle_is_recorded_quietly(env):
    fs, mon, notes = env
    mon.print_state = "standby"
    fs.remove("3-2.4")
    mon.poll_sysfs(now=110.0)
    assert kinds(mon) == ["device_lost"] and mon.events[0]["severity"] == "info" and notes == []


def test_flap_detected_notifies_and_is_rate_limited(env):
    fs, mon, notes = env
    fs.remove("3-2.4")
    mon.poll_sysfs(now=110.0)
    fs.add("3-2.4", "rp2040", "Klipper")
    mon.poll_sysfs(now=112.0)
    assert "flap" in kinds(mon) and len(notes) == 1 and "unstable" in notes[0]
    fs.remove("3-2.4")
    mon.poll_sysfs(now=120.0)
    fs.add("3-2.4", "rp2040", "Klipper")
    mon.poll_sysfs(now=121.0)
    assert kinds(mon).count("flap") == 2 and len(notes) == 1          # second flap: recorded, not re-notified


def test_reenumeration_with_new_device_number_counts_as_a_drop(env):
    fs, mon, _ = env
    fs.add("3-2.3.1.3", "stm32g0b1xx", "Klipper", devnum="77")        # same path, new devnum
    mon.poll_sysfs(now=110.0)
    assert mon.counters["sysfs_disconnects"]["3-2.3.1.3"] == 1 and "flap" in kinds(mon)


def test_hub_drop_during_print_alerts_with_the_hub(env):
    fs, mon, notes = env
    mon.print_state = "printing"
    for p in ("3-2.1.2", "3-2.1.3", "3-2.4", "3-2.3.1.3"):
        fs.remove(p)
    mon.poll_sysfs(now=110.0)
    ev = mon.events[0]
    assert ev["kind"] == "hub_drop" and ev["paths"][0] == "3-2" and ev["severity"] == "critical"
    assert len(notes) == 1 and "hub 3-2" in notes[0]
    assert kinds(mon).count("hub_drop") == 1


def test_power_off_is_not_an_alarm(env):
    """Switching the printer off drops everything: record it, never page the user."""
    fs, mon, notes = env
    mon.print_state = "standby"
    shutil.rmtree(fs.root)
    fs.root.mkdir()
    mon.poll_sysfs(now=110.0)
    assert "hub_drop" in kinds(mon) and notes == []
    mon.poll_sysfs(now=110.0 + u.FLAP_S + 1)
    assert "offline" in kinds(mon) and notes == []


def test_first_poll_is_a_baseline_not_a_flood(tmp_path):
    fs = Sysfs(tmp_path / "s")
    build_printer(fs)
    mon = u.UsbLinkHealth(sysfs=str(fs.root), read_klog=lambda s: None, notify=lambda m: None, state_path=tmp_path / "x.json")
    mon.poll_sysfs(now=1.0)
    assert list(mon.events) == [] and len(mon.known) == 8


# ── kernel log ────────────────────────────────────────────────────────────────
def klog(lines):
    return lambda since: list(lines)


def tt_lines(n, path="3-2.1", t0=1000.0):
    return [f"{t0 + i * 0.1:.1f} host kernel: usb {path}: clear tt 1 (90a1) error -71" for i in range(n)]


def test_error_burst_alerts_once_and_names_the_worst_path(env):
    fs, mon, notes = env
    mon._read_klog = klog(tt_lines(6))
    mon.poll_klog(now=1001.0)
    bursts = [e for e in mon.events if e["kind"] == "error_burst"]
    assert len(bursts) == 1 and "3-2.1" in bursts[0]["detail"] and bursts[0]["paths"] == ["3-2.1"]
    assert len(notes) == 1 and mon.klog_available is True
    mon._read_klog = klog(tt_lines(6, t0=1002.0))
    mon.poll_klog(now=1003.0)
    assert len([e for e in mon.events if e["kind"] == "error_burst"]) == 1      # same episode


def test_burst_rearms_after_quiet_period(env):
    fs, mon, notes = env
    mon._read_klog = klog(tt_lines(6))
    mon.poll_klog(now=1001.0)
    mon._read_klog = klog([])
    mon.poll_klog(now=1001.0 + u.BURST_REARM_S + 70)
    mon._read_klog = klog(tt_lines(6, t0=2000.0))
    mon.poll_klog(now=2001.0)
    assert len([e for e in mon.events if e["kind"] == "error_burst"]) == 2


def test_repeated_log_lines_are_counted_once(env):
    fs, mon, _ = env
    lines = tt_lines(3)
    mon._read_klog = klog(lines)
    mon.poll_klog(now=1001.0)
    mon.poll_klog(now=1006.0)                                                    # journalctl returns them again
    assert mon.counters["tt"]["3-2.1"] == 3


def test_unreadable_kernel_log_falls_back_to_sysfs_only(env):
    fs, mon, _ = env
    calls = []
    mon._read_klog = lambda since: (calls.append(1), None)[1]
    mon.poll_klog(now=1.0)
    mon.poll_klog(now=10.0)
    assert len(calls) == 1 and mon.klog_available is False                       # tried once, then stopped
    assert mon.status()["kernel_log"].startswith("unreadable")


# ── suspects ──────────────────────────────────────────────────────────────────
def test_suspects_rank_cable_errors_above_noisy_protocol_errors(env):
    fs, mon, _ = env
    mon.counters["tt"]["3-2.1"] = 5000                    # very noisy, but capped at 200 x 0.1 = 20 points
    mon.counters["cable"]["3-2.3"] = 6                    # 6 x 5 = 30 points
    mon.counters["kernel_disconnects"]["3-2.3.1.3"] = 3
    mon.counters["sysfs_disconnects"]["3-2.3.1.3"] = 4    # drops = max(3, 4) -> 12 points
    top = mon.suspects()
    assert [s["path"] for s in top] == ["3-2.3", "3-2.1", "3-2.3.1.3"]
    by = {s["path"]: s for s in top}
    assert by["3-2.3.1.3"]["drops"] == 4 and by["3-2.3.1.3"]["hub_tiers_deep"] == 3
    assert any("cable" in r for r in by["3-2.3"]["likely"]) and by["3-2.3"]["is_hub"]
    assert by["3-2.3"]["carries"] == ["USB 2.0 Hub [3-2.3.1]"]
    assert sorted(by["3-2.1"]["carries"]) == ["Raspberry Pi Pico [3-2.1.3]", "USB Serial [3-2.1.2]"]
    assert mon.suspects(limit=1)[0]["path"] == "3-2.3"


def test_no_suspects_when_nothing_has_failed(env):
    assert env[1].suspects() == []


def test_topology_tree_shows_hub_chain(env):
    fs, mon, _ = env
    tree = mon.topology()
    assert [n["path"] for n in tree] == ["3-2"]
    chain = tree[0]["children"]
    assert {c["path"] for c in chain} == {"3-2.1", "3-2.3", "3-2.4"}
    ebb = next(c for c in chain if c["path"] == "3-2.3")["children"][0]["children"][0]
    assert ebb["klipper_mcu"] is True and ebb["present"] is True


# ── persistence & route ───────────────────────────────────────────────────────
def test_counters_and_events_persist(env, tmp_path):
    fs, mon, _ = env
    fs.remove("3-2.4")
    mon.poll_sysfs(now=110.0)
    mon.save(now=111.0)
    again = u.UsbLinkHealth(sysfs=str(fs.root), read_klog=lambda s: None, notify=lambda m: None,
                            state_path=tmp_path / "state.json")
    st = again.status()
    assert again.counters["sysfs_disconnects"]["3-2.4"] == 1 and st["events"][0]["kind"] == "device_lost"


def test_route_serves_status():
    from api.server import app
    r = app.test_client().get("/api/v1/plugins/usb_link_health")
    body = r.get_json()
    assert r.status_code == 200 and {"suspects", "events", "topology", "kernel_log"} <= body.keys()
