# Indus3D: Real-Time Digital Twin & Closed-Loop Quality Controller

Indus3D is a next-generation real-time digital twin and closed-loop quality control platform for Klipper and Moonraker 3D printers.

> **Release Phase 1**: Core Foundation, Unified Settings & Database Migrations

---

## 🌟 Architecture Overview (Phase 1)

This foundation release establishes the core repository infrastructure, unified settings management, database schema migrations, and deployment automation:

- **Unified Configuration**: Centralized settings via `backend/config/settings.py` parsing environment variables with robust defaults.
- **Database Migrations Engine**: Built-in lightweight SQLite migration engine (`backend/db/migrator.py`) with versioned migrations (`001_baseline.py` through `009_config_history.py`).
- **Telemetry & Print Flight Records**: Structured SQLite flight logging schemas in `backend/db/models.py`.
- **Rotating File Logging**: Thread-safe rotating logging in `backend/core/logger.py` writing to `logs/indus3d.log`.
- **Worker Management**: Multi-threaded worker coordinator in `backend/workers/manager.py`.
- **Pruned Legacy Code**: Removed deprecated command queue and asynchronous IPC modules in favor of direct Moonraker communication.

---

## 🚀 Quickstart & Installation

### Prerequisites
- Python 3.9 or higher
- Klipper & Moonraker (for physical printer connection)

### Automated Install (Raspberry Pi / Linux)
```bash
git clone https://github.com/Krishnan328/indus3d.git
cd indus3d
./install.sh
```

### Manual Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Applying Database Migrations
To initialize or upgrade the SQLite flight record database:
```bash
cd backend
python -m db.migrator
```

---

## ⚙️ Configuration

Copy `backend/.env.example` to `backend/.env`:
```ini
MOONRAKER_HOST=127.0.0.1
MOONRAKER_PORT=7125
FLASK_HOST=0.0.0.0
FLASK_PORT=5001
TWIN_TICK_HZ=10
```

### Klipper Integration
Include the Indus3D configuration overrides in your `printer.cfg`:
```ini
[include indus3d.cfg]
```

---

## 🧪 Testing

Run backend tests using pytest:
```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for details.
