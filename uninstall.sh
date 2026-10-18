#!/bin/bash
# Indus3D Uninstallation Script
# Safely stops systemd service and cleans up Klipper & Moonraker integrations.

set -e

# 1. Check if running as root
if [ "$EUID" -eq 0 ]; then
  echo "❌ Please do not run this script as root. Run as your standard user."
  exit 1
fi

INDUS3D_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KLIPPER_CONF_DIR="${HOME}/printer_data/config"
KLIPPER_EXTRAS_DIR="${HOME}/klipper/klippy/extras"

echo "================================================="
echo "    🗑️  Uninstalling Indus3D"
echo "================================================="

# 2. Stop and disable service
echo -e "\n[1/4] Stopping and removing systemd service..."
if systemctl is-active --quiet indus3d.service 2>/dev/null; then
    sudo systemctl stop indus3d.service
    echo "✅ Stopped indus3d.service"
fi
if systemctl is-enabled --quiet indus3d.service 2>/dev/null; then
    sudo systemctl disable indus3d.service
    echo "✅ Disabled indus3d.service"
fi

if [ -f "/etc/systemd/system/indus3d.service" ]; then
    sudo rm /etc/systemd/system/indus3d.service
    sudo systemctl daemon-reload
    echo "✅ Removed /etc/systemd/system/indus3d.service"
fi

# 3. Remove Klipper Integration
echo -e "\n[2/4] Removing Klipper integration..."
if [ -f "${KLIPPER_CONF_DIR}/indus3d.cfg" ]; then
    rm "${KLIPPER_CONF_DIR}/indus3d.cfg"
    echo "✅ Removed ${KLIPPER_CONF_DIR}/indus3d.cfg"
fi

if [ -f "${KLIPPER_CONF_DIR}/printer.cfg" ]; then
    cp "${KLIPPER_CONF_DIR}/printer.cfg" "${KLIPPER_CONF_DIR}/printer.cfg.indus3d_bak"
    sed -i '/# Indus3D Integration/d' "${KLIPPER_CONF_DIR}/printer.cfg" 2>/dev/null || true
    sed -i '/\[include indus3d.cfg\]/d' "${KLIPPER_CONF_DIR}/printer.cfg" 2>/dev/null || true
    echo "✅ Removed [include indus3d.cfg] from printer.cfg (backup at printer.cfg.indus3d_bak)"
fi

if [ -L "${KLIPPER_EXTRAS_DIR}/indus_vibration.py" ]; then
    rm "${KLIPPER_EXTRAS_DIR}/indus_vibration.py"
    echo "✅ Removed Klipper extra module symlink"
fi

# 4. Remove Moonraker Update Manager Section
echo -e "\n[3/4] Removing Moonraker update manager configuration..."
if [ -f "${KLIPPER_CONF_DIR}/moonraker.conf" ]; then
    python3 - << 'PY_CLEAN'
import sys, os
conf_path = os.path.expanduser("~/printer_data/config/moonraker.conf")
if os.path.exists(conf_path):
    try:
        with open(conf_path, "r") as f:
            lines = f.readlines()
        new_lines = []
        skip = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[update_manager indus3d]"):
                skip = True
                continue
            if skip and stripped.startswith("["):
                skip = False
            if not skip:
                new_lines.append(line)
        with open(conf_path, "w") as f:
            f.writelines(new_lines)
        print("✅ Cleaned [update_manager indus3d] from moonraker.conf")
    except Exception as e:
        print(f"⚠️  Could not clean moonraker.conf: {e}")
PY_CLEAN
fi

echo -e "\n[4/4] Cleanup complete."
echo "Note: The Indus3D repository folder was preserved at: ${INDUS3D_DIR}"
echo "To completely delete all files, run: rm -rf ${INDUS3D_DIR}"
