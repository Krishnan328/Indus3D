# Indus3D: Real-Time Digital Twin & Closed-Loop Quality Controller for 3D Printers

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/Frontend-React_18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![Three.js](https://img.shields.io/badge/3D-Three.js-000000.svg?logo=three.js&logoColor=white)](https://threejs.org/)
[![Rust DSP](https://img.shields.io/badge/DSP-Rust-DEA584.svg?logo=rust&logoColor=white)](backend/dsp/)
[![Klipper](https://img.shields.io/badge/Firmware-Klipper-red.svg)](https://www.klipper3d.org/)

Indus3D is an open-source, real-time digital twin and closed-loop quality control platform for Klipper and Moonraker 3D printers. It continuously monitors physical toolhead kinematics, extrusion dynamics, thermal dissipation, and structural vibrations at 10 Hz, executing intelligent real-time corrective actions (M220 speed scaling, M221 flow compensation, dynamic Pressure Advance, adaptive cooling, and thermal Z-offset leveling) to prevent print failures and optimize part quality.

---

## 🌟 Key Features

### 1. Real-Time Physics-Based Digital Twin
- **Kinematic Model**: Tracks commanded vs. live physical toolhead position, finite-difference velocity, acceleration, and belt stress reversal dynamics.
- **Thermal Model**: First-order thermal lag observer predicting true nozzle melt-zone temperature and early-warning thermal runaway detection.
- **Extrusion Dynamics**: Calculates instantaneous volumetric flow ($mm^3/s$), bead cross-sectional area (stadium/pill model), and under/over-extrusion ratios.
- **Vibration & Resonance Monitor**: Integrates with high-speed ADXL345 accelerometer telemetry to track structural resonance frequencies and dynamically adjust input shaping.

### 2. High-Speed Rust DSP Pipeline (`backend/dsp`)
- **Binary ADXL Streaming**: 14-byte packed little-endian binary protocol (`IDX` header) streaming raw 3200 Hz accelerometer counts with low MCU overhead.
- **Fast-Path Collision & Impact Detector**: Real-time g-force spike and kurtosis impulse detection debounced at sub-millisecond intervals. Instantly triggers safety alerts and pauses the print upon toolhead crash or severe layer knock.
- **Slow-Path Spectral Telemetry with Motor Notch Filtering**: 1-Hz Hanning-windowed FFT calculating RMS, peak resonance frequency, kurtosis, and dynamic stiffness. Actively notches out motor step harmonics ($f = v \times \text{steps/mm}$) using velocity metadata from Python.
- **Standalone CLI Resonance Analyser**: Parses Klipper `TEST_RESONANCES` CSV data, measures PSD half-power bandwidth damping ratio ($\zeta$), and recommends optimal input shapers (ZV, MZV, EI, 2HUMP_EI).

### 3. Autopilot Closed-Loop Quality Controller
- **Adaptive Flow Control (`M221`)**: Detects extrusion variations in real time and trims flow rate within safe physical bounds (85%–115%).
- **Speed-Lag Compensation (`M220`)**: Automatically throttles print speed when positional lag exceeds mechanical compliance thresholds, smoothly recovering when lag clears.
- **Dynamic Pressure Advance**: Adapts Klipper's `SET_PRESSURE_ADVANCE` on the fly based on volumetric flow rate and shear-thinning polymer rheology.
- **Thermal Z-Offset Expansion Compensation**: Compensates for vertical frame thermal growth and layer height errors with anti-windup safety bounds.
- **Predictive Clog Detection**: Halts or pauses before catastrophic grinding occurs if melt pressure exceeds motor torque limits.

### 4. Bed Adaptation & Collision Safety Engine
- **OrcaSlicer / PrusaSlicer / BambuStudio Profile Import**: Directly parses `printable_area`, `printable_height`, and `bed_exclude_area` (bed leveling screws, clips, wipe towers, purge buckets) from `.json` slicer profiles.
- **Custom 3D Bed Models (STL)**: Upload, render, and inspect custom physical build plate geometries in Three.js with realistic metal/texture shading.
- **Collision Guardrails**: Forbids downward Z corrections near or over bed screws and clips below clearance altitude ($Z < 10\text{ mm}$). Clamps total Z adjustments strictly within `[-0.25mm, +0.50mm]`.

### 5. Modern Dashboard & Visualizer
- **Interactive 3D Viewport**: WebGL/Three.js digital twin rendering live nozzle coordinates, extruder path contours, and physical exclusion zones.
- **Full Klipper Controls**: Mainsail-style toolhead jogging, temperature gauges, extrusion controls, emergency stop, and interactive G-code terminal with live `[QC]` feedback tagging.
- **Touch UI Mode**: Tailored for 5" and 7" Raspberry Pi touchscreen displays.
- **Sensor Telemetry**: PZEM-004T AC power metering, Spoolman active spool tracking, and multi-channel webhook notifications (Discord/Telegram).

### 6. Edge Computer Vision & Failure Detection (`backend/edge`)
- **Zero-Dataset Motion Watchdog (`edge/watchdog.py`)**: Real-time OpenCV MOG2 background subtraction detecting detached prints or moving spaghetti masses without requiring any machine learning model or dataset.
- **Pre-Trained YOLO Defect Inspector (`edge/inspector.py`)**: Automated downloader (`tools/download_vision_model.py`) fetching MIT-licensed weights fine-tuned on 9,000+ 3D printing failure images (detects `spaghetti`, `severe stringing`, `blobs/zits`, and `part detachment`).
- **Autonomous First-Layer Squish**: Analyzes initial bead squish and baby-steps Klipper Z-offset on the fly (`SET_GCODE_OFFSET Z_ADJUST=±0.01`).
- **Smart Safety Guardrails**: Pauses print and pulses alert LEDs on catastrophic failures; logs warnings and dispatches Discord/Telegram notifications on non-critical defects without aborting the job.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│                   Frontend (React + Vite)              │
│       Three.js Viewport • Dashboard Grid • Touch UI    │
└───────────────────────────▲────────────────────────────┘
                            │ WebSocket (10 Hz) / REST
┌───────────────────────────▼────────────────────────────┐
│                    Flask API Gateway                   │
│   Auth Gate • Rate Limiting • Bed Safety • G-Code Proxy│
└─────────────┬───────────────────────────┬──────────────┘
              │                           │
┌─────────────▼──────────────┐ ┌──────────▼──────────────┐
│  Digital Twin Engine (10Hz)│ │  Moonraker HTTP / WS    │
│  Kinematics • Thermals     │ │  /printer/objects/query │
│  Extrusion  • Quality Ctrl │ │  /printer/gcode/script  │
└─────────────┬──────────────┘ └──────────┬──────────────┘
              │                           │
              │ UDP 3201 (1Hz Spectral)   │
              │ UDP 3202 (Collision)      │
              │ UDP 3203 (Velocity Meta)  │
┌─────────────▼──────────────┐            │
│  Rust DSP Pipeline         │            │
│  Fast-Path Crash Detector  │            │
│  Slow-Path FFT + Notch     │            │
│  Input Shaper Recommender  │            ▼
└─────────────▲──────────────┘    Klipper Firmware (MCU)
              │ UDP 3200 (Binary ADXL)
              └───────────────────────────┘
```

---

## 🚀 Quickstart & Installation

### Prerequisites
- Python 3.9 or higher
- Node.js 18 or higher & npm
- Klipper & Moonraker (for physical printer connection)

### Automated Install (Raspberry Pi / Linux)
The automated installer configures the Python virtual environment, compiles the frontend SPA for low-memory standalone hosting, configures Moonraker's update manager, symlinks Klipper vibration modules, and installs the `indus3d.service` systemd daemon:

```bash
git clone https://github.com/Krishnan328/Indus3D.git
cd Indus3D
./install.sh
```
Once installed, your dashboard is accessible at `http://<your-pi-ip>:5001`.

### Manual Setup

#### 1. Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m db.migrator
```

Run in **Simulation Mode** (no printer hardware required):
```bash
python main.py --sim --shape benchy --layers 40
```

Run in **Live Mode** (connected to Klipper via Moonraker):
```bash
python main.py
```

#### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open your browser at `http://localhost:5173`.

---

## ⚙️ Configuration

### Environment Variables (`backend/.env`)
Copy `backend/.env.example` to `backend/.env`:
```ini
MOONRAKER_HOST=127.0.0.1
MOONRAKER_PORT=7125
FLASK_HOST=0.0.0.0
FLASK_PORT=5001
INDUS3D_PASSWORD=            # Optional session password
TWIN_TICK_HZ=10              # Telemetry frequency
PZEM_PORT=/dev/ttyUSB0       # Optional PZEM power monitor
SPOOLMAN_URL=                # Optional Spoolman URL
```

### Klipper Integration (`indus3d.cfg`)
Include Indus3D overrides in your Klipper `printer.cfg`:
```ini
[include indus3d.cfg]
```

---

## 🧪 Testing

Indus3D includes an automated test suite covering bed safety geometry, extrusion dynamics, thermal runaway detection, DSP binary protocol, collision alerts, edge vision inspection, and resonance analysis:

#### Python Backend Tests (56 unit & integration tests)
```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

#### Rust DSP Engine Tests (Unit tests for notch filter, FFT, fast-path spike detector)
```bash
cd backend/dsp
cargo test
```

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for local development workflows and code conventions.

---

## 📜 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
