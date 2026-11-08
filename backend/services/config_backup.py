"""
services/config_backup.py
-------------------------
Automated Git Configuration Backup for Klipper & Moonraker configs.
Monitors config directory, tracks revisions, provides history, diffs,
and one-click rollbacks.
"""

import os
import subprocess
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("indus3d.config_backup")


def get_config_dir() -> str:
    """Detects the active Klipper/Moonraker config directory."""
    env_dir = os.getenv("KLIPPER_CONFIG_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    candidates = [
        "/var/lib/moonraker/config",
        os.path.expanduser("~/printer_data/config"),
        os.path.expanduser("~/klipper_config"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c

    # Fallback to current workspace config if running in test/mock environment
    local_cfg = Path(__file__).parent.parent / "config"
    return str(local_cfg)


class ConfigBackupManager:
    """Manages git-based versioning and backups for Klipper configuration files."""

    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = config_dir or get_config_dir()
        self._ensure_git_repo()

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        """Runs a git command inside the config directory."""
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=self.config_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            logger.error(f"Git command failed: {args} - {e}")
            return -1, "", str(e)

    def _ensure_git_repo(self):
        """Initializes git repository if not already present."""
        if not os.path.isdir(self.config_dir):
            return

        git_dir = os.path.join(self.config_dir, ".git")
        if not os.path.exists(git_dir):
            logger.info(f"Initializing git repository in {self.config_dir}")
            self._run_git(["init"])
            # Create standard .gitignore
            gitignore_path = os.path.join(self.config_dir, ".gitignore")
            if not os.path.exists(gitignore_path):
                try:
                    with open(gitignore_path, "w") as f:
                        f.write("*.log\n*.bak\n*.bkp\n*.gcode\n.moonraker*.bkp\n.gcode_move*\n")
                except Exception as e:
                    logger.warning(f"Could not write .gitignore: {e}")

        # Ensure committer identity is configured locally
        self._run_git(["config", "user.name", "Indus3D Auto-Backup"])
        self._run_git(["config", "user.email", "indus3d@localhost"])

    def has_changes(self) -> bool:
        """Checks if there are modified or untracked .cfg/.conf files."""
        code, out, _ = self._run_git(["status", "--porcelain"])
        if code != 0:
            return False
        # Filter for config files
        for line in out.splitlines():
            line = line.strip()
            if any(line.endswith(ext) for ext in [".cfg", ".conf", ".json"]):
                return True
        return False

    def auto_backup(self, reason: str = "Automated configuration backup") -> Dict:
        """
        Stages and commits config changes if detected.
        Returns outcome dict.
        """
        if not os.path.isdir(self.config_dir):
            return {"status": "skipped", "message": "Config directory does not exist"}

        # Stage config files (walk directory to find actual files matching extensions)
        add_files = []
        for root, _, files in os.walk(self.config_dir):
            if ".git" in root:
                continue
            for f in files:
                if any(f.endswith(ext) for ext in [".cfg", ".conf", ".json", ".gitignore"]):
                    rel_path = os.path.relpath(os.path.join(root, f), self.config_dir)
                    add_files.append(rel_path)

        if not add_files:
            return {"status": "unchanged", "message": "No configuration files found to track"}

        self._run_git(["add", "--"] + add_files)

        # Check if anything is staged
        code, _, _ = self._run_git(["diff", "--cached", "--quiet"])
        if code == 0:
            return {"status": "unchanged", "message": "No configuration changes to commit"}

        # Get summary of staged files
        _, staged_files, _ = self._run_git(["diff", "--cached", "--name-only"])
        file_list = [f for f in staged_files.splitlines() if f]

        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"{reason} [{ts_str}]\n\nModified: {', '.join(file_list)}"

        code, out, err = self._run_git(["commit", "-m", commit_msg])
        if code != 0:
            logger.error(f"Commit failed: {err}")
            return {"status": "error", "error": err}

        # Get new commit hash
        _, commit_hash, _ = self._run_git(["rev-parse", "HEAD"])
        logger.info(f"💾 Klipper config auto-backup created: {commit_hash[:8]} ({reason})")

        return {
            "status": "committed",
            "commit": commit_hash,
            "short_commit": commit_hash[:8],
            "files": file_list,
            "message": commit_msg,
            "timestamp": time.time(),
        }

    def get_history(self, limit: int = 25) -> List[Dict]:
        """Returns commit history for configuration files."""
        code, out, _ = self._run_git([
            "log",
            f"-n{limit}",
            "--pretty=format:%H|%an|%at|%s",
        ])
        if code != 0 or not out:
            return []

        history = []
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commit_hash, author, ts_str, subject = parts
                try:
                    ts = float(ts_str)
                    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    ts = 0.0
                    dt_str = ""

                history.append({
                    "commit": commit_hash,
                    "short_commit": commit_hash[:8],
                    "author": author,
                    "timestamp": ts,
                    "date": dt_str,
                    "message": subject,
                })
        return history

    def get_diff(self, commit_hash: str) -> Dict:
        """Returns the diff of a specific commit or between commit and HEAD."""
        # Sanitize commit hash to alphanumeric
        safe_hash = "".join(c for c in commit_hash if c.isalnum() or c in ("^", "~"))
        code, diff_text, err = self._run_git(["show", "--stat", "--patch", safe_hash])
        if code != 0:
            return {"error": err or "Failed to load diff"}
        return {"commit": safe_hash, "diff": diff_text}

    def restore_commit(self, commit_hash: str) -> Dict:
        """Restores config files to a previous commit, creating a restore commit."""
        safe_hash = "".join(c for c in commit_hash if c.isalnum() or c in ("^", "~"))

        # Safety auto-backup first if any uncommitted changes exist
        if self.has_changes():
            self.auto_backup(reason="Pre-rollback safety backup")

        code, _, err = self._run_git(["checkout", safe_hash, "--", "."])
        if code != 0:
            return {"status": "error", "error": f"Failed to checkout {safe_hash}: {err}"}

        # Commit restoration
        res = self.auto_backup(reason=f"Restored configuration from commit {safe_hash[:8]}")
        return res


# Global singleton instance
config_backup_mgr = ConfigBackupManager()
