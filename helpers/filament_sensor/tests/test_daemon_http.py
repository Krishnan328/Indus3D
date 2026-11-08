"""HTTP surface of the filament-sensor daemon: binding, CSRF guard, no CORS."""
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import indus3d_sensor_daemon as d  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))                 # state + csv live under HOME
    ini = tmp_path / "s.ini"
    ini.write_text(f"[api]\nport = {free_port()}\n")
    dm = d.Indus3DSensorDaemon(config_path=str(ini), dry_run=True, monitor=False)
    threading.Thread(target=dm.start_http_server, daemon=True).start()
    for _ in range(50):
        if getattr(dm, "http_server", None):
            break
        time.sleep(0.05)
    yield dm
    dm.http_server.shutdown()
    dm.http_server.server_close()


def get(dm, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{dm.api_port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_binds_to_loopback_by_default(daemon):
    assert daemon.api_host == "127.0.0.1" and daemon.http_server.server_address[0] == "127.0.0.1"


def test_host_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ini = tmp_path / "s.ini"
    ini.write_text(f"[api]\nhost = 0.0.0.0\nport = {free_port()}\n")
    dm = d.Indus3DSensorDaemon(config_path=str(ini), dry_run=True, monitor=False)
    assert dm.api_host == "0.0.0.0"


def test_status_is_json_without_cors_wildcard(daemon):
    code, headers, body = get(daemon, "/status")
    assert code == 200 and b"auto_flow_percent" in body
    assert "Access-Control-Allow-Origin" not in headers


@pytest.mark.parametrize("path", ["/tare_empty", "/calibrate_span?target=1.75", "/reset_spool", "/reset_bowden"])
def test_control_endpoints_refuse_requests_without_the_header(daemon, path, monkeypatch):
    sent = []
    monkeypatch.setattr(daemon, "send_sensor_command", lambda b: sent.append(bytes(b)) or True)
    daemon.mass_used_g = 12.5
    code, _, body = get(daemon, path)
    assert code == 403 and b"X-Indus3D-Action" in body
    assert sent == [] and daemon.mass_used_g == 12.5          # nothing happened


def test_control_endpoints_work_with_the_header(daemon, monkeypatch):
    sent = []
    monkeypatch.setattr(daemon, "send_sensor_command", lambda b: sent.append(bytes(b)) or True)
    h = {"X-Indus3D-Action": "1"}
    assert get(daemon, "/tare_empty", h)[0] == 200 and sent[-1] == bytes([0xF5, 0x22])
    assert get(daemon, "/calibrate_span?target=1.8", h)[0] == 200 and sent[-1] == bytes([0xF5, 0x23, 1800 & 0xFF, 1800 >> 8])
    daemon.mass_used_g = 12.5
    assert get(daemon, "/reset_spool", h)[0] == 200 and daemon.mass_used_g == 0.0


def test_unknown_path_is_404(daemon):
    assert get(daemon, "/nope")[0] == 404


def test_dashboard_defines_the_action_header_before_using_it():
    html = d.DASHBOARD_HTML
    first_use = min(html.index(f"fetch('{p}") for p in ("/tare_empty", "/calibrate_span", "/reset_spool", "/reset_bowden"))
    assert html.index("const ACTION_HEADERS") < first_use
    assert html.count("const ACTION_HEADERS") == 1
    for p in ("/tare_empty", "/reset_spool", "/reset_bowden"):
        assert f"fetch('{p}', {{headers: ACTION_HEADERS}})" in html
