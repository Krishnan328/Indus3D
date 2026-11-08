"""System page backend: validation, confirmation gates, busy refusal, unsupported-endpoint degradation,
unreachable Moonraker (502), the simulator stand-in and the rate-limit category. Moonraker is faked at the
``requests.request`` level so the real status-code handling is exercised."""
import copy

import pytest
import requests
from flask import Flask

from api import rate_limiter as rl
from api import system_host as sh
from api.routes import system as sysroutes


# ── a tiny Moonraker ──────────────────────────────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, status=200, result=None):
        self.status_code, self._result = status, result
        self.ok = 200 <= status < 300

    def json(self):
        if self.ok:
            return {"result": self._result}
        return {"error": {"code": self.status_code, "message": self._result or "nope"}}


SYSTEM_INFO = {"system_info": {
    "provider": "systemd_dbus",
    "cpu_info": {"cpu_count": 4, "processor": "aarch64", "cpu_desc": "Cortex-A72", "model": "Raspberry Pi 4",
                 "total_memory": 4000000},
    "distribution": {"name": "Debian 12", "id": "debian"},
    "available_services": ["klipper", "klipper_mcu", "moonraker", "crowsnest", "indus3d", "indus3d-backend"],
    "service_state": {n: {"active_state": "active", "sub_state": "running"}
                      for n in ("klipper", "klipper_mcu", "moonraker", "crowsnest", "indus3d", "indus3d-backend")},
    "network": {"wlan0": {"ip_addresses": [{"family": "ipv6", "address": "fe80::1"}, {"family": "ipv4", "address": "10.0.0.7"}]}},
    "python": {"version": [3, 11, 2, "final", 0]},
}}
PROC = {"throttled_state": {"bits": 0, "flags": []}, "cpu_temp": 51.2, "system_uptime": 9000.0,
        "network": {"lo": {"bandwidth": 1}, "wlan0": {"bandwidth": 1200.5, "rx_bytes": 5, "tx_bytes": 6}},
        "system_cpu_usage": {"cpu": 12.5}, "system_memory": {"total": 4000000, "available": 3000000, "used": 1000000}}
PRINTER_INFO = {"state": "ready", "hostname": "voron", "software_version": "v0.12.0-100", "state_message": "ok"}
SERVER_INFO = {"moonraker_version": "v0.9.3-12-gabc", "api_version_string": "1.5.0", "klippy_state": "ready",
               "klippy_connected": True, "failed_components": [], "warnings": []}
MCUS = {"status": {
    "mcu": {"mcu_version": "v0.12.0", "mcu_constants": {"MCU": "stm32f446xx", "CLOCK_FREQ": 180000000},
            "last_stats": {"mcu_awake": 0.02, "mcu_task_avg": 0.000005, "freq": 180000100}},
    "mcu toolhead": {"mcu_version": "v0.12.0", "mcu_constants": {"MCU": "rp2040"}, "last_stats": {}}}}
UPDATES = {"busy": False, "github_rate_limit": 60, "github_requests_remaining": 50, "version_info": {
    "system": {"name": "system", "configured_type": "system", "package_count": 2, "package_list": ["a", "b"]},
    "klipper": {"name": "klipper", "configured_type": "git_repo", "channel": "dev", "version": "v0.12.0-100",
                "remote_version": "v0.12.0-140", "commits_behind": [{"subject": "x", "author": "y", "tag": None}],
                "commits_behind_count": 40, "is_valid": True, "warnings": [], "anomalies": []},
    "moonraker": {"name": "moonraker", "configured_type": "git_repo", "version": "v0.9.3", "remote_version": "v0.9.3",
                  "commits_behind": [], "commits_behind_count": 0, "is_valid": True},
    "mainsail": {"name": "mainsail", "configured_type": "web", "version": "v2.12.0", "remote_version": "v2.13.0",
                 "is_valid": True}}}
DB_LIST = {"namespaces": ["moonraker"], "backups": ["old.db", "sqldb-backup-20260101-000000.db"]}
SERIAL = {"serial_devices": [
    {"device_type": "usb", "device_path": "/dev/ttyACM0", "path_by_id": "/dev/serial/by-id/usb-Klipper_x-if00",
     "path_by_hardware": "/dev/serial/by-path/p", "usb_location": "1:4"},
    {"device_type": "usb", "device_path": "/dev/ttyUSB0", "path_by_id": None, "path_by_hardware": "/dev/serial/by-path/q"},
    {"device_type": "hardware_uart", "device_path": "/dev/ttyAMA0", "path_by_id": None, "path_by_hardware": None}]}


