import pytest
from flask import Flask
from api.rate_limiter import check_rate_limit, _requests, _bans, _violations
from api.auth import install_auth_gate
from config.settings import settings

@pytest.fixture
def client():
    app = Flask(__name__)
    check_rate_limit(app)
    
    @app.route("/api/v1/auth/login", methods=["POST"])
    def login(): return "ok"
    
    @app.route("/api/v1/printer/stop", methods=["POST"])
    def stop(): return "ok"
    
    @app.route("/api/v1/control/jog", methods=["POST"])
    def jog(): return "ok"
    
    @app.route("/api/v1/twin", methods=["GET"])
    def twin(): return "ok"
    
    return app.test_client()

@pytest.fixture(autouse=True)
def reset_rate_limit():
    _requests.clear()
    _bans.clear()
    _violations.clear()
    yield
    _requests.clear()
    _bans.clear()
    _violations.clear()

def test_login_rate_limiting(client):
    # 5 attempts allowed
    for _ in range(5):
        resp = client.post("/api/v1/auth/login", environ_base={'REMOTE_ADDR': '1.2.3.4'})
        assert resp.status_code == 200
        
    # 6th attempt should fail with 429
    resp = client.post("/api/v1/auth/login", environ_base={'REMOTE_ADDR': '1.2.3.4'})
    assert resp.status_code == 429
    assert resp.json["category"] == "login"

def test_hardware_cmd_rate_limiting(client):
    for _ in range(30):
        resp = client.post("/api/v1/printer/stop", environ_base={'REMOTE_ADDR': '1.2.3.5'})
        assert resp.status_code == 200
        
    resp = client.post("/api/v1/printer/stop", environ_base={'REMOTE_ADDR': '1.2.3.5'})
    assert resp.status_code == 429
    assert resp.json["category"] == "hardware_cmd"

def test_ban_after_repeated_violations(client):
    # 3 violations trigger a ban
    # violation 1
    for _ in range(6): client.post("/api/v1/auth/login", environ_base={'REMOTE_ADDR': '9.9.9.9'})
    # violation 2
    for _ in range(2): client.post("/api/v1/auth/login", environ_base={'REMOTE_ADDR': '9.9.9.9'})
    # violation 3
    resp = client.post("/api/v1/auth/login", environ_base={'REMOTE_ADDR': '9.9.9.9'})
    
    assert resp.status_code == 403
    assert "banned" in resp.json["error"]

def test_jog_allows_rapid_clicks_and_does_not_ban(client):
    ip = "192.168.1.100"
    # Jogging allows high burst rates (e.g. 50 rapid clicks)
    for _ in range(50):
        resp = client.post("/api/v1/control/jog", environ_base={'REMOTE_ADDR': ip})
        assert resp.status_code == 200

def test_hardware_violations_do_not_ban_ip(client):
    ip = "192.168.1.101"
    # Cause multiple violations on hardware_cmd
    for _ in range(20):
        client.post("/api/v1/printer/stop", environ_base={'REMOTE_ADDR': ip})
    
    # Despite exceeding hardware limit, the IP is NOT banned from reading twin telemetry or general endpoints
    resp = client.get("/api/v1/twin", environ_base={'REMOTE_ADDR': ip})
    assert resp.status_code == 200


def test_auth_keeps_login_shell_public_but_gates_api(monkeypatch):
    """The SPA must load before a user can submit the configured password."""
    monkeypatch.setattr(settings, "INDUS3D_PASSWORD", "test-password")
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/")
    def frontend():
        return "login shell"

    @app.route("/api/v1/printer/status")
    def protected_status():
        return "printer state"

    install_auth_gate(app)
    test_client = app.test_client()

    assert test_client.get("/").status_code == 200
    assert test_client.get("/api/v1/printer/status").status_code == 401


def test_ldap_auth_flow(monkeypatch):
    """Test LDAP authentication integration when LDAP server is configured."""
    from api.auth import auth_bp
    monkeypatch.setenv("INDUS3D_LDAP_SERVER", "ldap://127.0.0.1:389")
    monkeypatch.setattr("api.auth._check_ldap_credentials", lambda u, p: u == "operator" and p == "secret123")

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp)
    client = app.test_client()

    # Invalid credentials
    resp = client.post("/api/v1/auth/login", json={"username": "operator", "password": "wrong"})
    assert resp.status_code == 401

    # Valid LDAP credentials
    resp = client.post("/api/v1/auth/login", json={"username": "operator", "password": "secret123"})
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
    assert resp.json["auth_type"] == "ldap"
    assert resp.json["user"] == "operator"

