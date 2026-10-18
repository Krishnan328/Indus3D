#!/bin/bash
# Indus3D Uninstallation Script

set -e

# 1. Check if running as root
if [ "$EUID" -eq 0 ]; then
  echo "❌ Please do not run this script as root. Run as your standard user."
  exit 1
fi

echo "================================================="
echo "    🗑️  Uninstalling Indus3D"
echo "================================================="

# 2. Stop and disable service
echo -e "\n[1/3] Stopping and removing systemd service..."
if systemctl is-active --quiet indus3d.service; then
    sudo systemctl stop indus3d.service
fi
if systemctl is-enabled --quiet indus3d.service; then
    sudo systemctl disable indus3d.service
fi

if [ -f "/etc/systemd/system/indus3d.service" ]; then
    sudo rm /etc/systemd/system/indus3d.service
    sudo systemctl daemon-reload
fi

# 3. Remove Klipper Integration
echo -e "\n[2/3] Removing Moonraker integration..."
KLIPPER_CONF_DIR="${HOME}/printer_data/config"
if [ -f "${KLIPPER_CONF_DIR}/indus3d.cfg" ]; then
    rm "${KLIPPER_CONF_DIR}/indus3d.cfg"
fi

if [ -f "${KLIPPER_CONF_DIR}/printer.cfg" ]; then
    # Create a backup just in case
    cp "${KLIPPER_CONF_DIR}/printer.cfg" "${KLIPPER_CONF_DIR}/printer.cfg.indus3d_bak"
    # Remove the include line and the preceding comment if it exists
    sed -i '/# Indus3D Integration/d' "${KLIPPER_CONF_DIR}/printer.cfg"
    sed -i '/\[include indus3d.cfg\]/d' "${KLIPPER_CONF_DIR}/printer.cfg"
fi

echo -e "\n[3/3] Cleanup complete."
echo "Note: The Indus3D directory itself was NOT deleted."
echo "You can safely delete it by running: rm -rf $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
