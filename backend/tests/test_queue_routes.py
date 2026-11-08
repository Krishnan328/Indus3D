"""Tests for api/routes/queue.py: totals/ETA, multiply, reorder planning, unsupported job_queue, 502, simulator."""
import json
from unittest import mock

import pytest
import requests

from api.routes import files as F
from api.routes import queue as Q
from mr_fakes import FakeMR, Resp, err, ok


# ── pure helpers ──────────────────────────────────────────────────────────────
def J(i, fn="a.gcode", est=100, fil=1000.0, g=3.0):
    meta = {}
    if est is not None:
        meta = {"estimated_time": est, "filament_total": fil, "filament_weight_total": g}
    return {"id": i, "filename": fn, "meta": meta}


def test_summarize_totals_and_eta_with_print_in_progress():
    jobs = [J("1", est=100), J("2", est=200)]
    s = Q.summarize(jobs, 50, now=1000.0)
    assert s["count"] == 2 and s["time_s"] == 300 and s["filament_mm"] == 2000.0 and s["filament_g"] == 6.0
    assert jobs[0]["eta_ts"] == 1150.0 and jobs[1]["eta_ts"] == 1350.0       # 50 s left on the running print
    assert s["finish_ts"] == 1350.0 and s["finish_is_lower_bound"] is False and s["missing_meta"] == 0


def test_summarize_missing_metadata_makes_eta_a_lower_bound():
    jobs = [J("1", est=100), J("2", est=None), J("3", est=100)]
    s = Q.summarize(jobs, 0, now=0.0)
    assert s["missing_meta"] == 1 and s["time_s"] == 200
    assert jobs[0]["eta_ts"] == 100.0 and jobs[1]["eta_ts"] is None and jobs[2]["eta_ts"] is None
    assert s["finish_ts"] is None and s["finish_is_lower_bound"] is True


def test_summarize_empty_queue():
    s = Q.summarize([], None, now=5.0)
    assert s["count"] == 0 and s["finish_ts"] is None and s["finish_is_lower_bound"] is False


def test_expand_filenames_multiply():
    assert Q.expand_filenames(["a", "b"], 3) == ["a", "a", "a", "b", "b", "b"]
    assert Q.expand_filenames(["a", "b"], 2, interleave=True) == ["a", "b", "a", "b"]
    assert Q.expand_filenames(["a"], 1) == ["a"]


def test_plan_reorder():
    cur = [{"id": i, "filename": f"{i}.gcode"} for i in "ABCD"]
    assert Q.plan_reorder(cur, list("ABCD")) == {"noop": True}
    assert Q.plan_reorder(cur, list("CABD")) == {"jump": "C"}                  # one job to the front keeps ids
    assert Q.plan_reorder(cur, list("ABDC")) == {"readd": ["D.gcode", "C.gcode"], "remove": ["C", "D"]}   # prefix A,B kept
    assert Q.plan_reorder(cur, list("DCBA")) == {"readd": ["D.gcode", "C.gcode", "B.gcode", "A.gcode"], "remove": list("ABCD")}
    with pytest.raises(ValueError):
        Q.plan_reorder(cur, list("ABC"))
    with pytest.raises(ValueError):
        Q.plan_reorder(cur, list("ABCX"))


# ── fake Moonraker with a stateful job queue ──────────────────────────────────
class QueueMR(FakeMR):
    def __init__(self, config=None):
        super().__init__()
        self.state = "ready"
        self.jobs = []
        self.n = 0
        self.config = config if config is not None else {"job_queue": {"automatic_transition": "False"}}
        self.meta = {}
        self.routes[("GET", "/server/job_queue/status")] = lambda kw: ok(self.view())
        self.routes[("POST", "/server/job_queue/job")] = self.add
        self.routes[("DELETE", "/server/job_queue/job")] = self.remove
        self.routes[("POST", "/server/job_queue/pause")] = lambda kw: self.set_state("paused")
        self.routes[("POST", "/server/job_queue/start")] = lambda kw: self.set_state("ready")
        self.routes[("POST", "/server/job_queue/jump")] = self.jump
        self.routes[("GET", "/server/config")] = lambda kw: ok({"config": self.config})
        self.routes[("GET", "/server/files/metadata")] = self.metadata

    def view(self):
        return {"queue_state": self.state, "queued_jobs": [
            {"filename": f, "job_id": i, "time_added": 1.0, "time_in_queue": 2.0} for i, f in self.jobs]}

    def add(self, kw):
        for f in kw["json"]["filenames"]:
            self.n += 1
            self.jobs.append((f"{self.n:04d}", f))
        return ok(self.view())

    def remove(self, kw):
        p = kw["params"]
        if p.get("all") == "true":
            self.jobs = []
        else:
            ids = p["job_ids"].split(",")
            if not any(i in dict(self.jobs) for i in ids):
                return err(404, "No jobs matching the given ids")
            self.jobs = [(i, f) for i, f in self.jobs if i not in ids]
        return ok(self.view())

    def set_state(self, s):
        self.state = s
        return ok(self.view())

    def jump(self, kw):
        jid = kw["params"]["job_id"]
        hit = [j for j in self.jobs if j[0] == jid]
        if not hit:
            return err(404, f"Job {jid} not found")
        self.jobs.remove(hit[0])
        self.jobs.insert(0, hit[0])
        return ok(self.view())

    def metadata(self, kw):
        fn = kw["params"]["filename"]
        if fn not in self.meta:
            return err(404, f"Metadata not available for {fn}")
        return ok(self.meta[fn])

    def order(self):
        return [f for _, f in self.jobs]