class Moon:
    def __init__(self):
        self.calls = []
        self.routes = {
            ("GET", "/machine/system_info"): SYSTEM_INFO, ("GET", "/machine/proc_stats"): copy.deepcopy(PROC),
            ("GET", "/printer/info"): PRINTER_INFO, ("GET", "/server/info"): copy.deepcopy(SERVER_INFO),
            ("GET", "/printer/objects/list"): {"objects": ["mcu", "mcu toolhead", "extruder"]},
            ("GET", "/printer/objects/query"): MCUS,
            ("GET", "/machine/update/status"): copy.deepcopy(UPDATES), ("GET", "/server/database/list"): copy.deepcopy(DB_LIST),
            ("GET", "/machine/peripherals/usb"): {"usb_devices": [{"usb_location": "1:4", "product": "stm32"}]},
            ("GET", "/machine/peripherals/serial"): SERIAL,
            ("GET", "/machine/peripherals/video"): {"v4l2_devices": [{"device_path": "/dev/video0"}]},
            ("GET", "/machine/peripherals/canbus"): {"can_uuids": [{"uuid": "AABB", "application": "Klipper"}]},
            ("GET", "/server/announcements/list"): {"entries": [
                {"entry_id": "a/1", "title": "Big", "description": "d", "priority": "high", "dismissed": False},
                {"entry_id": "a/2", "title": "Meh", "priority": "normal", "dismissed": False},
                {"entry_id": "a/3", "title": "Read", "priority": "high", "dismissed": True}]},
            ("POST", "/machine/services/restart"): "ok", ("POST", "/machine/services/start"): "ok",
            ("POST", "/machine/services/stop"): "ok",
            ("POST", "/machine/update/upgrade"): "ok", ("POST", "/machine/update/recover"): "ok",
            ("POST", "/server/database/backup"): {"backup_path": "/x/new.db"},
            ("POST", "/server/database/restore"): {"restored_tables": []},
            ("DELETE", "/server/database/backup"): {"backup_path": "/x/old.db"},
        }
        self.down = False

    def request(self, method, url, json=None, timeout=None, **kw):
        if self.down:
            raise requests.ConnectionError("refused")
        route = url.split("://", 1)[1].split("/", 1)[1]
        route, _, query = ("/" + route).partition("?")
        self.calls.append((method, route, query, json))
        hit = self.routes.get((method, route), "__missing__")
        if hit == "__missing__":
            return Resp(404)
        if isinstance(hit, Exception):
            raise hit
        if callable(hit):
            return hit(json)
        if isinstance(hit, Resp):
            return hit
        return Resp(200, hit)

    def posted(self, route):
        return [c for c in self.calls if c[0] != "GET" and c[1] == route]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    import workers
    monkeypatch.setattr(workers, "_active_worker", None)
    sh.reset_cache()
    sh.sim_reset()
    sysroutes.reset_job()
    monkeypatch.setattr(sysroutes, "_spawn", lambda fn: fn())      # run update jobs inline
    yield
    sh.reset_cache()
    sysroutes.reset_job()


@pytest.fixture
def moon(monkeypatch):
    m = Moon()
    monkeypatch.setattr(requests, "request", m.request)
    return m


@pytest.fixture
def printing(monkeypatch):
    import workers

    class W:
        latest = {"print_state": "printing"}
    monkeypatch.setattr(workers, "_active_worker", W())


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(sysroutes.system_bp, url_prefix="/api/v1/system")
    return app.test_client()


def post(c, path, **body):
    return c.post(f"/api/v1/system{path}", json=body)


