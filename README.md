# Indus3D — 3D Printer Digital Twin Dashboard

A real-time digital twin dashboard for any Klipper-based 3D printer.
Runs a physics-informed mathematical model alongside the printer and exposes
live kinematic, thermal, and extrusion metrics via a React dashboard.

## Quick Start

### Simulation mode (no printer needed)

```bash
cd backend
pip install -r requirements.txt
python main.py --sim --profile indus_sim_ender3.cfg

# Default — benchy, 40 layers
python main.py --sim

# Calibration cube, 30 layers
python main.py --sim --shape cube --layers 30

# Benchy, higher resolution
python main.py --sim --shape benchy --layers 80

# In another terminal
cd frontend
npm install
npm run dev
# Open http://localhost:5173
# Type TEST in the G-Code terminal to run a demo print
```

### Live mode (printer connected via Tailscale)

```bash
# Edit backend/config/indus_overrides.cfg and set moonraker_ip
cd backend && python main.py

cd frontend && npm run dev
```

## Deploy to Raspberry Pi

```bash
chmod +x deploy_to_pi.sh
./deploy_to_pi.sh
# Dashboard: http://<pi-ip>:3000
# Klipper/Mainsail untouched on port 80/7125
```

## Push to GitHub

### First time

```bash
git init
git add .
git commit -m "Initial Indus3D commit"

# Create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/indus3d.git
git branch -M main
git push -u origin main
```

### After making changes

```bash
git add .
git commit -m "describe your change"
git push
```

## Architecture

```
Browser (React + Three.js)
    ↕ WebSocket ws://<host>:5001/ws/twin  (10 Hz)
    ↕ HTTP POST /api/control/execute
Flask API (port 5001)
    ↕ reads from TelemetryWorker.latest
TelemetryWorker / SimulatedTelemetryWorker
    ↕ polls Klipper via Moonraker HTTP
Digital Twin Models (kinematic / thermal / extrusion)
    ↕ writes to SQLite
```

## Ports

| Service     | Port | Notes                    |
| ----------- | ---- | ------------------------ |
| Mainsail    | 80   | Unchanged                |
| Moonraker   | 7125 | Unchanged                |
| Indus3D API | 5001 | Backend Flask server     |
| Indus3D UI  | 3000 | Built frontend (Pi only) |
| Vite dev    | 5173 | Dev machine only         |
