#!/usr/bin/env bash
# ==============================================================================
# Indus3D Standalone Debian / Raspberry Pi OS Uninstaller
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="${SCRIPT_DIR}/integrations/kiauh/indus3d_installer.sh"

if [ -f "${INSTALLER}" ]; then
    chmod +x "${INSTALLER}"
    exec bash "${INSTALLER}" remove
else
    echo "Error: ${INSTALLER} not found."
    exit 1
fi
