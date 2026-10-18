#!/bin/bash
# Indus3D Installation Script
# This script sets up the Python backend, installs dependencies, configures systemd,
# and integrates Indus3D with Moonraker/Klipper.

set -e

# Setup variables
USER=$(whoami)
SYSTEMDDIR="/etc/systemd/system"
INDUS3D_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KLIPPER_CONF_DIR="${HOME}/printer_data/config"
PYTHONDIR="${INDUS3D_DIR}/backend/.venv"

# 1. Check if running as root
if [ "$EUID" -eq 0 ]; then
  echo "❌ Please do not run this script as root. Run as your standard user (e.g., 'pi')."
  exit 1
fi

echo "================================================="
echo "    🚀 Installing Indus3D for user: $USER"
echo "================================================="

# 2. Install System Dependencies
echo -e "\n[1/5] Installing system dependencies (ffmpeg, python3-venv)..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg wget zip unzip

# 3. Setup Python Virtual Environment
echo -e "\n[2/5] Setting up Python virtual environment..."
cd "${INDUS3D_DIR}/backend"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 4. Configure Klipper/Moonraker Integration
echo -e "\n[3/5] Configuring Moonraker Update Manager..."
if [ -d "$KLIPPER_CONF_DIR" ]; then
    cp "${INDUS3D_DIR}/indus3d.cfg" "${KLIPPER_CONF_DIR}/indus3d.cfg"
    
    if ! grep -q "\[include indus3d.cfg\]" "${KLIPPER_CONF_DIR}/printer.cfg"; then
        echo -e "\n# Indus3D Integration\n[include indus3d.cfg]\n" >> "${KLIPPER_CONF_DIR}/printer.cfg"
        echo "✅ Added [include indus3d.cfg] to printer.cfg"
    else
        echo "✅ indus3d.cfg is already included in printer.cfg"
    fi
else
    echo "⚠️  Warning: ${KLIPPER_CONF_DIR} not found."
    echo "Skipping auto-include of indus3d.cfg. You may need to include it manually."
fi

# 5. Create Systemd Service
echo -e "\n[4/5] Creating systemd service..."
SERVICE_FILE="/tmp/indus3d.service"
cat << SERVICE_EOF > $SERVICE_FILE
[Unit]
Description=Indus3D Digital Twin and Dashboard
After=network-online.target moonraker.service
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${INDUS3D_DIR}/backend
ExecStart=${PYTHONDIR}/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo mv $SERVICE_FILE $SYSTEMDDIR/indus3d.service
sudo chown root:root $SYSTEMDDIR/indus3d.service
sudo chmod 644 $SYSTEMDDIR/indus3d.service

# 6. Enable and Start Service
echo -e "\n[5/5] Enabling and starting Indus3D service..."
sudo systemctl daemon-reload
sudo systemctl enable indus3d.service
sudo systemctl restart indus3d.service

echo -e "\n================================================="
echo "    🎉 Indus3D Installation Complete! "
echo "================================================="
echo "The digital twin backend is now running as a background service."
echo "You can view your dashboard at: http://<your-pi-ip>:5001"
