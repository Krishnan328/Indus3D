#!/usr/bin/env bash
# Register the Indus3D extension with an existing KIAUH checkout.
#
#   ./install_extension.sh              # copy into ~/kiauh
#   KIAUH_DIR=/opt/kiauh ./install_extension.sh
#   ./install_extension.sh --link       # symlink instead of copy (development)
#   ./install_extension.sh --remove
#
# KIAUH discovers extensions by scanning kiauh/extensions/*/metadata.json, so
# no KIAUH source needs patching. A `git pull` inside KIAUH leaves the
# extension in place because the folder is untracked there.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/indus3d"
KIAUH_DIR="${KIAUH_DIR:-${HOME}/kiauh}"
DEST="${KIAUH_DIR}/kiauh/extensions/indus3d"

if [ ! -d "${KIAUH_DIR}/kiauh/extensions" ]; then
  echo "KIAUH not found at ${KIAUH_DIR}."
  echo "Install it first:  git clone https://github.com/dw-0/kiauh.git ${KIAUH_DIR}"
  echo "or point KIAUH_DIR at your checkout."
  exit 1
fi

case "${1:-}" in
  --remove)
    rm -rf "${DEST}"
    echo "Removed ${DEST}"
    exit 0
    ;;
  --link)
    rm -rf "${DEST}"
    ln -s "${SRC}" "${DEST}"
    echo "Linked ${DEST} -> ${SRC}"
    ;;
  "")
    rm -rf "${DEST}"
    cp -R "${SRC}" "${DEST}"
    find "${DEST}" -name '__pycache__' -prune -exec rm -rf {} +
    echo "Copied extension to ${DEST}"
    ;;
  *)
    echo "usage: $0 [--link|--remove]"
    exit 2
    ;;
esac

echo "Start KIAUH (./kiauh.sh) -> Extensions -> Indus3D"
