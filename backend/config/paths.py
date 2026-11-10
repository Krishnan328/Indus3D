"""
config/paths.py
----------------
Resolves writable directories for configuration and persistent JSON files.
Crucial for environments where the Python package resides in a read-only
store (such as NixOS /nix/store).
"""

import os
from pathlib import Path


def get_config_dir() -> str:
    # 1. Explicit environment variable
    env_dir = os.environ.get("INDUS3D_CONFIG_DIR")
    if env_dir:
        try:
            os.makedirs(env_dir, exist_ok=True)
            if os.access(env_dir, os.W_OK):
                return env_dir
        except Exception:
            pass

    # 2. Inferred from INDUS3D_CONFIG_PATH (e.g. /var/lib/indus3d/config/indus_overrides.cfg)
    cfg_path = os.environ.get("INDUS3D_CONFIG_PATH")
    if cfg_path:
        parent = os.path.dirname(os.path.abspath(cfg_path))
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
                if os.access(parent, os.W_OK):
                    return parent
            except Exception:
                pass

    # 3. Source code directory if writable (e.g. standard editable / git install)
    here = os.path.dirname(os.path.abspath(__file__))
    if os.access(here, os.W_OK):
        return here

    # 4. Standard system and XDG paths
    candidates = [
        "/var/lib/indus3d/config",
        os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config/indus3d"), "config"),
        os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share/indus3d"), "config"),
        "/tmp/indus3d_config",
    ]
    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            if os.access(candidate, os.W_OK):
                return candidate
        except Exception:
            continue

    return here
