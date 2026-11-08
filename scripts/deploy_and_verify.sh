#!/usr/bin/env bash
# Indus3D Deployment & Stability Verification Script
# Automatically builds, transfers, deploys, and verifies setup health on host.

set -euo pipefail

HOST="${INDUS3D_HOST:-100.94.157.108}"
USER="${INDUS3D_USER:-krishnanu}"
DEST="/home/${USER}/indus3d"

echo "🚀 [1/4] Building frontend assets..."
(cd frontend && npm run build)

echo "📦 [2/4] Syncing codebase to host ${HOST}..."
rsync -avz --exclude='.git' --exclude='node_modules' --exclude='.venv' --exclude='__pycache__' \
  backend frontend/dist flake.nix nix scripts \
  "${USER}@${HOST}:${DEST}/"

echo "🔄 [3/4] Rebuilding and applying NixOS configuration on host..."
ssh -t "${USER}@${HOST}" "
  cd /etc/nixos
  echo 'Updating Indus3D service...'
  sudo nixos-rebuild switch --flake .#nixos-ks
  sudo systemctl restart indus3d
"

echo "🩺 [4/4] Executing Indus3D Comprehensive System Stability Audit..."
ssh "${USER}@${HOST}" "python3 ${DEST}/scripts/check_system_stability.py"