# ── info ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_info_merges_the_moonraker_sections(client, moon):
    r = client.get("/api/v1/system/info")
    assert r.status_code == 200
    b = r.get_json()
    h = b["host"]
    assert h["hostname"] == "voron" and h["os"] == "Debian 12" and h["model"] == "Raspberry Pi 4"
    assert h["cpu_usage_pct"] == 12.5 and h["cpu_temp_c"] == 51.2 and h["memory_used_pct"] == 25.0
    assert h["network"] == [{"name": "wlan0", "ip": "10.0.0.7", "bandwidth_bps": 1200.5, "rx_bytes": 5, "tx_bytes": 6}]
    assert h["moonraker"]["version"] == "v0.9.3-12-gabc" and h["klipper"]["version"] == "v0.12.0-100"
    assert h["throttle"]["supported"] and h["throttle"]["now"] == []
    assert [m["name"] for m in b["mcus"]] == ["main", "toolhead"]
    assert b["mcus"][0]["chip"] == "stm32f446xx" and b["mcus"][0]["awake_pct"] == 2.0 and b["mcus"][0]["task_avg_us"] == 5.0
    assert b["simulated"] is False and all(s["ok"] for s in b["sections"].values())


def test_info_degrades_per_section_and_does_not_fail(client, moon):
    del moon.routes[("GET", "/machine/proc_stats")]
    moon.routes[("GET", "/printer/info")] = Resp(503, "Klippy not ready")
    b = client.get("/api/v1/system/info").get_json()
    assert b["sections"]["proc_stats"]["unsupported"] is True
    assert b["sections"]["printer_info"] == {"ok": False, "unsupported": False, "error": "Klippy not ready"}
    assert b["host"]["os"] == "Debian 12" and b["host"]["cpu_temp_c"] is None and b["host"]["klipper"] is None


def test_info_is_cached_briefly(client, moon):
    client.get("/api/v1/system/info")
    n = len(moon.calls)
    client.get("/api/v1/system/info")
    assert len(moon.calls) == n


def test_unreachable_moonraker_is_502_everywhere(client, moon):
    moon.down = True
    for path in ("/info", "/services", "/updates", "/backups", "/peripherals", "/announcements", "/alerts"):
        r = client.get(f"/api/v1/system{path}")
        assert r.status_code == 502, path
        assert r.get_json()["ok"] is False and "unreachable" in r.get_json()["error"]
    assert post(client, "/services/klipper/restart", confirmed=True).status_code == 502


def test_a_missing_endpoint_is_a_404_unsupported_result(client, moon):
    del moon.routes[("GET", "/machine/update/status")]
    del moon.routes[("GET", "/server/announcements/list")]
    r = client.get("/api/v1/system/updates")
    assert r.status_code == 404 and r.get_json()["unsupported"] is True
    assert "not available on this Moonraker" in r.get_json()["error"]
    assert client.get("/api/v1/system/announcements").status_code == 404
    assert post(client, "/updates/klipper", confirmed=True).status_code == 404


# ── services ───────────────────────────────────────────────────────────────────────────────────────────────
def test_services_listing_flags_self_and_print_critical(client, moon):
    b = client.get("/api/v1/system/services").get_json()
    by = {s["name"]: s for s in b["services"]}
    assert b["manageable"] is True and by["klipper"]["print_critical"] and by["klipper_mcu"]["print_critical"]
    assert by["indus3d"]["is_self"] and by["indus3d-backend"]["is_self"] and not by["crowsnest"]["is_self"]
    assert by["crowsnest"]["active_state"] == "active"


def test_service_action_needs_confirmation(client, moon):
    for body in ({}, {"confirmed": "yes"}, {"confirmed": 1}, {"confirmed": False}):
        r = post(client, "/services/crowsnest/restart", **body)
        assert r.status_code == 400 and r.get_json()["needs"] == "confirmed"
    assert moon.posted("/machine/services/restart") == []


def test_service_action_validates_action_and_name(client, moon):
    assert post(client, "/services/crowsnest/reboot", confirmed=True).status_code == 400
    r = post(client, "/services/not-a-service/restart", confirmed=True)
    assert r.status_code == 404 and "crowsnest" in r.get_json()["services"]
    assert post(client, "/services/..%2Fetc/restart", confirmed=True).status_code == 404
    assert moon.posted("/machine/services/restart") == []


def test_service_restart_is_forwarded_with_the_listed_name(client, moon):
    r = post(client, "/services/crowsnest/restart", confirmed=True)
    assert r.status_code == 200 and r.get_json() == {"ok": True, "service": "crowsnest", "action": "restart", "self": False}
    assert moon.posted("/machine/services/restart")[0][3] == {"service": "crowsnest"}


