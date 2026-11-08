"""Back-to-back queued jobs: per-print state must reset even when the printer never visibly leaves "printing".

Moonraker's job queue loads the next job within milliseconds of the previous one completing, faster than the
telemetry poll, so consumers that key on printing -> not printing -> printing never see the edge.
"""
from unittest import mock

import pytest

from core.job_tracker import JobEdges, is_new_job, job_ref


def S(state="printing", name="a.gcode", dur=0, **kw):
    return dict({"print_state": state, "filename": name, "print_duration": dur}, **kw)


# ── is_new_job / JobEdges ─────────────────────────────────────────────────────
def test_is_new_job_filename_change_and_duration_reset():
    ref = job_ref(S(dur=3600))
    assert is_new_job(ref, S(name="b.gcode", dur=3601))                  # different file
    assert is_new_job(ref, S(name="a.gcode", dur=2))                     # same file again ("multiply")
    assert not is_new_job(ref, S(dur=3601))                              # same job, progressing
    assert not is_new_job(ref, S(dur=3600))                              # paused: duration constant
    assert not is_new_job(ref, S(dur=3598))                              # tiny jitter is not a restart
    assert not is_new_job(None, S())


def test_empty_filename_while_loading_is_not_a_new_job():
    ref = job_ref(S(dur=100))
    assert not is_new_job(ref, S(name="", dur=101))
    assert not is_new_job(job_ref(S(name="", dur=100)), S(name="b.gcode", dur=101))


def test_job_edges_normal_lifecycle():
    e = JobEdges()
    assert e.step(S("standby", "")) == (None, False, False)
    assert e.step(S("printing", "a", 1)) == (None, True, False)
    assert e.step(S("printing", "a", 2)) == (None, False, False)
    assert e.step(S("complete", "a", 2)) == ("complete", False, False)
    assert e.step(S("printing", "b", 1)) == (None, True, False)
    assert e.step(S("cancelled", "b", 5)) == ("cancelled", False, False)


def test_job_edges_back_to_back_is_end_then_start_in_one_tick():
    e = JobEdges()
    e.step(S("printing", "a", 3600))
    assert e.step(S("printing", "b", 1)) == ("complete", True, True)     # other file
    assert e.step(S("printing", "b", 2)) == (None, False, False)
    assert e.step(S("printing", "b", 5000)) == (None, False, False)
    assert e.step(S("printing", "b", 0)) == ("complete", True, True)     # same file, queue multiply


# ── run recorder ──────────────────────────────────────────────────────────────
def test_run_recorder_splits_back_to_back_runs():
    from plugins.run_recorder import RunRecorder
    r = RunRecorder(archive=False)
    done = []
    r.on_finish(done.append)
    r.tick(S("printing", "a.gcode", 10, progress=0.5), {"now": 0.0})
    r.on_sent([{"command": "M221 S95", "ok": True, "ts": 1.0}], {"now": 1.0, "snap": {"progress": 0.5}, "corrections": []})
    first_id = r.current["id"]
    r.tick(S("printing", "b.gcode", 1, progress=0.0), {"now": 100.0})     # no non-printing tick in between
    assert len(done) == 1 and done[0]["filename"] == "a.gcode" and done[0]["final_state"] == "complete"
    assert len(done[0]["commands"]) == 1
    assert r.current["id"] != first_id and r.current["filename"] == "b.gcode"
    assert r.current["commands"] == [] and r.current["progress"] == 0.0
    r.tick(S("printing", "b.gcode", 500, progress=0.01), {"now": 101.0})
    assert len(done) == 1                                                  # same job continues, no spurious split
    r.tick(S("printing", "b.gcode", 0, progress=0.0), {"now": 200.0})      # same file again
    assert len(done) == 2 and done[1]["filename"] == "b.gcode"


def test_run_recorder_unchanged_with_a_visible_gap():
    from plugins.run_recorder import RunRecorder
    r = RunRecorder(archive=False)
    done = []
    r.on_finish(done.append)
    r.tick(S("printing", "a.gcode", 10), {"now": 0.0})
    r.tick(S("complete", "a.gcode", 10), {"now": 5.0})
    r.tick(S("printing", "b.gcode", 1), {"now": 6.0})
    assert len(done) == 1 and r.current["filename"] == "b.gcode"


# ── spool planner ─────────────────────────────────────────────────────────────
def test_spool_planner_rechecks_for_each_queued_job():
    from plugins.spool_planner import SpoolPlanner
    notes = []
    sp = SpoolPlanner(get_meta=lambda f: {"filament_weight_total": 200}, get_remaining=lambda: (50.0, "sensor"),
                      notify=notes.append)
    sp.tick(S("printing", "a.gcode", 10), {})
    sp.tick(S("printing", "a.gcode", 11), {})
    assert len(notes) == 1
    sp.tick(S("printing", "b.gcode", 1), {})                                # next queued job: its own check
    assert len(notes) == 2 and "b.gcode" in notes[1]
    sp.tick(S("printing", "b.gcode", 2), {})
    assert len(notes) == 2


