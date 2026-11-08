"""Timelapse stitch -> print_history link -> QA report ordering, and the no-timelapse / failure paths."""
import os
import sqlite3
import subprocess
from unittest import mock

import pytest

from core import timelapse as tl


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE print_history (id INTEGER PRIMARY KEY, timelapse_id TEXT, timelapse_path TEXT, timelapse_hash TEXT)")
    c.execute("INSERT INTO print_history (id) VALUES (7)")
    c.commit()
    c.close()
    monkeypatch.setattr("db.models.get_connection", lambda: sqlite3.connect(db))
    monkeypatch.setattr(tl.settings, "TIMELAPSE_DIR", str(tmp_path / "tl"), raising=False)
    monkeypatch.setattr(tl, "get_timelapse_cfg", lambda: {"enabled": True, "fps": 15, "mode": "interval", "interval_s": 0})

    def row():
        c = sqlite3.connect(db)
        try:
            return c.execute("SELECT timelapse_id, timelapse_path, timelapse_hash FROM print_history WHERE id=7").fetchone()
        finally:
            c.close()
    return row, tmp_path


def _job_with_frames(n):
    job = tl.TimelapseJob()
    job.start("My Part.gcode", history_id=7)
    for i in range(n):
        with open(os.path.join(job.job_dir, f"frame_{i:06d}.jpg"), "wb") as f:
            f.write(b"\xff\xd8jpeg" + bytes([i]))
    job.frame_count = n
    return job


def _fake_ffmpeg(returncode=0):
    def run(cmd, **kw):
        if returncode == 0:
            with open(cmd[-1], "wb") as f:
                f.write(b"video-bytes" * 1000)
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="boom")
    return run


def _wait(ev):
    assert ev.wait(10), "on_done never called"


def test_report_runs_after_the_db_link_and_sees_the_timelapse_columns(env):
    import threading
    row, _ = env
    job = _job_with_frames(4)
    done, seen = threading.Event(), {}

    def on_done():
        seen["row"] = row()
        done.set()
    with mock.patch.object(tl.subprocess, "run", side_effect=_fake_ffmpeg()):
        assert job.finish("complete", history_id=7, on_done=on_done) is True
        _wait(done)
    tid, path, h = seen["row"]
    assert tid and path.endswith("timelapse.mp4") and len(h) == 64
    assert h == tl._sha256_file(path)


def test_sha256_is_chunked(tmp_path):
    import hashlib
    p = tmp_path / "v.bin"
    data = os.urandom(3 * 1024 * 1024 + 17)
    p.write_bytes(data)
    reads = []
    real_open = open

    class Spy:
        def __init__(self, f):
            self.f = f

        def read(self, n=-1):
            reads.append(n)
            return self.f.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()
    with mock.patch("builtins.open", lambda *a, **k: Spy(real_open(*a, **k))):
        assert tl._sha256_file(str(p)) == hashlib.sha256(data).hexdigest()
    assert reads and all(r == 1024 * 1024 for r in reads)


def test_no_timelapse_path_returns_false_and_does_not_call_back(env):
    job = tl.TimelapseJob()
    called = []
    assert job.finish("complete", history_id=7, on_done=lambda: called.append(1)) is False    # inactive
    job = _job_with_frames(1)                                                                  # < 2 frames
    assert job.finish("complete", history_id=7, on_done=lambda: called.append(1)) is False
    assert called == []


@pytest.mark.parametrize("failure", ["ffmpeg_missing", "ffmpeg_error", "timeout"])
def test_failed_stitch_still_runs_the_report_without_a_link(env, failure):
    import threading
    row, _ = env
    job = _job_with_frames(4)
    done, seen = threading.Event(), {}

    def on_done():
        seen["row"] = row()
        done.set()
    if failure == "ffmpeg_missing":
        runner = mock.Mock(side_effect=FileNotFoundError("ffmpeg"))
    elif failure == "timeout":
        runner = mock.Mock(side_effect=subprocess.TimeoutExpired("ffmpeg", 300))
    else:
        runner = _fake_ffmpeg(returncode=1)
    with mock.patch.object(tl.subprocess, "run", side_effect=runner):
        assert job.finish("complete", history_id=7, on_done=on_done) is True
        _wait(done)
    assert seen["row"] == (None, None, None)          # report would print "Timelapse: unavailable"


def test_a_raising_callback_does_not_break_the_stitch_thread(env):
    import threading
    job = _job_with_frames(3)
    after = threading.Event()
    with mock.patch.object(tl.subprocess, "run", side_effect=_fake_ffmpeg()):
        tl._stitch(job.job_dir, 15, "complete", 7, on_done=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert os.path.isfile(os.path.join(job.job_dir, "timelapse.mp4"))
    after.set()


def test_incident_clip_and_keyframes_unchanged(env):
    job = _job_with_frames(12)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return _fake_ffmpeg()(cmd, **kw)
    with mock.patch.object(tl.subprocess, "run", side_effect=run):
        tl._stitch(job.job_dir, 1, "error", 7)
    assert os.path.isfile(os.path.join(job.job_dir, "keyframe_first.jpg"))
    assert os.path.isfile(os.path.join(job.job_dir, "keyframe_last.jpg"))
    assert any(c[-1].endswith("incident.mp4") for c in calls) and any(c[-1].endswith("timelapse.mp4") for c in calls)


# ── _finish_job wiring ───────────────────────────────────────────────────────
def _finish(chained, run_callback=False):
    from workers import telemetry_worker as tw
    w = tw.TelemetryWorker()
    w._print_start_time = 1000.0
    w._print_start_fil_m = 0.0
    w._last_fil_m = 0.0
    w._print_start_wh = 0.0
    w._job_filename = "a.gcode"
    cb = {}

    def fake_finish(status, history_id=None, on_done=None):
        cb["on_done"] = on_done
        return chained
    qa = mock.Mock()
    with mock.patch.object(tw.timelapse_job, "finish", side_effect=fake_finish), \
         mock.patch.object(tw, "get_connection") as gc, \
         mock.patch.object(tw, "_energy_wh", return_value=0.0), \
         mock.patch.object(tw, "get_spool_price_per_g", return_value=0.0), \
         mock.patch("services.qa_reporter.trigger_qa_report", qa), \
         mock.patch("core.notifications.notify_print_completed") as npc:
        gc.return_value.cursor.return_value.lastrowid = 7
        w._finish_job({"filename": "a.gcode"}, {}, "complete", False)
        w._print_start_time = 9999.0              # the next job starts before the stitch ends
        if run_callback:
            qa.assert_not_called()
            cb["on_done"]()
    return qa, cb, npc


def test_finish_job_defers_the_report_to_the_stitch_thread():
    qa, cb, npc = _finish(chained=True, run_callback=True)
    qa.assert_called_once()
    assert qa.call_args[0][0] == 7 and qa.call_args[0][1] == 1000.0          # start time of the ended job
    assert "excursions" in npc.call_args[1]


def test_finish_job_starts_the_report_immediately_without_a_timelapse():
    qa, cb, _ = _finish(chained=False)
    qa.assert_called_once()
