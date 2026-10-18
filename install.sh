#!/bin/bash
# Indus3D Installation Script
# Sets up Python backend, builds frontend SPA, configures systemd,
# and integrates with Klipper & Moonraker.

set -e

# Setup variables
USER=$(whoami)
SYSTEMDDIR="/etc/systemd/system"
INDUS3D_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KLIPPER_CONF_DIR="${HOME}/printer_data/config"
KLIPPER_EXTRAS_DIR="${HOME}/klipper/klippy/extras"
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
echo -e "\n[1/6] Installing system dependencies (ffmpeg, python3-venv, git, curl)..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg wget curl zip unzip

# 3. Setup Python Virtual Environment
echo -e "\n[2/6] Setting up Python virtual environment..."
cd "${INDUS3D_DIR}/backend"
if [ ! -d "${PYTHONDIR}" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
deactivate

# 4. Optional Rust DSP Engine Build
echo -e "\n[3/6] Checking Rust DSP vibration engine..."
if command -v cargo &> /dev/null; then
    echo "🦀 Building Rust DSP binary (release mode)..."
    cd "${INDUS3D_DIR}/backend/dsp"
    cargo build --release
    echo "✅ Rust DSP engine compiled successfully."
else
    echo "ℹ️  Rust toolchain (cargo) not found — using Python/simulated DSP fallback."
fi

# 5. Build Frontend SPA Dashboard
echo -e "\n[4/6] Setting up frontend dashboard..."
cd "${INDUS3D_DIR}/frontend"
if command -v npm &> /dev/null; then
    echo "📦 Building React 18 production bundle..."
    npm install --no-audit --no-fund
    npm run build
    echo "✅ Frontend built cleanly to frontend/dist/."
else
    echo "⚠️  npm not detected. Attempting to install nodejs/npm..."
    if sudo apt-get install -y nodejs npm; then
        npm install --no-audit --no-fund
        npm run build
        echo "✅ Frontend built cleanly to frontend/dist/."
    else
        echo "⚠️  Could not install npm automatically. You can build manually later via 'cd frontend && npm install && npm run build'."
    fi
fi

# 6. Configure Klipper & Moonraker Integration
echo -e "\n[5/6] Configuring Klipper & Moonraker integration..."
if [ -d "$KLIPPER_CONF_DIR" ]; then
    # Copy indus3d.cfg into printer config
    cp "${INDUS3D_DIR}/indus3d.cfg" "${KLIPPER_CONF_DIR}/indus3d.cfg"
    
    # Include in printer.cfg
    if [ -f "${KLIPPER_CONF_DIR}/printer.cfg" ]; then
        if ! grep -q "\[include indus3d.cfg\]" "${KLIPPER_CONF_DIR}/printer.cfg"; then
            echo -e "\n# Indus3D Integration\n[include indus3d.cfg]\n" >> "${KLIPPER_CONF_DIR}/printer.cfg"
            echo "✅ Added [include indus3d.cfg] to printer.cfg"
        else
            echo "✅ indus3d.cfg is already included in printer.cfg"
        fi
    fi

    # Register in moonraker.conf update manager
    if [ -f "${KLIPPER_CONF_DIR}/moonraker.conf" ]; then
        if ! grep -q "\[update_manager indus3d\]" "${KLIPPER_CONF_DIR}/moonraker.conf"; then
            cat << MOONRAKER_EOF >> "${KLIPPER_CONF_DIR}/moonraker.conf"

# Indus3D Update Manager
[update_manager indus3d]
type: git_repo
path: ${INDUS3D_DIR}
origin: https://github.com/Krishnan328/Indus3D.git
primary_branch: main
is_system_service: True
managed_services: indus3d
MOONRAKER_EOF
            echo "✅ Added [update_manager indus3d] to moonraker.conf"
        else
            echo "✅ [update_manager indus3d] already configured in moonraker.conf"
        fi
    fi
else
    echo "⚠️  ${KLIPPER_CONF_DIR} not found. Skipping auto-configuration of printer.cfg and moonraker.conf."
fi

# Optional Klipper extras module symlink
if [ -d "$KLIPPER_EXTRAS_DIR" ]; then
    ln -sf "${INDUS3D_DIR}/klipper_modules/indus_vibration.py" "${KLIPPER_EXTRAS_DIR}/indus_vibration.py"
    echo "✅ Symlinked indus_vibration.py into ${KLIPPER_EXTRAS_DIR}/"
fi

# 7. Create & Start Systemd Service
echo -e "\n[6/6] Creating systemd service..."
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
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo mv $SERVICE_FILE $SYSTEMDDIR/indus3d.service
sudo chown root:root $SYSTEMDDIR/indus3d.service
sudo chmod 644 $SYSTEMDDIR/indus3d.service

sudo systemctl daemon-reload
sudo systemctl enable indus3d.service
sudo systemctl restart indus3d.service

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo -e "\n================================================="
echo "    🎉 Indus3D Installation Complete!"
echo "================================================="
echo "The digital twin backend and dashboard are running as a background service."
echo "Access your dashboard at: http://${IP_ADDR}:5001"
echo "Check status anytime with: sudo systemctl status indus3d.service"
