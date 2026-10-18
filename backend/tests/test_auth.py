import pytest
from flask import Flask
from api.rate_limiter import check_rate_limit, _requests, _bans, _violations

@pytest.fixture
def client():
    app = Flask(__name__)
    check_rate_limit(app)
    
    @app.route("/api/v1/auth/login", methods=["POST"])
    def login(): return "ok"
    
    @app.route("/api/v1/printer/stop", methods=["POST"])
    def stop(): return "ok"
    
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
    for _ in range(10):
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