@pytest.mark.parametrize("name", ["klipper", "klipper_mcu", "moonraker"])
@pytest.mark.parametrize("action", ["restart", "stop"])
def test_print_critical_services_are_refused_during_a_print(client, moon, printing, name, action):
    r = post(client, f"/services/{name}/{action}", confirmed=True)
    assert r.status_code == 409 and r.get_json()["busy"] is True and r.get_json()["reason"] == "print"
    assert moon.posted(f"/machine/services/{action}") == []


def test_other_services_and_start_are_allowed_during_a_print(client, moon, printing):
    assert post(client, "/services/crowsnest/restart", confirmed=True).status_code == 200
    assert post(client, "/services/klipper/start", confirmed=True).status_code == 200


def test_klipper_restart_is_allowed_when_idle(client, moon):
    assert post(client, "/services/klipper/restart", confirmed=True).status_code == 200


def test_stopping_indus3d_itself_needs_confirm_self(client, moon):
    r = post(client, "/services/indus3d/stop", confirmed=True)
    assert r.status_code == 400 and r.get_json()["needs"] == "confirm_self"
    assert moon.posted("/machine/services/stop") == []
    assert post(client, "/services/indus3d-backend/stop", confirmed=True, confirm_self="true").status_code == 400
    r = post(client, "/services/indus3d/stop", confirmed=True, confirm_self=True)
    assert r.status_code == 200 and r.get_json()["self"] is True
    # restarting it is not a stop: ordinary confirmation is enough
    assert post(client, "/services/indus3d/restart", confirmed=True).status_code == 200


def test_self_service_names_come_from_the_environment(client, moon, monkeypatch):
    monkeypatch.setenv("INDUS3D_SELF_SERVICE", "crowsnest")
    assert post(client, "/services/crowsnest/stop", confirmed=True).get_json()["needs"] == "confirm_self"
    assert post(client, "/services/indus3d/stop", confirmed=True).status_code == 200


def test_no_service_provider_means_unsupported(client, moon):
    si = copy.deepcopy(SYSTEM_INFO)
    si["system_info"]["provider"] = "none"
    moon.routes[("GET", "/machine/system_info")] = si
    assert client.get("/api/v1/system/services").get_json()["manageable"] is False
    r = post(client, "/services/crowsnest/restart", confirmed=True)
    assert r.status_code == 404 and r.get_json()["unsupported"] is True


def test_moonraker_refusing_a_service_call_is_a_502_with_its_message(client, moon):
    moon.routes[("POST", "/machine/services/restart")] = Resp(503, "PolicyKit denied")
    r = post(client, "/services/crowsnest/restart", confirmed=True)
    assert r.status_code == 502 and r.get_json()["error"] == "PolicyKit denied" and r.get_json()["upstream_status"] == 503


# ── updates ────────────────────────────────────────────────────────────────────────────────────────────────
def test_updates_listing_marks_pending_components(client, moon):
    b = client.get("/api/v1/system/updates").get_json()
    by = {c["name"]: c for c in b["components"]}
    assert b["pending"] == ["system", "klipper", "mainsail"] and b["job"] is None
    assert by["system"]["package_count"] == 2 and by["klipper"]["commits_behind"] == 40
    assert by["moonraker"]["update_available"] is False and by["mainsail"]["remote_version"] == "v2.13.0"
    assert by["klipper"]["recoverable"] is True and by["mainsail"]["recoverable"] is False
    assert [c["name"] for c in b["components"]][:3] == ["system", "klipper", "moonraker"]


def test_update_needs_confirmation_and_a_known_component(client, moon):
    assert post(client, "/updates/klipper").status_code == 400
    assert post(client, "/updates/klipper", confirmed="true").status_code == 400
    r = post(client, "/updates/nonsense", confirmed=True)
    assert r.status_code == 404 and "klipper" in r.get_json()["components"]
    assert post(client, "/updates/bad%20name", confirmed=True).status_code == 400
    assert moon.posted("/machine/update/upgrade") == []


def test_update_uses_the_upgrade_endpoint_and_reports_the_job(client, moon):
    r = post(client, "/updates/klipper", confirmed=True)
    assert r.status_code == 202 and r.get_json()["started"] is True
    assert moon.posted("/machine/update/upgrade")[0][3] == {"name": "klipper"}
    job = client.get("/api/v1/system/updates").get_json()["job"]
    assert job["state"] == "done" and job["component"] == "klipper"


