#!/usr/bin/env bash
# Moonraker invokes install_script with no arguments after updating the checkout.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/indus3d_installer.sh" refresh-dependencies
