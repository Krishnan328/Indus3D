# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0-phase1] - Repository Foundation, Unified Settings & DB Migrations

### Added
- Production `.gitignore` ignoring virtual environments, build artifacts, node_modules, and SQLite databases.
- Centralized configuration system in `backend/config/settings.py`.
- Versioned SQLite database migration framework in `backend/db/migrator.py` with migrations `001` through `009`.
- Flight logging and telemetry database models in `backend/db/models.py`.
- Rotating file logging handler (`backend/core/logger.py`) and worker lifecycle coordinator (`backend/workers/manager.py`).
- Automated installation scripts: `install.sh`, `uninstall.sh`, and `deploy_to_pi.sh`.
- Klipper configuration overrides template: `indus3d.cfg`.
- Pytest test runner configuration (`backend/pytest.ini`) and test fixtures (`backend/tests/conftest.py`).
- Developer guide in `docs/DEVELOPMENT.md`.

### Removed
- Legacy command queue subsystem (`backend/cmd_queue/`).
- Deprecated background queue worker (`backend/workers/queue_worker.py`).
