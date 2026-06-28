#!/bin/bash
# deploy_to_pi.sh
# ----------------
# Deploys Indus3D to your Raspberry Pi over SSH without touching Klipper/Mainsail.
# Run this from your dev machine inside the project root.
#
# Usage:
#   chmod +x deploy_to_pi.sh
#   ./deploy_to_pi.sh
#
# Prerequisites on your dev machine:
#   - SSH access to Pi (key-based preferred, password works too)
#   - rsync installed (brew install rsync on Mac, apt install rsync on Linux)
#   - Node.js installed locally (to build frontend)
#
# What it does:
#   1. Builds the React frontend locally (npm run build)
#   2. rsyncs only the backend + frontend/dist to the Pi
#   3. Installs Python deps in a venv on the Pi
#   4. Starts Indus3D as a systemd service (port 5001, separate from Klipper on 7125)
#   5. Serves the built frontend on port 3000 via a simple Python static server

set -e

# ── EDIT THESE ────────────────────────────────────────────────────────────────
PI_USER="pi"
PI_HOST="100.88.38.105"          # Your Tailscale IP
PI_DEST="/home/pi/indus3d"       # Where to install on Pi
# ─────────────────────────────────────────────────────────────────────────────

echo "🔨 Building frontend..."
cd frontend
npm install --silent
npm run build
cd ..

echo "📦 Syncing to Pi at ${PI_USER}@${PI_HOST}:${PI_DEST}..."
rsync -avz --progress \
  --exclude 'frontend/node_modules' \
  --exclude 'backend/indus_env' \
  --exclude 'backend/__pycache__' \
  --exclude 'backend/**/__pycache__' \
  --exclude 'backend/db/flight_record.db' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  backend/ "${PI_USER}@${PI_HOST}:${PI_DEST}/backend/"

rsync -avz --progress \
  frontend/dist/ "${PI_USER}@${PI_HOST}:${PI_DEST}/frontend_dist/"

echo "🐍 Installing Python dependencies on Pi..."
ssh "${PI_USER}@${PI_HOST}" bash << 'REMOTE'
  set -e
  cd ~/indus3d/backend

  # Create venv if not exists
  if [ ! -d "indus_env" ]; then
    python3 -m venv indus_env
    echo "✅ Virtual env created"
  fi

  source indus_env/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  echo "✅ Dependencies installed"
REMOTE

echo "⚙️  Installing systemd services on Pi..."
ssh "${PI_USER}@${PI_HOST}" bash << 'REMOTE'
  # Indus3D backend service (port 5001)
  sudo tee /etc/systemd/system/indus3d.service > /dev/null << 'SERVICE'
[Unit]
Description=Indus3D Backend
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/indus3d/backend
ExecStart=/home/pi/indus3d/backend/indus_env/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE

  # Indus3D frontend static server (port 3000)
  sudo tee /etc/systemd/system/indus3d-ui.service > /dev/null << 'SERVICE'
[Unit]
Description=Indus3D Frontend
After=indus3d.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/indus3d/frontend_dist
ExecStart=/usr/bin/python3 -m http.server 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable indus3d indus3d-ui
  sudo systemctl restart indus3d indus3d-ui
  echo "✅ Services started"
  sleep 2
  sudo systemctl status indus3d --no-pager | tail -5
REMOTE

PI_IP_DISPLAY="${PI_HOST}"
echo ""
echo "✅ Deployment complete!"
echo ""
echo "   Dashboard : http://${PI_IP_DISPLAY}:3000"
echo "   API       : http://${PI_IP_DISPLAY}:5001"
echo "   Mainsail  : http://${PI_IP_DISPLAY}  (unchanged)"
echo "   Klipper   : port 7125  (unchanged)"
echo ""
echo "To check logs on Pi:"
echo "   ssh ${PI_USER}@${PI_HOST} 'journalctl -u indus3d -f'"