def test_update_all_sends_no_name(client, moon):
    assert post(client, "/updates/full", confirmed=True).status_code == 202
    assert moon.posted("/machine/update/upgrade")[0][3] == {}


def test_update_falls_back_to_the_legacy_endpoints_on_old_moonraker(client, moon):
    del moon.routes[("POST", "/machine/update/upgrade")]
    moon.routes[("POST", "/machine/update/klipper")] = "ok"
    moon.routes[("POST", "/machine/update/client")] = "ok"
    moon.routes[("POST", "/machine/update/full")] = "ok"
    assert post(client, "/updates/klipper", confirmed=True).status_code == 202
    assert post(client, "/updates/mainsail", confirmed=True).status_code == 202
    assert post(client, "/updates/full", confirmed=True).status_code == 202
    assert [c[1] for c in moon.calls if c[0] == "POST" and "upgrade" not in c[1]] == [
        "/machine/update/klipper", "/machine/update/client", "/machine/update/full"]
    assert moon.posted("/machine/update/client")[0][3] == {"name": "mainsail"}


def test_update_is_refused_during_a_print(client, moon, printing):
    r = post(client, "/updates/klipper", confirmed=True)
    assert r.status_code == 409 and r.get_json()["reason"] == "print"
    assert moon.posted("/machine/update/upgrade") == []


def test_update_is_refused_while_moonraker_reports_busy(client, moon):
    moon.routes[("GET", "/machine/update/status")] = dict(UPDATES, busy=True)
    r = post(client, "/updates/klipper", confirmed=True)
    assert r.status_code == 409 and r.get_json()["reason"] == "update"


def test_only_one_update_at_a_time(client, moon, monkeypatch):
    monkeypatch.setattr(sysroutes, "_spawn", lambda fn: None)       # job stays 'running'
    assert post(client, "/updates/klipper", confirmed=True).status_code == 202
    r = post(client, "/updates/mainsail", confirmed=True)
    assert r.status_code == 409 and r.get_json()["reason"] == "update" and "klipper" in r.get_json()["error"]
    assert client.get("/api/v1/system/updates").get_json()["job"]["state"] == "running"
    assert post(client, "/updates/klipper/recover", confirmed=True).status_code == 409


def test_a_refused_update_ends_the_job_with_the_error(client, moon):
    moon.routes[("POST", "/machine/update/upgrade")] = Resp(503, "Cannot update, print in progress")
    assert post(client, "/updates/klipper", confirmed=True).status_code == 202
    job = client.get("/api/v1/system/updates").get_json()["job"]
    assert job["state"] == "error" and "print in progress" in job["message"]
    assert post(client, "/updates/klipper", confirmed=True).status_code == 202     # slot is free again


def test_losing_the_connection_mid_update_is_reported_as_unknown(client, moon):
    moon.routes[("POST", "/machine/update/upgrade")] = requests.ConnectionError("reset")
    post(client, "/updates/moonraker", confirmed=True)
    assert client.get("/api/v1/system/updates").get_json()["job"]["state"] == "unknown"


def test_recover_validates_and_forwards_hard(client, moon):
    assert post(client, "/updates/klipper/recover").status_code == 400
    assert post(client, "/updates/full/recover", confirmed=True).status_code == 400
    assert post(client, "/updates/mainsail/recover", confirmed=True).status_code == 400       # not a git repo
    assert post(client, "/updates/klipper/recover", confirmed=True, hard=True).status_code == 202
    assert moon.posted("/machine/update/recover")[0][3] == {"name": "klipper", "hard": True}
    assert post(client, "/updates/klipper/recover", confirmed=True).status_code == 202
    assert moon.posted("/machine/update/recover")[1][3] == {"name": "klipper", "hard": False}


# ── backups ────────────────────────────────────────────────────────────────────────────────────────────────
def test_backup_listing(client, moon):
    b = client.get("/api/v1/system/backups").get_json()
    assert b["supported"] is True and [x["filename"] for x in b["backups"]] == ["sqldb-backup-20260101-000000.db", "old.db"]


