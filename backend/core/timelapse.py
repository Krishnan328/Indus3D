"""
core/timelapse.py
-------------------
Captures webcam snapshots during a print and stitches them into an mp4 on
completion, via ffmpeg (must be installed on the host — apt install ffmpeg;
invoked only as a subprocess, never bundled). Two capture modes, configured
in indus_overrides.cfg:
  "interval" — snapshot every N seconds while printing. Works with any
               slicer, no gcode macros needed.
  "layer"    — snapshot whenever Z increases, using Indus3D's own live Z
               tracking. Also needs no slicer-side layer-change macros —
               most other timelapse tools require SET_PRINT_STATS_INFO or
               similar; this doesn't.

Snapshot source: Crowsnest's standard ?action=snapshot convention, derived
import logging
from settings.webcam_stream_url by swapping ?action=stream for
?action=snapshot — this is Mainsail/Crowsnest's documented URL scheme, not
guessed. Some camera-streamer configs don't support snapshots (a known
Crowsnest issue); a failed capture is logged and skipped, never allowed to
interrupt the print or the telemetry loop.
"""

import os
import re
import time
import glob
import shutil
import subprocess
import threading
import requests
from config.settings import settings
from config.loader import get_timelapse_cfg

_TIMEOUT = 5


def _snapshot_url() -> str:
    stream_url = settings.webcam_stream_url
    if "action=stream" in stream_url:
        return stream_url.replace("action=stream", "action=snapshot")
    return stream_url  # non-standard URL — best effort, try it as-is


class TimelapseJob:
    """One in-progress timelapse capture session, for the current print."""

    def __init__(self):
        self.active = False
        self.job_dir = None
        self.frame_count = 0
        self._last_capture_t = 0.0
        self._last_capture_z = None

    def start(self, filename: str):
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename or "print")
        job_id = f"{int(time.time())}_{safe_name}"
        self.job_dir = os.path.join(settings.TIMELAPSE_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.active = True
        self.frame_count = 0
        self._last_capture_t = 0.0
        self._last_capture_z = None
        logging.info(f"🎬 Timelapse started: {self.job_dir}")

    def maybe_capture(self, z: float):
        """Call every tick while printing — decides internally whether a
        snapshot is actually due, based on the configured mode."""
        if not self.active:
            return
        cfg = get_timelapse_cfg()
        mode = cfg.get("mode", "interval")
        if mode == "layer":
            due = self._last_capture_z is None or z > self._last_capture_z
        else:
            due = (time.time() - self._last_capture_t) >= cfg.get("interval_s", 10)
        if not due:
            return
        if self._capture_frame():
            self._last_capture_t = time.time()
            self._last_capture_z = z

    def _capture_frame(self) -> bool:
        try:
            res = requests.get(_snapshot_url(), timeout=_TIMEOUT)
            if not res.ok or not res.content:
                return False
            path = os.path.join(self.job_dir, f"frame_{self.frame_count:06d}.jpg")
            with open(path, "wb") as f:
                f.write(res.content)
            self.frame_count += 1
            return True
        except Exception as e:
            logging.info(f"🔴 Timelapse snapshot failed: {e}")
            return False

    def finish(self, status: str):
        """Call once on the transition out of 'printing'. Stitching runs in
        a background thread — never block the telemetry loop on ffmpeg."""
        if not self.active:
            return
        self.active = False
        if self.frame_count < 2:
            logging.info(f"🎬 Timelapse: only {self.frame_count} frame(s) captured, skipping video (print {status})")
            shutil.rmtree(self.job_dir, ignore_errors=True)
            return
        threading.Thread(
            target=_stitch, args=(self.job_dir, get_timelapse_cfg().get("fps", 15), status), daemon=True
        ).start()


def _stitch(job_dir: str, fps: int, status: str):
    out_path = os.path.join(job_dir, "timelapse.mp4")
    incident_path = os.path.join(job_dir, "incident.mp4")
    pattern  = os.path.join(job_dir, "frame_%06d.jpg")
    try:
        # If it's an error/halted, stitch the last 10 seconds into a separate incident clip first
        if status in ("error", "halted", "cancelled"):
            # find how many frames we have
            import glob
            frames = sorted(glob.glob(os.path.join(job_dir, "frame_*.jpg")))
            if len(frames) > fps * 10:
                start_frame = len(frames) - (fps * 10)
                # ffmpeg can start from a specific image sequence number using -start_number
                subprocess.run(
                    ["ffmpeg", "-y", "-start_number", str(start_frame), "-framerate", str(fps), "-i", pattern,
                     "-vframes", str(fps * 10), "-vcodec", "libx264", "-pix_fmt", "yuv420p", incident_path],
                    capture_output=True, timeout=60
                )

        # Stitch full timelapse
        result = subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern,
             "-vcodec", "libx264", "-pix_fmt", "yuv420p", out_path],
            capture_output=True, timeout=300, text=True,
        )
        if result.returncode != 0:
            logging.info(f"🔴 ffmpeg failed (timelapse {status}): {result.stderr[-500:]}")
            return
        # Frames are only useful for debugging a failed stitch — clean up
        # once the video exists, to save space on constrained storage.
        for f in glob.glob(os.path.join(job_dir, "frame_*.jpg")):
            os.remove(f)
        logging.info(f"🎬 Timelapse ready: {out_path}")
    except FileNotFoundError:
        logging.info(f"🔴 Timelapse: ffmpeg not found — install it (apt install ffmpeg). Frames kept in {job_dir}")
    except Exception as e:
        logging.info(f"🔴 Timelapse stitch failed: {e}")


current_job = TimelapseJob()


def list_timelapses() -> list:
    """Completed timelapses, newest first."""
    if not os.path.isdir(settings.TIMELAPSE_DIR):
        return []
    out = []
    for name in sorted(os.listdir(settings.TIMELAPSE_DIR), reverse=True):
        video = os.path.join(settings.TIMELAPSE_DIR, name, "timelapse.mp4")
        if os.path.isfile(video):
            out.append({
                "id": name,
                "size_bytes": os.path.getsize(video),
                "created": os.path.getmtime(video),
            })
    return out
