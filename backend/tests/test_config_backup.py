"""
tests/test_config_backup.py
---------------------------
Unit tests for the automated git configuration backup service.
"""

import os
import shutil
import tempfile
import pytest
from services.config_backup import ConfigBackupManager


@pytest.fixture
def temp_config_dir():
    d = tempfile.mkdtemp(prefix="indus3d_cfg_test_")
    # Create sample config files
    with open(os.path.join(d, "printer.cfg"), "w") as f:
        f.write("[printer]\nkinematics: cartesian\n")
    with open(os.path.join(d, "moonraker.conf"), "w") as f:
        f.write("[server]\nport: 7125\n")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_git_init_and_backup(temp_config_dir):
    mgr = ConfigBackupManager(config_dir=temp_config_dir)
    assert os.path.exists(os.path.join(temp_config_dir, ".git"))

    # Initial backup
    res = mgr.auto_backup(reason="Initial test backup")
    assert res["status"] == "committed"
    assert "printer.cfg" in res["files"] or "moonraker.conf" in res["files"]

    # No changes backup
    res2 = mgr.auto_backup(reason="Should skip")
    assert res2["status"] == "unchanged"

    # Modify file
    with open(os.path.join(temp_config_dir, "printer.cfg"), "a") as f:
        f.write("max_velocity: 300\n")

    assert mgr.has_changes() is True
    res3 = mgr.auto_backup(reason="Modified max_velocity")
    assert res3["status"] == "committed"

    # History
    history = mgr.get_history()
    assert len(history) >= 2
    assert "Modified max_velocity" in history[0]["message"]

    # Diff
    diff_data = mgr.get_diff(history[0]["commit"])
    assert "diff" in diff_data
    assert "max_velocity" in diff_data["diff"]

    # Restore to initial commit
    restore_res = mgr.restore_commit(history[1]["commit"])
    assert restore_res["status"] == "committed"
    with open(os.path.join(temp_config_dir, "printer.cfg"), "r") as f:
        restored_content = f.read()
    assert "max_velocity" not in restored_content
