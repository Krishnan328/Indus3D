"""Shared helpers for plugins (not itself a plugin: the loader skips ``_*.py``)."""

import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

_BACKEND = Path(__file__).resolve().parent.parent


def data_dir(sub: str = "") -> Path:
    """Writable directory for plugin output (INDUS3D_PLUGIN_DATA, default /var/lib/indus3d/data/plugins or backend/data/plugins)."""
    env_dir = os.environ.get("INDUS3D_PLUGIN_DATA")
    if env_dir:
        root = Path(env_dir)
    elif Path("/var/lib/indus3d").exists():
        root = Path("/var/lib/indus3d/data/plugins")
    else:
        root = _BACKEND / "data" / "plugins"
    d = root / sub if sub else root
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = Path("/tmp/indus3d/data/plugins")
        d = root / sub if sub else root
        d.mkdir(parents=True, exist_ok=True)
    return d


def notify_safe(message: str) -> None:
    try:
        from core.notifications import notify
        notify(message)
    except Exception as e:  # noqa: BLE001
        logging.info(f"⚠️  notify failed: {e}")


def notify_critical_safe(alert_id: str, message: str) -> None:
    """A safety alert: the rich Discord/Telegram card with a webcam snapshot (non-blocking, queued), falling
    back to the plain notification if the rich path is unavailable."""
    try:
        from core.notifications import notify_critical_alert
        notify_critical_alert(alert_id, message)
    except Exception as e:  # noqa: BLE001
        logging.info(f"⚠️  critical notify failed ({e}); sending plain")
        notify_safe(message)


def http_json(url: str, timeout: float = 2.0, method: str = "GET", body: Any = None,
              headers: Optional[dict] = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj: Any) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Poller:
    """Background loop calling ``fn`` every ``interval`` s; start() is idempotent and
    exceptions never kill the loop."""

    def __init__(self, fn: Callable[[], None], interval: float, name: str):
        self.fn, self.interval, self.name = fn, interval, name
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True, name=self.name).start()

    def _loop(self) -> None:
        while True:
            try:
                self.fn()
            except Exception as e:  # noqa: BLE001
                logging.info(f"⚠️  poller {self.name}: {e}")
            time.sleep(self.interval)


def delayed(seconds: float, fn: Callable, *args) -> None:
    """Run ``fn`` once after ``seconds`` on a daemon timer (used when another
    component must finish writing first, e.g. the print_history row)."""
    t = threading.Timer(seconds, lambda: _safe(fn, *args))
    t.daemon = True
    t.start()


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001
        logging.error(f"delayed task failed: {e}")


def active_material() -> str:
    try:
        from db.models import get_connection
        conn = get_connection()
        try:
            row = conn.execute("SELECT value FROM printer_config WHERE key='virtual_spool_material'").fetchone()
        finally:
            conn.close()
        return (row[0] if row and row[0] else "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def latest_telemetry() -> dict:
    try:
        import workers
        w = workers._active_worker
        return dict(w.latest) if w and w.latest else {}
    except Exception:  # noqa: BLE001
        return {}