@pytest.fixture
def client():
    from api.server import app
    from api import rate_limiter as rl
    rl._requests.clear(); rl._bans.clear(); rl._violations.clear()      # one process, one client IP: start each test fresh
    F.reset_cache()
    Q.reset_cache()
    return app.test_client()


@pytest.fixture
def mr(request):
    fake = QueueMR()
    prog = {"state": "standby", "busy": False, "filename": "", "remaining_s": 0, "progress": None}
    fake.progress = prog
    with mock.patch("api.mr_client.requests.request", side_effect=fake), \
            mock.patch.object(F, "_is_simulator", return_value=False), \
            mock.patch.object(Q, "_print_progress", side_effect=lambda: dict(fake.progress)):
        yield fake


def names(client):
    return [j["filename"] for j in client.get("/api/v1/queue/status").get_json()["jobs"]]


# ── status ────────────────────────────────────────────────────────────────────
def test_status_totals_eta_and_manual_start_note(client, mr):
    mr.meta = {"a.gcode": {"estimated_time": 600, "filament_total": 5000, "filament_weight_total": 15, "slicer": "Cura",
                           "thumbnails": [{"width": 300, "height": 300, "size": 1, "relative_path": ".thumbs/a-300.png"},
                                          {"width": 32, "height": 32, "size": 1, "relative_path": ".thumbs/a-32.png"}]},
               "b.gcode": {"estimated_time": 300}}
    mr.state = "paused"
    mr.add({"json": {"filenames": ["a.gcode", "b.gcode", "nometa.gcode", "a.gcode"]}})
    mr.progress.update(state="printing", busy=True, filename="cur.gcode", remaining_s=120)
    s = client.get("/api/v1/queue/status").get_json()
    assert s["available"] is True and s["state"] == "paused"
    assert [j["filename"] for j in s["jobs"]] == ["a.gcode", "b.gcode", "nometa.gcode", "a.gcode"]
    assert s["jobs"][0]["thumb"] == ".thumbs/a-32.png" and s["jobs"][0]["has_meta"] is True
    assert s["jobs"][2]["has_meta"] is False
    t = s["totals"]
    assert t["count"] == 4 and t["missing_meta"] == 1 and t["time_s"] == 600 + 300 + 600
    assert t["remaining_current_s"] == 120 and t["finish_ts"] is None and t["finish_is_lower_bound"] is True
    assert s["jobs"][0]["eta_ts"] - s["jobs"][0]["eta_ts"] % 1 > 0
    assert s["jobs"][1]["eta_ts"] - s["jobs"][0]["eta_ts"] == pytest.approx(300)
    assert s["manual_start"] is True and "by hand" in s["note"]
    metas = [c for c in mr.calls if c[1] == "/server/files/metadata"]
    assert len(metas) == 3                                   # one lookup per distinct file, not per job


def test_status_metadata_is_cached_between_polls(client, mr):
    mr.meta = {"a.gcode": {"estimated_time": 10}}
    mr.add({"json": {"filenames": ["a.gcode"]}})
    client.get("/api/v1/queue/status")
    client.get("/api/v1/queue/status")
    assert len([c for c in mr.calls if c[1] == "/server/files/metadata"]) == 1


