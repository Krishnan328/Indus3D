"""Static packaging contracts; these do not replace a container build/recreation test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_persistent_paths_are_inside_the_mounted_volume():
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    for setting in (
        "DB_PATH=/app/data/db/flight_record.db",
        "INDUS3D_CONFIG_PATH=/app/data/config/indus_overrides.cfg",
        "FLASK_SECRET_KEY_PATH=/app/data/.flask_secret_key",
        "TIMELAPSE_DIR=/app/data/timelapse",
    ):
        assert setting in dockerfile
    assert "indus3d_data:/app/data" in compose
    assert "/api/v1/health" in dockerfile
    assert "/api/v1/twin/state" not in dockerfile


def test_container_build_excludes_local_credentials_and_runtime_data():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    for pattern in ("**/.env", "**/.flask_secret_key", "**/*.db", "**/node_modules", "**/.venv*"):
        assert pattern in ignore