def test_old_moonraker_without_the_backup_api(client, moon):
    moon.routes[("GET", "/server/database/list")] = {"namespaces": ["moonraker"]}      # no "backups" key
    b = client.get("/api/v1/system/backups").get_json()
    assert b["supported"] is False and b["backups"] == []
    r = post(client, "/backups")
    assert r.status_code == 404 and r.get_json()["unsupported"] is True
    del moon.routes[("GET", "/server/database/list")]
    sh.reset_cache()
    assert client.get("/api/v1/system/backups").status_code == 404


def test_backup_create_validates_the_filename(client, moon):
    for bad in ("../x.db", "a/b.db", "x.txt", ".hidden.db", "a b.db", "x" * 120 + ".db", 5, ["x.db"]):
        assert post(client, "/backups", filename=bad).status_code == 400, bad
    assert moon.posted("/server/database/backup") == []
    r = post(client, "/backups", filename="before-update.db")
    assert r.status_code == 201 and r.get_json()["backup_path"] == "/x/new.db"
    assert moon.posted("/server/database/backup")[0][3] == {"filename": "before-update.db"}
    assert post(client, "/backups").status_code == 201
    assert moon.posted("/server/database/backup")[1][3] == {}
    assert post(client, "/backups", filename="old.db").status_code == 409


def test_backup_create_is_refused_during_a_print(client, moon, printing):
    assert post(client, "/backups").status_code == 409


def test_restore_needs_confirmation_a_listed_file_and_no_print(client, moon):
    assert post(client, "/backups/old.db/restore").status_code == 400
    assert post(client, "/backups/old.db/restore", confirmed="true").status_code == 400
    assert post(client, "/backups/ghost.db/restore", confirmed=True).status_code == 404
    assert post(client, "/backups/..%2Fetc%2Fpasswd/restore", confirmed=True).status_code in (400, 404)
    assert post(client, "/backups/notadb/restore", confirmed=True).status_code == 400
    assert moon.posted("/server/database/restore") == []
    r = post(client, "/backups/old.db/restore", confirmed=True)
    assert r.status_code == 200 and moon.posted("/server/database/restore")[0][3] == {"filename": "old.db"}


def test_restore_refused_during_a_print(client, moon, printing):
    assert post(client, "/backups/old.db/restore", confirmed=True).status_code == 409
    assert moon.posted("/server/database/restore") == []


def test_restore_survives_moonraker_restarting_right_away(client, moon):
    moon.routes[("POST", "/server/database/restore")] = requests.ConnectionError("gone")
    r = client.post("/api/v1/system/backups/old.db/restore", json={"confirmed": True})
    assert r.status_code == 200 and r.get_json()["result"] == {"restarting": True}


def test_delete_backup_needs_confirmation_and_a_listed_file(client, moon):
    assert client.delete("/api/v1/system/backups/old.db").status_code == 400
    assert client.delete("/api/v1/system/backups/ghost.db", json={"confirmed": True}).status_code == 404
    assert moon.posted("/server/database/backup") == []
    r = client.delete("/api/v1/system/backups/old.db", json={"confirmed": True})
    assert r.status_code == 200
    call = [c for c in moon.calls if c[0] == "DELETE"][0]
    assert call[1] == "/server/database/backup" and call[2] == "filename=old.db"


# ── peripherals / announcements / alerts ──────────────────────────────────────────────────────────────────────────────
def test_peripherals_are_each_optional(client, moon, monkeypatch):
    monkeypatch.setattr(sysroutes, "_link_health", lambda: {"suspects": [{"path": "1-1.2"}], "events": []})
    del moon.routes[("GET", "/machine/peripherals/usb")]
    moon.routes[("GET", "/machine/peripherals/video")] = Resp(500, "libcamera exploded")
    b = client.get("/api/v1/system/peripherals").get_json()
    assert b["usb"]["available"] is False and b["usb"]["unsupported"] is True
    assert b["video"]["available"] is False and "libcamera" in b["video"]["error"]
    assert b["serial"]["available"] is True and len(b["serial"]["items"]) == 3
    kinds = [d["recommended_kind"] for d in b["serial"]["items"]]
    assert kinds == ["by-id", "by-path", "device"]
    assert b["serial"]["items"][0]["recommended_path"] == "/dev/serial/by-id/usb-Klipper_x-if00"
    assert b["serial"]["items"][2]["recommended_path"] == "/dev/ttyAMA0"
    assert b["link_health"]["suspects"][0]["path"] == "1-1.2"