def test_status_automatic_transition_is_reported(client):
    fake = QueueMR(config={"job_queue": {"automatic_transition": "True"}})
    fake.progress = {"state": "standby", "busy": False, "filename": "", "remaining_s": 0, "progress": None}
    with mock.patch("api.mr_client.requests.request", side_effect=fake), mock.patch.object(F, "_is_simulator", return_value=False), \
            mock.patch.object(Q, "_print_progress", side_effect=lambda: dict(fake.progress)):
        s = client.get("/api/v1/queue/status").get_json()
    assert s["automatic_transition"] is True and s["manual_start"] is False


def test_missing_job_queue_gives_setup_snippet(client, mr):
    for key in [("GET", "/server/job_queue/status"), ("POST", "/server/job_queue/job"), ("POST", "/server/job_queue/start"),
                ("DELETE", "/server/job_queue/job"), ("POST", "/server/job_queue/pause"), ("POST", "/server/job_queue/jump")]:
        mr.routes[key] = err(404, "Not Found")
    s = client.get("/api/v1/queue/status")
    assert s.status_code == 200 and s.get_json()["available"] is False
    assert "[job_queue]" in s.get_json()["setup"]["snippet"]
    r = client.post("/api/v1/queue/add", json={"filenames": ["a.gcode"]})
    assert r.status_code == 501 and r.get_json()["unsupported"] and "[job_queue]" in r.get_json()["setup"]["snippet"]
    for path, body in [("start", {}), ("pause", {}), ("remove", {"all": True}), ("jump", {"id": "1"})]:
        assert client.post(f"/api/v1/queue/{path}", json=body).status_code == 501


def test_moonraker_unreachable_is_502(client):
    with mock.patch("api.mr_client.requests.request", side_effect=requests.ConnectionError("down")), \
            mock.patch.object(F, "_is_simulator", return_value=False):
        assert client.get("/api/v1/queue/status").status_code == 502
        assert client.post("/api/v1/queue/start", json={}).status_code == 502


# ── add / multiply ────────────────────────────────────────────────────────────
def test_add_and_multiply(client, mr):
    r = client.post("/api/v1/queue/add", json={"filenames": ["a.gcode", "sub/b.gcode"], "repeat": 3})
    assert r.status_code == 200 and r.get_json()["added"] == 6
    assert mr.order() == ["a.gcode"] * 3 + ["sub/b.gcode"] * 3
    sent = [c for c in mr.calls if c[0] == "POST" and c[1] == "/server/job_queue/job"][0][2]["json"]
    assert sent["reset"] is False


def test_add_at_front_jumps_new_jobs_in_order(client, mr):
    mr.add({"json": {"filenames": ["old1.gcode", "old2.gcode"]}})
    r = client.post("/api/v1/queue/add", json={"filenames": ["x.gcode", "y.gcode"], "position": "front"})
    assert r.status_code == 200
    assert mr.order() == ["x.gcode", "y.gcode", "old1.gcode", "old2.gcode"]


@pytest.mark.parametrize("body", [
    {}, {"filenames": []}, {"filenames": "a.gcode"}, {"filenames": ["../a.gcode"]}, {"filenames": ["/etc/passwd"]},
    {"filenames": ["a.gcode"], "repeat": 0}, {"filenames": ["a.gcode"], "repeat": 51}, {"filenames": ["a.gcode"], "repeat": "2"},
    {"filenames": ["a.gcode"], "repeat": True}, {"filenames": ["a.gcode"], "position": "middle"},
    {"filenames": ["a.gcode"] * 40, "repeat": 6},
])
def test_add_validation(client, mr, body):
    r = client.post("/api/v1/queue/add", json=body)
    assert r.status_code == 400
    assert mr.jobs == []


# ── remove / pause / start / jump ─────────────────────────────────────────────
def test_remove_ids_and_all(client, mr):
    mr.add({"json": {"filenames": ["a", "b", "c"]}})
    assert client.post("/api/v1/queue/remove", json={"ids": ["0001", "0003"]}).get_json()["count"] == 1
    assert mr.order() == ["b"]
    assert [c for c in mr.calls if c[0] == "DELETE"][0][2]["params"] == {"job_ids": "0001,0003"}
    assert client.post("/api/v1/queue/remove", json={"all": True}).get_json()["count"] == 0
    assert client.post("/api/v1/queue/remove", json={"ids": ["a,b"]}).status_code == 400
    assert client.post("/api/v1/queue/remove", json={}).status_code == 400
    assert client.post("/api/v1/queue/remove", json={"all": "true"}).status_code == 400


