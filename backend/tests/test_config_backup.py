"""Git configuration backup: lazy construction, secrets, restore safety (real git in tmp dirs)."""
import os
import subprocess
import sys
import textwrap

import pytest
from flask import Flask

import services.config_backup as cb
from services.config_backup import ConfigBackupManager, get_manager, reset_manager

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def write(d, name, text):
    path = os.path.join(d, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(d, name):
    with open(os.path.join(d, name)) as f:
        return f.read()


@pytest.fixture
def cfg(tmp_path):
    d = str(tmp_path / "cfg")
    os.makedirs(d)
    write(d, "printer.cfg", "[printer]\nkinematics: cartesian\n")
    write(d, "moonraker.conf", "[server]\nport: 7125\n")
    return d


@pytest.fixture
def mgr(cfg):
    return ConfigBackupManager(config_dir=cfg)


# ── nothing at import / construction time ───────────────────────────────────────
def test_importing_the_module_runs_no_git():
    code = textwrap.dedent("""
        import subprocess, sys
        calls = []
        real = subprocess.run
        subprocess.run = lambda *a, **k: (calls.append(a), real(*a, **k))[1]
        import services.config_backup as cb
        assert cb._manager is None
        assert not calls, calls
        print("ok")
    """)
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr


def test_constructor_and_reads_do_not_init_git(cfg):
    m = ConfigBackupManager(config_dir=cfg)
    assert not os.path.exists(os.path.join(cfg, ".git"))
    assert m.get_history() == [] and m.has_changes() is False
    assert not os.path.exists(os.path.join(cfg, ".git"))
    m.auto_backup("x")
    assert os.path.isdir(os.path.join(cfg, ".git"))


def test_test_session_never_creates_a_repo_in_the_source_tree():
    assert not os.path.exists(os.path.join(BACKEND, "config", ".git"))
    assert os.environ["KLIPPER_CONFIG_DIR"] != os.path.join(BACKEND, "config")


def test_no_config_dir_disables_the_manager(monkeypatch, tmp_path):
    monkeypatch.delenv("KLIPPER_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cb.os.path, "isdir", lambda p: False)
    assert cb.get_config_dir() is None
    reset_manager()
    m = get_manager()
    assert m.enabled is False
    assert m.auto_backup("x")["status"] == "disabled"
    assert m.get_diff("abcdef1")["status"] == "disabled"
    assert m.restore_commit("abcdef1")["status"] == "disabled"
    assert m.get_history() == []


def test_get_manager_is_lazy_singleton():
    reset_manager()
    assert cb._manager is None
    a = get_manager()
    assert get_manager() is a


# ── core behaviour ──────────────────────────────────────────────────────────────
def test_backup_history_diff(mgr, cfg):
    res = mgr.auto_backup(reason="Initial")
    assert res["status"] == "committed" and "printer.cfg" in res["files"]
    assert mgr.auto_backup("again")["status"] == "unchanged"
    write(cfg, "printer.cfg", "[printer]\nkinematics: cartesian\nmax_velocity: 300\n")
    assert mgr.has_changes()
    assert mgr.auto_backup("Modified")["status"] == "committed"
    hist = mgr.get_history()
    assert len(hist) == 2 and "Modified" in hist[0]["message"]
    assert "max_velocity" in mgr.get_diff(hist[0]["commit"])["diff"]
    assert "max_velocity" in mgr.get_diff(hist[0]["short_commit"])["diff"]


@pytest.mark.parametrize("ref", ["HEAD", "HEAD~1", "master", "main", "--all", "abc", "zzzzzzz", "", "deadbeef1",
                                 "HEAD^{tree}", "1234567;rm -rf /", None, 5])
def test_diff_rejects_anything_but_a_known_commit(mgr, ref):
    mgr.auto_backup("a")
    assert "error" in mgr.get_diff(ref)


# ── secrets ─────────────────────────────────────────────────────────────────────
def test_secret_files_and_content_are_never_committed(mgr, cfg):
    write(cfg, "telegram.conf", "[telegram]\nchat: 1\n")
    write(cfg, "my_secrets.cfg", "[x]\na: b\n")
    write(cfg, "notify.cfg", "[notifier x]\nurl: discord://\ntoken: abc123\n")
    write(cfg, "hooks.cfg", "[a]\nurl: https://discord.com/api/webhooks/123456/abcDEF-xyz\n")
    write(cfg, "tg.cfg", "[a]\nv: 123456789:AAH3k9Zx1mQ7pLw2eRt5yUi8oPa0sDfGhJk\n")
    write(cfg, "mqtt.cfg", "[mqtt]\nusername: bob\n")
    write(cfg, "broker.cfg", "[a]\nbroker: mqtt://bob:hunter2@host\n")
    write(cfg, "key.cfg", "[a]\napi_key = zzz\n")
    write(cfg, "ok.cfg", "[safe]\nvalue: 1\ntoken:\n# password: commented\n")
    res = mgr.auto_backup("snap")
    assert res["status"] == "committed"
    assert set(res["skipped_secrets"]) == {"telegram.conf", "my_secrets.cfg", "notify.cfg", "hooks.cfg",
                                           "tg.cfg", "mqtt.cfg", "broker.cfg", "key.cfg"}
    assert "ok.cfg" in res["files"]
    _, tracked, _ = mgr._run_git(["ls-files"])
    assert "token" not in tracked.replace("ok.cfg", "")           # nothing secret tracked
    for name in res["skipped_secrets"]:
        assert name not in tracked.split()
    _, log, _ = mgr._run_git(["log", "-p", "--all"])
    assert "hunter2" not in log and "abc123" not in log and "AAH3k9" not in log


def test_default_gitignore_lists_secret_patterns(mgr, cfg):
    mgr.auto_backup("x")
    ig = read(cfg, ".gitignore")
    for pat in ("*token*", "*secret*", "*password*", "*.env", ".env*", "*credentials*", "*telegram*"):
        assert pat in ig


def test_json_is_opt_in(mgr, cfg, monkeypatch):
    write(cfg, "mainsail.json", '{"a": 1}')
    assert "mainsail.json" not in mgr.auto_backup("x")["files"]
    monkeypatch.setenv("INDUS3D_CONFIG_BACKUP_JSON", "1")
    assert "mainsail.json" in mgr.auto_backup("y")["files"]


def test_secret_json_not_tracked_even_when_opted_in(mgr, cfg, monkeypatch):
    monkeypatch.setenv("INDUS3D_CONFIG_BACKUP_JSON", "1")
    write(cfg, "svc.json", '{"api_key": "abc"}')
    res = mgr.auto_backup("x")
    assert "svc.json" in res["skipped_secrets"]


# ── restore ─────────────────────────────────────────────────────────────────────
def two_commits(mgr, cfg):
    mgr.auto_backup("one")
    write(cfg, "printer.cfg", "[printer]\nkinematics: corexy\n")
    write(cfg, "extra.cfg", "[extra]\n")
    mgr.auto_backup("two")
    return mgr.get_history()


def test_restore_touches_only_tracked_files_and_reports_changes(mgr, cfg):
    hist = two_commits(mgr, cfg)
    write(cfg, "brand_new.cfg", "[new]\n")               # untracked: must survive
    res = mgr.restore_commit(hist[1]["short_commit"])
    assert res["status"] == "restored" and res["changed_files"] == ["printer.cfg"]
    assert res["needs_firmware_restart"] is True
    assert "cartesian" in read(cfg, "printer.cfg")
    assert os.path.exists(os.path.join(cfg, "brand_new.cfg"))
    assert os.path.exists(os.path.join(cfg, "extra.cfg"))   # not in the old commit; never deleted


def test_restore_takes_a_safety_snapshot_first(mgr, cfg):
    hist = two_commits(mgr, cfg)
    write(cfg, "printer.cfg", "[printer]\nkinematics: delta\nUNSAVED: yes\n")
    res = mgr.restore_commit(hist[1]["commit"])
    assert res["snapshot"]
    msgs = [h["message"] for h in mgr.get_history()]
    assert any("Pre-restore safety snapshot" in m for m in msgs)
    snap = [h for h in mgr.get_history() if "Pre-restore" in h["message"]][0]
    assert "UNSAVED" in mgr.get_diff(snap["commit"])["diff"]


@pytest.mark.parametrize("ref", ["HEAD~1", "master", "main", "HEAD", "abc", "../../x", "deadbeefdeadbeef", "", None])
def test_restore_rejects_non_hash_refs(mgr, cfg, ref):
    two_commits(mgr, cfg)
    before = read(cfg, "printer.cfg")
    res = mgr.restore_commit(ref)
    assert res["status"] == "error"
    assert read(cfg, "printer.cfg") == before


def test_restore_rejects_commit_not_in_history(mgr, cfg):
    two_commits(mgr, cfg)
    mgr._run_git(["checkout", "-q", "-b", "side"])
    write(cfg, "printer.cfg", "[side]\n")
    mgr.auto_backup("side commit")
    side = mgr.get_history()[0]["commit"]
    mgr._run_git(["checkout", "-q", "-"])
    assert mgr.restore_commit(side)["status"] == "error"


def test_restore_keeps_private_copy_of_unsnapshotted_secret_file(mgr, cfg):
    write(cfg, "printer.cfg", "[printer]\nk: 1\n")
    mgr.auto_backup("one")
    first = mgr.get_history()[0]["commit"]
    write(cfg, "printer.cfg", "[printer]\nk: 2\nsecret: s3cr3t\n")     # now looks secret: not snapshotted
    res = mgr.restore_commit(first)
    assert res["status"] == "restored" and res["private_copies"]
    kept = read(cfg, res["private_copies"][0])
    assert "s3cr3t" in kept
    _, log, _ = mgr._run_git(["log", "-p", "--all"])
    assert "s3cr3t" not in log


# ── routes ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(mgr, monkeypatch):
    monkeypatch.setattr(cb, "_manager", mgr)
    from api.server import app
    return app.test_client()


def _busy(monkeypatch, busy):
    import api.routes.printer as pr
    monkeypatch.setattr(pr, "_printer_is_busy", lambda: busy)


def test_route_restore_requires_confirmation_and_idle(client, mgr, cfg, monkeypatch):
    hist = two_commits(mgr, cfg)
    url = "/api/v1/printer/config/backup/restore"
    _busy(monkeypatch, False)
    r = client.post(url, json={"commit": hist[1]["commit"]})
    assert r.status_code == 409 and r.get_json()["needs_confirmation"]
    assert "corexy" in read(cfg, "printer.cfg")
    _busy(monkeypatch, True)
    r = client.post(url, json={"commit": hist[1]["commit"], "confirmed": True})
    assert r.status_code == 409 and "corexy" in read(cfg, "printer.cfg")
    _busy(monkeypatch, False)
    assert client.post(url, json={"commit": "HEAD~1", "confirmed": True}).status_code == 404
    assert client.post(url, json={"confirmed": True}).status_code == 400
    r = client.post(url, json={"commit": hist[1]["commit"], "confirmed": True})
    assert r.status_code == 200 and r.get_json()["changed_files"] == ["printer.cfg"]


def test_route_manual_backup_requires_confirmation(client, cfg, monkeypatch):
    r = client.post("/api/v1/printer/config/backup", json={})
    assert r.status_code == 409
    r = client.post("/api/v1/printer/config/backup", json={"confirmed": True, "reason": "hi\nthere"})
    assert r.status_code == 200 and r.get_json()["status"] == "committed"


def test_route_diff_rejects_unknown(client, mgr, cfg):
    mgr.auto_backup("a")
    assert client.get("/api/v1/printer/config/backup/diff?commit=HEAD~3").status_code == 404
    good = mgr.get_history()[0]["commit"]
    assert client.get(f"/api/v1/printer/config/backup/diff?commit={good}").status_code == 200


def test_routes_when_disabled(monkeypatch):
    monkeypatch.setattr(cb, "_manager", ConfigBackupManager(config_dir=None))
    from api.server import app
    c = app.test_client()
    r = c.get("/api/v1/printer/config/backups")
    assert r.status_code == 200 and r.get_json()["status"] == "disabled"
    for r in (c.post("/api/v1/printer/config/backup", json={"confirmed": True}),
              c.post("/api/v1/printer/config/backup/restore", json={"commit": "abcdef1", "confirmed": True}),
              c.get("/api/v1/printer/config/backup/diff?commit=abcdef1")):
        assert r.status_code == 409 and r.get_json()["status"] == "disabled"


# ── auto-backup after config save never breaks the save ─────────────────────────
def test_save_survives_backup_failure_and_timeout(monkeypatch):
    from unittest import mock
    from api.server import app

    def post_save():
        old = mock.Mock(ok=True, text="a: 1\n")
        up = mock.Mock(text="{}", status_code=200, ok=True)
        with mock.patch("api.routes.printer.requests.get", return_value=old), \
             mock.patch("api.routes.printer.requests.post", return_value=up), \
             mock.patch("db.models.get_connection"):
            return app.test_client().post("/api/v1/printer/config/printer.cfg", data="a: 2\n")

    class Boom(ConfigBackupManager):
        def auto_backup(self, reason=""):
            raise RuntimeError("git exploded")

    monkeypatch.setattr(cb, "_manager", Boom(config_dir="/nonexistent"))
    assert post_save().status_code == 200

    import time

    class Slow(ConfigBackupManager):
        def auto_backup(self, reason=""):
            time.sleep(1.0)
            return {"status": "unchanged"}

    slow = Slow(config_dir="/nonexistent")
    t = time.time()
    res = slow.auto_backup_bounded("x", timeout=0.1)
    assert res["status"] == "pending" and time.time() - t < 0.8
