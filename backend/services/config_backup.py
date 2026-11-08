"""
services/config_backup.py
-------------------------
Git-based backup of the Klipper/Moonraker configuration directory: history, diffs, rollback.

Safety properties
* Nothing happens at import time. The manager is built lazily by ``get_manager()``; ``git init``
  only runs when a backup is actually requested.
* There is no fallback directory inside the Indus3D source tree. Without a Klipper config
  directory (``KLIPPER_CONFIG_DIR``, ``/var/lib/moonraker/config``, ``~/printer_data/config``,
  ``~/klipper_config``) the manager is *disabled* and every call answers ``status: "disabled"``.
* Secrets stay out of the history: files whose *name* looks secret-bearing, and files whose
  *content* contains token / password / api_key / secret assignments, MQTT credentials,
  Discord webhooks or Telegram bot tokens, are never staged (reported as ``skipped_secrets``).
* ``.json`` files (mostly Moonraker/Mainsail UI state) are opt-in: ``INDUS3D_CONFIG_BACKUP_JSON=1``.
* Restore accepts only a full or abbreviated hex hash that exists in this repository's history,
  takes a safety snapshot first, only rewrites files that exist in that commit and never deletes.
"""

import fnmatch
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("indus3d.config_backup")

_SECRET_NAME_GLOBS = [
    "*telegram*", "*bot_token*", "*bot-token*", "*secret*", "*password*", "*passwd*", "*.env", ".env*",
    "*token*", "*credentials*", "*.pem", "*.key",
]
_MAX_FILE_BYTES = 2 * 1024 * 1024
_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")

_SECRET_ASSIGN_RE = re.compile(
    r"""(?ix)
    ["']?[\w.\-]*(?:token|password|passwd|api[_\-]?key|secret)[\w.\-]*["']?   # key
    \s*[:=]\s*
    ["']?[^\s"',#;]+                                                          # a non-empty value
    """
)
_URL_CREDS_RE = re.compile(r"[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@", re.I)
_DISCORD_RE = re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w\-]+", re.I)
_TELEGRAM_RE = re.compile(r"\b\d{8,11}:[A-Za-z0-9_\-]{30,}\b")
_MQTT_USER_RE = re.compile(r"""(?ix)^\s*["']?(?:username|user)["']?\s*[:=]\s*["']?[^\s"']+""")

DEFAULT_GITIGNORE = (
    "*.log\n*.bak\n*.bkp\n*.gcode\n.moonraker*.bkp\n.gcode_move*\n"
    "# secrets: never back these up\n"
    + "".join(f"{g}\n" for g in _SECRET_NAME_GLOBS)
    + ".indus3d-restore-backup/\n"
)


def get_config_dir() -> Optional[str]:
    """The active Klipper/Moonraker config directory, or None when there is none."""
    env_dir = os.getenv("KLIPPER_CONFIG_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    for c in ("/var/lib/moonraker/config", os.path.expanduser("~/printer_data/config"),
              os.path.expanduser("~/klipper_config")):
        if os.path.isdir(c):
            return c
    return None


def _extensions() -> Tuple[str, ...]:
    exts = [".cfg", ".conf"]
    if os.getenv("INDUS3D_CONFIG_BACKUP_JSON", "0") == "1":
        exts.append(".json")
    return tuple(exts)


def is_secret_name(filename: str) -> bool:
    low = os.path.basename(filename).lower()
    return any(fnmatch.fnmatch(low, g) for g in _SECRET_NAME_GLOBS)


def has_secret_content(text: str) -> bool:
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        m = re.match(r"^\[([^\]]+)\]", stripped)
        if m:
            section = m.group(1).lower()
            continue
        if (_SECRET_ASSIGN_RE.search(line) or _URL_CREDS_RE.search(line) or _DISCORD_RE.search(line)
                or _TELEGRAM_RE.search(line)):
            return True
        if "mqtt" in section and _MQTT_USER_RE.match(line):
            return True
    return False


def _clean_text(value, default: str, limit: int = 200) -> str:
    if not isinstance(value, str):
        return default
    return _CTRL_RE.sub(" ", value).strip()[:limit].strip() or default