def test_canbus_is_only_queried_on_request(client, moon):
    b = client.get("/api/v1/system/peripherals").get_json()
    assert b["canbus"]["queried"] is False and not [c for c in moon.calls if "canbus" in c[1]]
    b = client.get("/api/v1/system/peripherals?canbus=can0").get_json()
    assert b["canbus"]["items"][0]["uuid"] == "AABB" and b["canbus"]["interface"] == "can0"
    assert [c for c in moon.calls if "canbus" in c[1]][0][2] == "interface=can0"
    assert client.get("/api/v1/system/peripherals?canbus=can0%26x%3D1").status_code == 400
    assert client.get("/api/v1/system/peripherals?canbus=..%2Fx").status_code == 400


def test_peripherals_work_without_the_usb_link_health_plugin(client, moon, monkeypatch):
    import plugins
    monkeypatch.setitem(__import__("sys").modules, "plugins.usb_link_health", None)    # import fails
    assert client.get("/api/v1/system/peripherals").get_json()["link_health"] is None


def test_announcements_hide_dismissed_ones(client, moon):
    b = client.get("/api/v1/system/announcements").get_json()
    assert [a["id"] for a in b["announcements"]] == ["a/1", "a/2"]


def test_alerts_combine_every_source(client, moon):
    moon.routes[("GET", "/machine/proc_stats")] = dict(PROC, throttled_state={"bits": 0x50005, "flags": []})
    moon.routes[("GET", "/server/info")] = dict(SERVER_INFO, moonraker_version="v0.8.0-5-gdead",
                                                failed_components=["spoolman"])
    b = client.get("/api/v1/system/alerts").get_json()
    ids = {a["id"] for a in b["alerts"]}
    assert {"throttle:undervoltage", "throttle:throttled", "moonraker:outdated", "component:spoolman",
            "update:system", "update:klipper:v0.12.0-140", "update:mainsail:v2.13.0",
            "announcement:a/1", "announcement:a/2"} <= ids
    assert "update:moonraker:v0.9.3" not in ids and "announcement:a/3" not in ids
    by = {a["id"]: a for a in b["alerts"]}
    assert by["throttle:undervoltage"]["severity"] == "critical" and by["throttle:undervoltage"]["notify"] is True
    assert by["announcement:a/1"]["notify"] is True and by["announcement:a/2"]["notify"] is False
    assert b["counts"]["critical"] == 1 and b["min_moonraker"] == "v0.9.0"


def test_throttle_history_is_shown_but_not_notified(client, moon):
    moon.routes[("GET", "/machine/proc_stats")] = dict(PROC, throttled_state={"bits": 0x50000, "flags": []})
    by = {a["id"]: a for a in client.get("/api/v1/system/alerts").get_json()["alerts"]}
    assert by["throttle:history"]["notify"] is False and "throttle:undervoltage" not in by


def test_the_minimum_moonraker_version_can_be_overridden(client, moon, monkeypatch):
    moon.routes[("GET", "/server/info")] = dict(SERVER_INFO, moonraker_version="v0.8.0-5-gdead")
    monkeypatch.setenv("INDUS3D_MIN_MOONRAKER", "v0.7.0")
    assert "moonraker:outdated" not in {a["id"] for a in client.get("/api/v1/system/alerts").get_json()["alerts"]}


def test_a_failed_section_is_reported_not_turned_into_an_error(client, moon):
    del moon.routes[("GET", "/machine/update/status")]
    b = client.get("/api/v1/system/alerts").get_json()
    assert b["sections"]["updates"]["unsupported"] is True and not [a for a in b["alerts"] if a["id"].startswith("update:")]


# ── simulator ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def sim(monkeypatch):
    import workers

    class Sim:
        latest = {"print_state": "standby"}

        def inject_gcode(self, g):
            pass
    monkeypatch.setattr(workers, "_active_worker", Sim())

    def boom(*a, **k):
        raise AssertionError("the simulator must never reach Moonraker")
    monkeypatch.setattr(requests, "request", boom)
    return workers


