#!/usr/bin/env bash
# ==============================================================================
# Indus3D - One-Line KIAUH Extension Installer
# Registers the Indus3D extension directly into your local KIAUH installation.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Krishnan328/Indus3D/main/integrations/kiauh/install-extension.sh | bash
# Or with custom path:
#   curl -fsSL ... | bash -s -- /custom/path/to/kiauh
# ==============================================================================

set -euo pipefail

REPO_URL="${INDUS3D_REPO_URL:-https://github.com/Krishnan328/Indus3D.git}"
REPO_BRANCH="${INDUS3D_REPO_BRANCH:-main}"

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
NC="\033[0m"

CUSTOM_KIAUH_PATH="${1:-}"

find_kiauh_dir() {
    if [ -n "${CUSTOM_KIAUH_PATH}" ]; then
        if [ ! -f "${CUSTOM_KIAUH_PATH}/kiauh.sh" ] || [ ! -d "${CUSTOM_KIAUH_PATH}/kiauh/extensions" ]; then
            echo "Not a supported KIAUH checkout: ${CUSTOM_KIAUH_PATH}" >&2
            return 1
        fi
        echo "${CUSTOM_KIAUH_PATH}"
        return
    fi

    # Standard locations
    for dir in "${HOME}/kiauh" "/home/${USER}/kiauh" "/root/kiauh"; do
        if [ -f "${dir}/kiauh.sh" ] && [ -d "${dir}/kiauh/extensions" ]; then
            echo "${dir}"
            return
        fi
    done

    echo ""
}

KIAUH_DIR=$(find_kiauh_dir)

if [ -z "${KIAUH_DIR}" ]; then
    echo -e "${YELLOW}⚠️  KIAUH directory not automatically found.${NC}"
    echo -e "If KIAUH is installed in a custom location, run:"
    echo -e "  bash install-extension.sh /path/to/your/kiauh"
    echo ""
    echo -e "${CYAN}Alternatively, you can install Indus3D directly without KIAUH using:${NC}"
    echo -e "  git clone ${REPO_URL} ~/indus3d && cd ~/indus3d && ./install.sh"
    exit 1
fi

EXT_DIR="${KIAUH_DIR}/kiauh/extensions/indus3d"
echo -e "${CYAN}🚀 Registering Indus3D Extension in KIAUH at: ${EXT_DIR}${NC}"

mkdir -p "${EXT_DIR}"

# Run from an authenticated clone: raw.githubusercontent.com downloads cannot
# access this private repository using the user's Git credentials.
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for name in metadata.json extension.py indus3d_installer.sh config_file.py; do
    if [ ! -f "${SOURCE_DIR}/${name}" ]; then
        echo "Run this script from a cloned Indus3D repository, not curl | bash." >&2
        exit 1
    fi
    cp "${SOURCE_DIR}/${name}" "${EXT_DIR}/${name}"
done
chmod +x "${EXT_DIR}/indus3d_installer.sh"
chmod +x "${EXT_DIR}/extension.py"

echo ""
echo -e "${GREEN}===================================================================${NC}"
echo -e "${GREEN}   ✔ Indus3D Extension successfully linked into KIAUH!             ${NC}"
echo -e "${GREEN}===================================================================${NC}"
echo -e "To install or manage Indus3D:"
echo -e "  1. Run: ${CYAN}${KIAUH_DIR}/kiauh.sh${NC}"
echo -e "  2. Select: ${YELLOW}[E]xtensions${NC}"
echo -e "  3. Select: ${GREEN}Indus3D${NC} -> ${CYAN}[1] Install${NC}"
echo ""