class ConfigBackupManager:
    """Git-based versioning for the Klipper configuration. Construction does no I/O."""

    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = config_dir
        self._lock = threading.RLock()
        self._prepared = False

    # ── state ──────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(self.config_dir) and os.path.isdir(self.config_dir)

    def _disabled(self) -> Dict:
        return {"status": "disabled",
                "message": "No Klipper config directory found (set KLIPPER_CONFIG_DIR); config backup is disabled"}

    def _has_repo(self) -> bool:
        return self.enabled and os.path.isdir(os.path.join(self.config_dir, ".git"))

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        try:
            res = subprocess.run(["git"] + args, cwd=self.config_dir, capture_output=True, text=True, timeout=10)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            logger.error(f"Git command failed: {args} - {e}")
            return -1, "", str(e)

    def _prepare(self) -> bool:
        """Create the repository on first real use. Returns False when git is unusable."""
        if self._prepared and self._has_repo():
            return True
        if not self.enabled:
            return False
        if not os.path.isdir(os.path.join(self.config_dir, ".git")):
            logger.info(f"Initializing git repository in {self.config_dir}")
            code, _, err = self._run_git(["init"])
            if code != 0:
                logger.warning(f"git init failed: {err}")
                return False
            gitignore = os.path.join(self.config_dir, ".gitignore")
            if not os.path.exists(gitignore):
                try:
                    with open(gitignore, "w") as f:
                        f.write(DEFAULT_GITIGNORE)
                except OSError as e:
                    logger.warning(f"Could not write .gitignore: {e}")
        self._run_git(["config", "user.name", "Indus3D Auto-Backup"])
        self._run_git(["config", "user.email", "indus3d@localhost"])
        self._prepared = True
        return True

    # ── candidates ─────────────────────────────────────────────────────────
    def _scan(self) -> Tuple[List[str], List[str]]:
        """(files to track, files skipped because they look like they hold secrets)."""
        exts = _extensions()
        track, skipped = [], []
        for root, dirs, files in os.walk(self.config_dir):
            dirs[:] = [d for d in dirs if d != ".git" and not d.startswith(".indus3d-")]
            for f in files:
                full = os.path.join(root, f)
                if not f.endswith(exts) or os.path.islink(full):
                    continue
                rel = os.path.relpath(full, self.config_dir)
                if is_secret_name(f):
                    skipped.append(rel)
                    continue
                try:
                    if os.path.getsize(full) > _MAX_FILE_BYTES:
                        continue
                    with open(full, "r", errors="replace") as fh:
                        if has_secret_content(fh.read()):
                            skipped.append(rel)
                            continue
                except OSError:
                    continue
                track.append(rel)
        return sorted(track), sorted(skipped)

    def has_changes(self) -> bool:
        if not self._has_repo():
            return False
        code, out, _ = self._run_git(["status", "--porcelain"])
        if code != 0:
            return False
        exts = _extensions()
        return any(line.strip().endswith(exts) for line in out.splitlines())

    # ── backup ─────────────────────────────────────────────────────────────
    def auto_backup(self, reason: str = "Automated configuration backup") -> Dict:
        if not self.enabled:
            return self._disabled()
        reason = _clean_text(reason, "Automated configuration backup")
        with self._lock:
            if not self._prepare():
                return {"status": "error", "error": "git repository could not be initialised"}
            track, skipped = self._scan()
            if skipped:
                logger.warning("Config backup skipped files that look like they contain secrets: "
                               + ", ".join(skipped))
            if not track:
                return {"status": "unchanged", "message": "No configuration files found to track",
                        "skipped_secrets": skipped}
            self._run_git(["add", "--"] + track)
            code, _, _ = self._run_git(["diff", "--cached", "--quiet"])
            if code == 0:
                return {"status": "unchanged", "message": "No configuration changes to commit",
                        "skipped_secrets": skipped}
            _, staged, _ = self._run_git(["diff", "--cached", "--name-only"])
            file_list = [f for f in staged.splitlines() if f]
            ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"{reason} [{ts_str}]\n\nModified: {', '.join(file_list)}"
            code, _, err = self._run_git(["commit", "-m", commit_msg])
            if code != 0:
                logger.error(f"Commit failed: {err}")
                return {"status": "error", "error": err, "skipped_secrets": skipped}
            _, commit_hash, _ = self._run_git(["rev-parse", "HEAD"])
            logger.info(f"Klipper config auto-backup created: {commit_hash[:8]} ({reason})")
            return {"status": "committed", "commit": commit_hash, "short_commit": commit_hash[:8],
                    "files": file_list, "message": commit_msg, "timestamp": time.time(),
                    "skipped_secrets": skipped}

    def auto_backup_bounded(self, reason: str, timeout: float = 8.0) -> Dict:
        """``auto_backup`` that never blocks the caller for longer than ``timeout`` seconds and never raises."""
        try:
            fut = _executor().submit(self.auto_backup, reason)
            return fut.result(timeout=timeout)
        except FutureTimeout:
            logger.warning("Config auto-backup is taking too long; continuing without waiting for it")
            return {"status": "pending", "message": "Backup still running in the background"}
        except Exception as e:
            logger.warning(f"Config auto-backup failed: {e}")
            return {"status": "error", "error": str(e)}

    # ── history ────────────────────────────────────────────────────────────
    def get_history(self, limit: int = 25) -> List[Dict]:
        if not self._has_repo():
            return []
        limit = max(1, min(int(limit), 500))
        code, out, _ = self._run_git(["log", f"-n{limit}", "--pretty=format:%H|%an|%at|%s"])
        if code != 0 or not out:
            return []
        history = []
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            commit_hash, author, ts_str, subject = parts
            try:
                ts = float(ts_str)
                dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts, dt_str = 0.0, ""
            history.append({"commit": commit_hash, "short_commit": commit_hash[:8], "author": author,
                            "timestamp": ts, "date": dt_str, "message": subject})
        return history

    def resolve_commit(self, ref) -> Optional[str]:
        """Full hash for a hex string that names a commit in this repository's history, else None.
        Branch names, ``HEAD~3`` and other revision syntax are rejected."""
        if not isinstance(ref, str) or not _HASH_RE.match(ref) or not self._has_repo():
            return None
        code, full, _ = self._run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        if code != 0 or not full.startswith(ref.lower()):
            return None
        code, out, _ = self._run_git(["rev-list", "HEAD"])
        if code != 0 or full not in out.split():
            return None
        return full

    def get_diff(self, commit_hash: str) -> Dict:
        if not self.enabled:
            return self._disabled()
        full = self.resolve_commit(commit_hash)
        if full is None:
            return {"error": "Unknown commit"}
        code, diff_text, err = self._run_git(["show", "--stat", "--patch", "--no-color", full, "--"])
        if code != 0:
            return {"error": err or "Failed to load diff"}
        return {"commit": full, "diff": diff_text}

    # ── restore ────────────────────────────────────────────────────────────
    def restore_commit(self, commit_hash: str) -> Dict:
        """Restore the config files that exist in ``commit_hash``. Never deletes files."""
        if not self.enabled:
            return self._disabled()
        with self._lock:
            full = self.resolve_commit(commit_hash)
            if full is None:
                return {"status": "error", "error": "Unknown commit"}

            # 1. safety snapshot before touching anything
            snapshot = self.auto_backup(reason="Pre-restore safety snapshot")
            if snapshot.get("status") == "error":
                return {"status": "error", "error": f"Safety snapshot failed: {snapshot.get('error')}"}

            # 2. only files the target commit tracked, and that this policy allows
            code, listing, err = self._run_git(["ls-tree", "-r", "--name-only", full])
            if code != 0:
                return {"status": "error", "error": f"Could not read commit: {err}"}
            exts = _extensions()
            targets = [f for f in listing.splitlines()
                       if f.endswith(exts) and not is_secret_name(f) and ".." not in f.split("/")]
            if not targets:
                return {"status": "unchanged", "message": "That commit tracks no restorable files",
                        "restored_from": full, "changed_files": []}

            # files the snapshot could not save (secret-looking) would be lost: keep a private copy
            kept = self._keep_unsnapshotted(targets, snapshot.get("skipped_secrets") or [])

            # working tree vs target commit, before checkout: exactly the files this restore rewrites
            _, changed, _ = self._run_git(["diff", "--name-only", full, "--"] + targets)
            code, _, err = self._run_git(["checkout", full, "--"] + targets)
            if code != 0:
                return {"status": "error", "error": f"Failed to check out {full[:8]}: {err}"}
            changed_files = [f for f in changed.splitlines() if f]
            result = {"status": "restored" if changed_files else "unchanged", "restored_from": full,
                      "short_commit": full[:8], "changed_files": changed_files,
                      "snapshot": snapshot.get("short_commit"),
                      "needs_firmware_restart": bool(changed_files)}
            if kept:
                result["private_copies"] = kept
            if changed_files:
                commit = self.auto_backup(reason=f"Restored configuration from commit {full[:8]}")
                result["commit"] = commit.get("commit")
            return result

    def _keep_unsnapshotted(self, targets: List[str], skipped: List[str]) -> List[str]:
        overlap = [f for f in targets if f in set(skipped)]
        if not overlap:
            return []
        dest_root = os.path.join(self.config_dir, ".indus3d-restore-backup", datetime.now().strftime("%Y%m%d-%H%M%S"))
        kept = []
        for rel in overlap:
            src = os.path.join(self.config_dir, rel)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(dest_root, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                kept.append(os.path.relpath(dst, self.config_dir))
            except OSError as e:
                logger.warning(f"Could not keep a copy of {rel}: {e}")
        return kept


_executor_lock = threading.Lock()
_exec: Optional[ThreadPoolExecutor] = None
_manager: Optional[ConfigBackupManager] = None
_manager_lock = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _exec
    with _executor_lock:
        if _exec is None:
            _exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cfg-backup")
        return _exec


def get_manager() -> ConfigBackupManager:
    """The process-wide manager, built on first use (no I/O in its constructor)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ConfigBackupManager(get_config_dir())
        return _manager


def reset_manager() -> None:
    """Forget the singleton (tests / config-dir change)."""
    global _manager
    with _manager_lock:
        _manager = None
