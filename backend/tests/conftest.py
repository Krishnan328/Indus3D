import atexit
import os
import shutil
import sys
import tempfile

import pytest

# Add backend directory to sys.path so we can import from core, digital_twin, etc.
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# The config-backup service must never write into the source tree or a real printer's config:
# the whole test session gets a throw-away Klipper config directory.
_TEST_CONFIG_DIR = tempfile.mkdtemp(prefix="indus3d_test_klipper_cfg_")
os.environ["KLIPPER_CONFIG_DIR"] = _TEST_CONFIG_DIR
atexit.register(shutil.rmtree, _TEST_CONFIG_DIR, ignore_errors=True)

from db.models import init_db
init_db()


@pytest.fixture(autouse=True)
def _fresh_config_backup_manager():
    from services import config_backup
    config_backup.reset_manager()
    yield
    config_backup.reset_manager()


def pytest_sessionfinish(session, exitstatus):
    stray = os.path.join(backend_dir, "config", ".git")
    if os.path.exists(stray):
        session.exitstatus = 1
        print(f"\nERROR: the test run created {stray} (config backup leaked into the source tree)")
