"""
core/timelapse.py
-------------------
Captures webcam snapshots during a print and stitches them into an mp4 on
completion, via ffmpeg.
Provides cryptographic visual audit trails and ties timelapses directly
to AS9100 print history and QA reports.
"""

import os
import re
import time
import glob
import shutil
import hashlib
import subprocess
import threading
import logging
from typing import Optional, List, Dict
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
        self.job_id = None
        self.frame_count = 0
        self.history_id = None
        self._last_capture_t = 0.0
        self._last_capture_z = None

    def start(self, filename: str, history_id: Optional[int] = None):
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename or "print")
        self.job_id = f"{int(time.time())}_{safe_name}"
        self.job_dir = os.path.join(settings.TIMELAPSE_DIR, self.job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.active = True
        self.history_id = history_id
        self.frame_count = 0
        self._last_capture_t = 0.0
        self._last_capture_z = None
        logging.info(f"🎬 Timelapse started: {self.job_dir} (job_id={self.job_id})")

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

    def finish(self, status: str, history_id: Optional[int] = None):
        """Call once on the transition out of 'printing'. Stitching runs in
        a background thread — never block the telemetry loop on ffmpeg."""
        if not self.active:
            return
        self.active = False
        target_history_id = history_id or self.history_id

        if self.frame_count < 2:
            logging.info(f"🎬 Timelapse: only {self.frame_count} frame(s) captured, skipping video (print {status})")
            shutil.rmtree(self.job_dir, ignore_errors=True)
            return

        threading.Thread(
            target=_stitch,
            args=(self.job_dir, get_timelapse_cfg().get("fps", 15), status, target_history_id),
            daemon=True,
        ).start()


def _stitch(job_dir: str, fps: int, status: str, history_id: Optional[int] = None):
    out_path = os.path.join(job_dir, "timelapse.mp4")
    incident_path = os.path.join(job_dir, "incident.mp4")
    pattern = os.path.join(job_dir, "frame_%06d.jpg")
    job_id = os.path.basename(job_dir)

    try:
        frames = sorted(glob.glob(os.path.join(job_dir, "frame_*.jpg")))

        # Preserve keyframes for QA report thumbnail insertion
        if frames:
            try:
                shutil.copyfile(frames[0], os.path.join(job_dir, "keyframe_first.jpg"))
                shutil.copyfile(frames[-1], os.path.join(job_dir, "keyframe_last.jpg"))
                if len(frames) > 2:
                    mid_idx = len(frames) // 2
                    shutil.copyfile(frames[mid_idx], os.path.join(job_dir, "keyframe_mid.jpg"))
            except Exception as ke:
                logging.warning(f"Could not save keyframe thumbnails: {ke}")

        # If it's an error/halted, stitch the last 10 seconds into a separate incident clip first
        if status in ("error", "halted", "cancelled"):
            if len(frames) > fps * 10:
                start_frame = len(frames) - (fps * 10)
                subprocess.run(
                    ["ffmpeg", "-y", "-start_number", str(start_frame), "-framerate", str(fps), "-i", pattern,
                     "-vframes", str(fps * 10), "-vcodec", "libx264", "-pix_fmt", "yuv420p", incident_path],
                    capture_output=True, timeout=60,
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

        # Compute SHA-256 hash of video for tamper-proof QA compliance
        video_hash = ""
        try:
            with open(out_path, "rb") as vf:
                video_hash = hashlib.sha256(vf.read()).hexdigest()
        except Exception as he:
            logging.warning(f"Failed to hash timelapse video: {he}")

        # Clean up individual frame files to save space, keeping keyframes and mp4
        for f in frames:
            try:
                os.remove(f)
            except OSError:
                pass

        logging.info(f"🎬 Timelapse ready: {out_path} (SHA-256: {video_hash[:12]}...)")

        # Update database with timelapse link
        if history_id:
            try:
                from db.models import get_connection
                conn = get_connection()
                conn.execute(
                    "UPDATE print_history SET timelapse_id = ?, timelapse_path = ?, timelapse_hash = ? WHERE id = ?",
                    (job_id, out_path, video_hash, history_id),
                )
                conn.commit()
                conn.close()
                logging.info(f"Attached timelapse {job_id} to print history job {history_id}")
            except Exception as dbe:
                logging.error(f"Failed to link timelapse to print history: {dbe}")

    except FileNotFoundError:
        logging.info(f"🔴 Timelapse: ffmpeg not found — install it (apt install ffmpeg). Frames kept in {job_dir}")
    except Exception as e:
        logging.info(f"🔴 Timelapse stitch failed: {e}")


current_job = TimelapseJob()


def list_timelapses() -> List[Dict]:
    """Completed timelapses, newest first."""
    if not os.path.isdir(settings.TIMELAPSE_DIR):
        return []
    out = []
    for name in sorted(os.listdir(settings.TIMELAPSE_DIR), reverse=True):
        video = os.path.join(settings.TIMELAPSE_DIR, name, "timelapse.mp4")
        if os.path.isfile(video):
            has_incident = os.path.isfile(os.path.join(settings.TIMELAPSE_DIR, name, "incident.mp4"))
            out.append({
                "id": name,
                "size_bytes": os.path.getsize(video),
                "created": os.path.getmtime(video),
                "has_incident_clip": has_incident,
            })
    return out