# ── the telemetry worker itself ───────────────────────────────────────────────
def _moonraker_payload(state, name, duration, filament=0.0):
    return {"result": {"status": {
        "toolhead": {"position": [10, 10, 0.4, 0]}, "motion_report": {"live_position": [10, 10, 0.4, 0], "live_velocity": 0},
        "extruder": {"temperature": 210.0, "target": 210.0, "power": 0.3}, "heater_bed": {"temperature": 60.0, "target": 60.0},
        "print_stats": {"state": state, "filename": name, "print_duration": duration, "filament_used": filament},
        "display_status": {"progress": 0.5}, "gcode_move": {"speed_factor": 1.0, "extrude_factor": 1.0}}}}


@pytest.fixture
def worker():
    from workers import telemetry_worker as tw
    w = tw.TelemetryWorker()
    seen = {"ticks": [], "qc": [], "finished": [], "started": []}

    def fake_get(url, timeout=None):
        m = mock.Mock(ok=True)
        m.json.return_value = seen["payload"]
        return m

    patches = [
        mock.patch.object(w._session, "get", side_effect=fake_get),
        mock.patch.object(tw._moonraker, "get_printer_info", return_value={
            "moonraker_online": True, "state": "ready", "klippy_connected": True, "state_message": ""}),
        mock.patch.object(tw.TelemetryWorker, "_discover_temp_sensors", return_value=[]),
        mock.patch.object(tw.command_pipeline, "tick", side_effect=lambda snap, src="live": seen["ticks"].append(dict(snap))),
        mock.patch.object(tw.command_pipeline, "run_quality_cycle", return_value=[]),
        mock.patch.object(tw.quality_controller, "update", side_effect=lambda snap, *a: seen["qc"].append(snap["print_state"]) or []),
        mock.patch.object(tw.timelapse_job, "finish", side_effect=lambda st, history_id=None: seen["finished"].append(st)),
        mock.patch.object(tw.timelapse_job, "start", side_effect=lambda fn: seen["started"].append(fn)),
        mock.patch.object(tw, "get_timelapse_cfg", return_value={"enabled": True}),
        mock.patch.object(tw, "notify"),
        mock.patch.object(tw, "execute_alert_action"),
        mock.patch.object(tw, "log_snapshot"),
        mock.patch.object(tw, "get_connection"),
        mock.patch.object(tw, "get_spool_price_per_g", return_value=0.0),
        mock.patch.object(tw.TelemetryWorker, "_apply_led_state"),
        mock.patch.object(tw.TelemetryWorker, "_flush_maintenance"),
        mock.patch("services.qa_reporter.trigger_qa_report"),
    ]
    for p in patches:
        p.start()
    seen["tw"] = tw
    yield w, seen
    for p in patches:
        p.stop()


def step(w, seen, state, name, duration):
    seen["payload"] = _moonraker_payload(state, name, duration)
    seen["ticks"].clear()
    w._tick()
    return [t["print_state"] for t in seen["ticks"]]


def test_worker_back_to_back_jobs_get_an_end_then_a_start(worker):
    w, seen = worker
    assert step(w, seen, "printing", "a.gcode", 100) == ["printing"]
    assert seen["started"] == ["a.gcode"]
    assert step(w, seen, "printing", "a.gcode", 101) == ["printing"]
    # the queue hands over inside one poll interval: plugins get a "complete" tick, then the new job's printing tick
    assert step(w, seen, "printing", "b.gcode", 1) == ["complete", "printing"]
    assert seen["finished"] == ["complete"]                 # old job's timelapse closed ...
    assert seen["started"] == ["a.gcode", "b.gcode"]        # ... new one opened, for the right file
    assert "complete" in seen["qc"]                         # controller's commanded values were reset
    assert step(w, seen, "printing", "b.gcode", 2) == ["printing"]
    assert seen["finished"] == ["complete"]


def test_worker_same_file_queued_twice(worker):
    w, seen = worker
    step(w, seen, "printing", "a.gcode", 3000)
    assert step(w, seen, "printing", "a.gcode", 0) == ["complete", "printing"]
    assert seen["started"] == ["a.gcode", "a.gcode"] and seen["finished"] == ["complete"]


def test_worker_normal_lifecycle_unchanged(worker):
    w, seen = worker
    step(w, seen, "printing", "a.gcode", 100)
    assert step(w, seen, "complete", "a.gcode", 100) == ["complete"]
    assert seen["finished"] == ["complete"]
    assert step(w, seen, "printing", "b.gcode", 1) == ["printing"]
    assert seen["started"] == ["a.gcode", "b.gcode"] and seen["finished"] == ["complete"]


def test_worker_history_row_names_the_job_that_ended(worker):
    w, seen = worker
    step(w, seen, "printing", "a.gcode", 100)
    seen["tw"].get_connection.reset_mock()
    step(w, seen, "printing", "b.gcode", 1)
    cur = seen["tw"].get_connection.return_value.cursor.return_value
    inserts = [c for c in cur.execute.call_args_list if "INSERT INTO print_history" in c[0][0]]
    assert len(inserts) == 1 and inserts[0][0][1][0] == "a.gcode" and inserts[0][0][1][1] == "complete"