def test_the_simulator_serves_plausible_stub_data_offline(client, sim):
    b = client.get("/api/v1/system/info").get_json()
    assert b["simulated"] is True and b["host"]["hostname"] == "indus3d-sim" and len(b["mcus"]) == 2
    assert client.get("/api/v1/system/services").get_json()["manageable"] is True
    assert client.get("/api/v1/system/updates").get_json()["pending"] == ["system", "klipper"]
    assert client.get("/api/v1/system/backups").get_json()["backups"]
    assert client.get("/api/v1/system/peripherals").get_json()["serial"]["items"][0]["recommended_kind"] == "by-id"
    assert client.get("/api/v1/system/announcements").get_json()["announcements"] == []
    assert client.get("/api/v1/system/alerts").get_json()["ok"] is True


def test_the_simulator_accepts_actions_with_the_same_gates(client, sim):
    assert post(client, "/services/crowsnest/stop").status_code == 400
    assert post(client, "/services/crowsnest/stop", confirmed=True).status_code == 200
    sh.reset_cache()
    states = {s["name"]: s["active_state"] for s in client.get("/api/v1/system/services").get_json()["services"]}
    assert states["crowsnest"] == "inactive"
    assert post(client, "/updates/klipper", confirmed=True).status_code == 202
    sh.reset_cache()
    assert "klipper" not in client.get("/api/v1/system/updates").get_json()["pending"]
    assert post(client, "/backups", filename="sim-test.db").status_code == 201
    assert any(x["filename"] == "sim-test.db" for x in client.get("/api/v1/system/backups").get_json()["backups"])
    assert client.delete("/api/v1/system/backups/sim-test.db", json={"confirmed": True}).status_code == 200


def test_the_simulator_print_blocks_updates(client, sim):
    sim._active_worker.latest = {"print_state": "paused"}
    assert post(client, "/updates/klipper", confirmed=True).status_code == 409
    assert post(client, "/services/klipper/restart", confirmed=True).status_code == 409


# ── rate limit and auth gate ────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def limited():
    rl._requests.clear(); rl._bans.clear(); rl._violations.clear()
    app = Flask(__name__)
    rl.check_rate_limit(app)
    app.register_blueprint(sysroutes.system_bp, url_prefix="/api/v1/system")
    yield app.test_client()
    rl._requests.clear(); rl._bans.clear(); rl._violations.clear()


def test_system_writes_use_the_strict_rate_limit_not_ui_adjust(limited, moon):
    ip = {"REMOTE_ADDR": "9.9.9.9"}
    codes = [limited.post("/api/v1/system/services/crowsnest/restart", json={"confirmed": True}, environ_base=ip).status_code
             for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    assert limited.post("/api/v1/system/backups", json={}, environ_base=ip).get_json()["category"] == "hardware_cmd"


def test_deleting_a_backup_counts_toward_the_strict_limit(limited, moon):
    ip = {"REMOTE_ADDR": "9.9.9.8"}
    codes = [limited.delete("/api/v1/system/backups/old.db", json={"confirmed": True}, environ_base=ip).status_code
             for _ in range(11)]
    assert codes[10] == 429


def test_reads_are_not_counted_as_hardware_commands(limited, moon):
    ip = {"REMOTE_ADDR": "9.9.9.7"}
    assert all(limited.get("/api/v1/system/info", environ_base=ip).status_code == 200 for _ in range(30))
    assert limited.post("/api/v1/system/services/crowsnest/restart", json={"confirmed": True}, environ_base=ip).status_code == 200


def test_routes_sit_behind_the_auth_gate(monkeypatch):
    from api import auth
    monkeypatch.setattr(auth, "auth_required", lambda: True)
    rl._requests.clear()
    app = Flask(__name__)
    app.secret_key = "x"
    auth.install_auth_gate(app)
    app.register_blueprint(sysroutes.system_bp, url_prefix="/api/v1/system")
    c = app.test_client()
    for method, path in (("get", "/info"), ("get", "/alerts"), ("post", "/services/klipper/restart"),
                         ("post", "/updates/full"), ("delete", "/backups/old.db")):
        assert getattr(c, method)(f"/api/v1/system{path}").status_code == 401, path
    rl._requests.clear()


def test_blueprint_is_registered_on_the_real_app():
    from api.server import app
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert {"/api/v1/system/info", "/api/v1/system/services/<name>/<action>", "/api/v1/system/updates",
            "/api/v1/system/backups/<filename>/restore"} <= rules
