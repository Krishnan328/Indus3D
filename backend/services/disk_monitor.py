"""
services/disk_monitor.py
--------------------------
Monitors disk space on the partition that holds the Indus3D data directory.
Designed for Raspberry Pi with SD card or USB storage — these fill up fast
with timelapse frames, SQLite snapshots, and G-code files.

Checked every 60 seconds (configurable), not every telemetry tick — disk
usage doesn't change at 10Hz. Follows the same error-handling pattern as
moonraker_client.py and pzem_monitor.py: never raises, returns safe defaults.

The result dict is added to telemetry_worker.latest so the frontend can
display it and derive alerts (low disk space is a "warn" alert condition).
"""

import logging
import os
import shutil
import time
from config.settings import settings

# ── Safe default ──────────────────────────────────────────────────────────────
_UNKNOWN = {
    "total_gb":     None,
    "used_gb":      None,
    "free_gb":      None,
    "usage_pct":    None,
    "warn":         False,
    "critical":     False,
}


class DiskMonitor:
    """Polls disk usage at a configurable interval. Call check() from the
    telemetry tick — it returns a cached result until the next poll is due."""

    def __init__(self):
        self._check_path = settings.DISK_CHECK_PATH or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        self._warn_gb = settings.DISK_WARN_GB
        self._critical_gb = settings.DISK_CRITICAL_GB
        self._interval = settings.DISK_CHECK_INTERVAL_S
        self._last_check = 0.0
        self._cached = _UNKNOWN.copy()

    def check(self) -> dict:
        """Return current disk usage. Cached between polls (default 60s).
        Never raises."""
        now = time.time()
        if now - self._last_check < self._interval:
            return self._cached

        self._last_check = now
        try:
            usage = shutil.disk_usage(self._check_path)
            total_gb = round(usage.total / (1024 ** 3), 1)
            used_gb  = round(usage.used  / (1024 ** 3), 1)
            free_gb  = round(usage.free  / (1024 ** 3), 1)
            usage_pct = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0

            self._cached = {
                "total_gb":  total_gb,
                "used_gb":   used_gb,
                "free_gb":   free_gb,
                "usage_pct": usage_pct,
                "warn":      free_gb < self._warn_gb,
                "critical":  free_gb < self._critical_gb,
            }
        except Exception as e:
            logging.info(f"💾 Disk monitor: {e}")
            self._cached = _UNKNOWN.copy()

        return self._cached


# Module-level singleton
disk_monitor = DiskMonitor()
