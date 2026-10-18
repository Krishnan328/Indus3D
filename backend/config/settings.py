"""
config/settings.py
-------------------
Single source of truth for all runtime configuration.
Reads from environment variables, which are loaded from .env if present.

Usage anywhere in the backend:
    from config.settings import settings
    url = f"http://{settings.MOONRAKER_HOST}:{settings.MOONRAKER_PORT}"
"""

import os
from pathlib import Path

# Load .env file from backend/ directory if it exists
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass   # python-dotenv not installed — fall back to environment only


class _Settings:

    # ── Moonraker / Klipper ───────────────────────────────────────────────────
    MOONRAKER_HOST: str  = os.getenv("MOONRAKER_HOST", "127.0.0.1")
    MOONRAKER_PORT: int  = int(os.getenv("MOONRAKER_PORT", "7125"))

    # ── Webcam ────────────────────────────────────────────────────────────────
    # Set to the full stream URL if non-standard, otherwise auto-built
    WEBCAM_STREAM_URL: str = os.getenv(
        "WEBCAM_STREAM_URL",
        ""   # if empty, built as http://MOONRAKER_HOST/webcam/?action=stream
    )

    # ── Flask API ─────────────────────────────────────────────────────────────
    FLASK_HOST: str  = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT: int  = int(os.getenv("FLASK_PORT", "5001"))
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, or * for development
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # ── Database ──────────────────────────────────────────────────────────────
    DB_PATH: str = os.getenv(
        "DB_PATH",
        str(Path(__file__).parent.parent / "db" / "flight_record.db")
    )

    # ── Timelapse ─────────────────────────────────────────────────────────────
    # Behavior (enabled/mode/interval/fps) lives in indus_overrides.cfg like
    # other behavior settings — this is just the storage path, a deployment
    # concern like DB_PATH above.
    TIMELAPSE_DIR: str = os.getenv(
        "TIMELAPSE_DIR",
        str(Path(__file__).parent.parent / "data" / "timelapse")
    )

    # ── Simulation ────────────────────────────────────────────────────────────
    SIM_MODE:   bool = os.getenv("SIM_MODE",   "false").lower() == "true"
    SIM_SHAPE:  str  = os.getenv("SIM_SHAPE",  "benchy")
    SIM_LAYERS: int  = int(os.getenv("SIM_LAYERS", "30"))

    # ── Telemetry tick rate ───────────────────────────────────────────────────
    # Was a hardcoded POLL_HZ=10 constant in telemetry_worker.py. Every tick
    # does a Moonraker poll + 3 digital twin model updates + a WebSocket push
    # + (now-batched) SQLite logging — on a 1GB Pi or Creality mainboard,
    # lower this rather than inheriting whatever a Pi 5 comfortably handles.
    # The roadmap's planned 50Hz WebSocket-subscription upgrade should target
    # this setting too, not replace it with a new hardcoded value.
    TWIN_TICK_HZ: float = float(os.getenv("TWIN_TICK_HZ", "10"))

    # NOTE: input shaper baseline (Y resonance Hz, bed mass, shaper type) is
    # NOT read from here despite an earlier version of this file suggesting
    # otherwise. quality_controller.py reads y_resonance_hz/bed_mass_g/
    # y_shaper_type directly from indus_overrides.cfg's [indus3d] section —
    # confirmed via grep that nothing anywhere read the old
    # Y_RESONANCE_HZ/BED_MASS_G/Y_SHAPER_TYPE fields that used to live here,
    # so they were removed rather than left as dead, misleading config. See
    # core/shaper_tuner.py for the (semi-)automated way to set these now.

    # ── Filament ──────────────────────────────────────────────────────────────
    DEFAULT_FILAMENT: str = os.getenv("DEFAULT_FILAMENT", "PLA")

    # ── Notifications (all optional — configure any, all, or none) ────────────
    # Discord: Server Settings → Integrations → Webhooks → New Webhook → copy URL
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    # Telegram: message @BotFather to create a bot and get a token, then
    # message your bot once and check https://api.telegram.org/bot<TOKEN>/getUpdates
    # for your chat_id
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID:   str = os.getenv("TELEGRAM_CHAT_ID",   "")
    # Critical alerts (thermal runaway) always notify if a channel is
    # configured. Warn-level alerts (lag, under/over-extrusion) are opt-in —
    # off by default so a well-tuned printer doesn't spam your phone.
    NOTIFY_ON_WARN: bool = os.getenv("NOTIFY_ON_WARN", "false").lower() == "true"

    # ── Alert thresholds (overrides profile values if set) ────────────────────
    LAG_WARN_MM:         float = float(os.getenv("LAG_WARN_MM",         "0"))
    STRESS_WARN:         float = float(os.getenv("STRESS_WARN",         "0"))
    EXT_HEAT_CYCLES_WARN: int  = int(os.getenv("EXT_HEAT_CYCLES_WARN", "0"))
    BED_HEAT_CYCLES_WARN: int  = int(os.getenv("BED_HEAT_CYCLES_WARN", "0"))

    # ── PZEM-004T Power Monitor ───────────────────────────────────────────────
    # USB-serial device path for the PZEM-004T via FTDI adapter (Modbus RTU
    # over RS485). Use the by-id path for stability across reboots:
    #   ls /dev/serial/by-id/
    # Set to empty string to disable (power card shows "not connected").
    PZEM_SERIAL_PORT: str = os.getenv("PZEM_SERIAL_PORT", "")
    PZEM_SERIAL_BAUD: int = int(os.getenv("PZEM_SERIAL_BAUD", "9600"))
    PZEM_MODBUS_ADDR: int = int(os.getenv("PZEM_MODBUS_ADDR", "1"))

    # ── Authentication ────────────────────────────────────────────────────────
    # Single shared password. When set, all API routes require authentication
    # (session cookie or Bearer token). When empty, auth is disabled entirely
    # — zero friction for local/dev use, preserves current behavior.
    INDUS3D_PASSWORD: str = os.getenv("INDUS3D_PASSWORD", "")
    # Persistent secret key for Flask sessions. If not set, one is generated
    # and saved to backend/.flask_secret_key on first run.
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "")

    # ── Disk Space Monitoring ───────────────────────────────────────────────
    # Free-space thresholds for the partition holding the Indus3D data
    # directory. When free space drops below these, the frontend shows
    # a warning or critical alert. Defaults are conservative for a
    # typical Raspberry Pi SD card.
    DISK_WARN_GB: float = float(os.getenv("DISK_WARN_GB", "2.0"))
    DISK_CRITICAL_GB: float = float(os.getenv("DISK_CRITICAL_GB", "0.5"))
    DISK_CHECK_PATH: str = os.getenv("DISK_CHECK_PATH", "")  # empty = backend dir
    DISK_CHECK_INTERVAL_S: float = float(os.getenv("DISK_CHECK_INTERVAL_S", "60"))

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def moonraker_url(self) -> str:
        return f"http://{self.MOONRAKER_HOST}:{self.MOONRAKER_PORT}"

    @property
    def webcam_stream_url(self) -> str:
        if self.WEBCAM_STREAM_URL:
            return self.WEBCAM_STREAM_URL
        # Default: Mainsail's standard webcam path on the same host
        return f"http://{self.MOONRAKER_HOST}/webcam/?action=stream"


settings = _Settings()