def test_pause_start_and_start_refused_during_print(client, mr):
    assert client.post("/api/v1/queue/pause", json={}).get_json()["state"] == "paused"
    mr.progress.update(state="printing", busy=True, filename="x.gcode", remaining_s=5)
    r = client.post("/api/v1/queue/start", json={})
    assert r.status_code == 409 and r.get_json()["code"] == "busy"
    assert mr.state == "paused"
    mr.progress.update(state="complete", busy=False)
    assert client.post("/api/v1/queue/start", json={}).get_json()["state"] == "ready"


def test_jump(client, mr):
    mr.add({"json": {"filenames": ["a", "b", "c"]}})
    assert client.post("/api/v1/queue/jump", json={"id": "0003"}).status_code == 200
    assert mr.order() == ["c", "a", "b"]
    assert client.post("/api/v1/queue/jump", json={"id": "nope"}).status_code == 404
    assert client.post("/api/v1/queue/jump", json={}).status_code == 400


# ── reorder ───────────────────────────────────────────────────────────────────
def test_reorder_by_readd_keeps_prefix_and_never_loses_jobs(client, mr):
    mr.add({"json": {"filenames": ["a", "b", "c", "d"]}})
    r = client.post("/api/v1/queue/reorder", json={"ids": ["0001", "0002", "0004", "0003"]})
    assert r.status_code == 200 and r.get_json()["method"] == "readd"
    assert mr.order() == ["a", "b", "d", "c"]
    add_idx = [i for i, c in enumerate(mr.calls) if c[0] == "POST" and c[1] == "/server/job_queue/job"][-1]
    del_idx = [i for i, c in enumerate(mr.calls) if c[0] == "DELETE"][-1]
    assert add_idx < del_idx                                    # add first, remove second


def test_reorder_single_move_to_front_uses_jump(client, mr):
    mr.add({"json": {"filenames": ["a", "b", "c"]}})
    r = client.post("/api/v1/queue/reorder", json={"ids": ["0003", "0001", "0002"]})
    assert r.get_json()["method"] == "jump" and mr.order() == ["c", "a", "b"]
    assert mr.jobs[0][0] == "0003"                              # id preserved


def test_reorder_noop_and_stale(client, mr):
    mr.add({"json": {"filenames": ["a", "b"]}})
    assert client.post("/api/v1/queue/reorder", json={"ids": ["0001", "0002"]}).get_json()["method"] == "none"
    r = client.post("/api/v1/queue/reorder", json={"ids": ["0001"]})
    assert r.status_code == 409 and r.get_json()["code"] == "queue_changed"
    assert client.post("/api/v1/queue/reorder", json={"ids": []}).status_code == 400
    assert mr.order() == ["a", "b"]


def test_reorder_tolerates_job_that_started_meanwhile(client, mr):
    mr.add({"json": {"filenames": ["a", "b", "c"]}})
    orig_remove = mr.remove

    def racing_remove(kw):                                       # Moonraker already loaded a/b: ids are unknown now
        mr.jobs = [j for j in mr.jobs if j[0] not in ("0001", "0002", "0003")]
        return orig_remove(kw)
    mr.routes[("DELETE", "/server/job_queue/job")] = racing_remove
    r = client.post("/api/v1/queue/reorder", json={"ids": ["0003", "0002", "0001"]})
    assert r.status_code == 200
    assert mr.order() == ["c", "b", "a"]


# ── simulator ─────────────────────────────────────────────────────────────────
@pytest.fixture
def sim(client):
    with mock.patch.object(F, "_is_simulator", return_value=True), \
            mock.patch("api.mr_client.requests.request", side_effect=AssertionError("simulator must not call Moonraker")):
        yield client


def test_sim_queue_flow(sim):
    assert sim.get("/api/v1/queue/status").get_json()["state"] == "paused"
    r = sim.post("/api/v1/queue/add", json={"filenames": ["benchy.gcode", "calibration/pa_test.gcode"], "repeat": 2})
    assert r.get_json()["added"] == 4
    s = sim.get("/api/v1/queue/status").get_json()
    assert s["simulator"] is True and s["totals"]["count"] == 4
    assert s["totals"]["time_s"] == 2 * 3720 + 2 * 900 and s["totals"]["missing_meta"] == 0
    ids = [j["id"] for j in s["jobs"]]
    assert sim.post("/api/v1/queue/reorder", json={"ids": ids[::-1]}).status_code == 200
    s2 = sim.get("/api/v1/queue/status").get_json()
    assert [j["filename"] for j in s2["jobs"]] == ["calibration/pa_test.gcode"] * 2 + ["benchy.gcode"] * 2
    assert sim.post("/api/v1/queue/remove", json={"all": True}).get_json()["count"] == 0
