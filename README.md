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
- **Auto Z-Offset & Tribo-Acoustic Bed Friction Engine**: Computes the real-time High-Frequency Friction Index (HFFI: $1200 - 1600\text{ Hz}$ vs $20 - 400\text{ Hz}$) and microsecond-grade kinematic jerk spikes ($j_z > 400\text{ g/s}$). Differentiates nozzle bed rubbing from under-squished extrusions.
- **Fast-Path Collision & Impact Detector**: Real-time g-force spike and kurtosis impulse detection debounced at sub-millisecond intervals. Instantly triggers safety alerts and pauses the print upon toolhead crash or severe layer knock.
- **Slow-Path Spectral Telemetry with Motor Notch Filtering**: 1-Hz Hanning-windowed FFT calculating RMS, peak resonance frequency, kurtosis, and dynamic stiffness. Actively notches out motor step harmonics ($f = v \times \text{steps/mm}$) using velocity metadata from Python.
- **Standalone CLI Resonance Analyser**: Parses Klipper `TEST_RESONANCES` CSV data, measures PSD half-power bandwidth damping ratio ($\zeta$), and recommends optimal input shapers (ZV, MZV, EI, 2HUMP_EI).

### 3. Autopilot Closed-Loop Quality Controller
- **Auto-Z Bed Adhesion Closed-Loop Trimming**: Automatically trims Klipper Z-offset on layer 1 via `SET_GCODE_OFFSET Z_ADJUST=... MOVE=1` when tribo-acoustic rubbing or under-squish is detected, relieving bed scraping and ensuring strong polymer wetting.
- **Adaptive Flow Control (`M221`)**: Detects extrusion variations in real time and trims flow rate within safe physical bounds (85%–115%).
- **Speed-Lag Compensation (`M220`)**: Automatically throttles print speed when positional lag exceeds mechanical compliance thresholds, smoothly recovering when lag clears.
- **Dynamic Pressure Advance**: Adapts Klipper's `SET_PRESSURE_ADVANCE` on the fly based on volumetric flow rate and shear-thinning polymer rheology.
- **Thermal Z-Offset Expansion Compensation**: Compensates for vertical frame thermal growth and layer height errors with anti-windup safety bounds.
- **Predictive Clog Detection**: Halts or pauses before catastrophic grinding occurs if melt pressure exceeds motor torque limits.

### 4. Bed Adaptation & Collision Safety Engine
- **OrcaSlicer / PrusaSlicer / BambuStudio Profile Import**: Directly parses `printable_area`, `printable_height`, and `bed_exclude_area` (bed leveling screws, clips, wipe towers, purge buckets) from `.json` slicer profiles.
- **Custom 3D Bed Models (STL)**: Upload, render, and inspect custom physical build plate geometries in Three.js with realistic metal/texture shading.
- **Collision Guardrails**: Forbids downward Z corrections near or over bed screws and clips below clearance altitude ($Z < 10\text{ mm}$). Clamps total Z adjustments strictly within `[-0.25mm, +0.50mm]`.

### 5. Modern Dashboard, 3D Object Exclusion & Automation
- **Interactive 3D Viewport & Object Cancellation**: WebGL/Three.js digital twin rendering live nozzle coordinates, extruder path contours, and individual printed object bounding boxes. Operators can click any individual object in 3D or open the floating Objects HUD drawer to cancel defective parts mid-print (`EXCLUDE_OBJECT`) while the rest of the print finishes safely.
- **KAMP (Klipper Adaptive Meshing & Purging)**: Intercepts mesh calibration and line purging, restricting bed probing strictly to the sliced footprint. Dramatically cuts pre-flight calibration time and mechanical wear.
- **Sensor-Aware Pre-Flight PRINT_START & PRINT_END**: Fully parametric pre-flight sequencing supporting chamber heat-soak, dual-stage 150°C pre-heating, automatic brush wiping (`NOZZLE_WIPE`), and smart parking (`SMART_PARK`).
- **Automated Git Configuration Backup**: Tracks all changes in `/var/lib/moonraker/config/` automatically in git, with REST APIs for history, visual diffs, and one-click rollback.
- **Full Klipper Controls**: Mainsail-style toolhead jogging, temperature gauges, extrusion controls, emergency stop, and interactive G-code terminal with live `[QC]` feedback tagging.
- **Touch UI Mode**: Tailored for 5" and 7" Raspberry Pi touchscreen displays.
- **Rich Sensor Telemetry & Webhooks**: PZEM-004T AC power metering with Wh/cost reporting, Spoolman active spool tracking, and multi-channel rich Discord embeds & Telegram notifications with attached live webcam snapshots.
- **Visual QA Audit & Timelapse**: Automatically stitches timelapses, preserves keyframe thumbnails, stores a SHA-256 integrity hash of each video next to it, and references it (and keyframes) in the AS9100 Certificate of Conformance. The report is generated after the video link is saved.

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

Indus3D supports two official installation targets depending on your operating system:

### 1. Debian / Raspberry Pi OS / Ubuntu

#### Option A: KIAUH Extension (Recommended for standard Klipper setups)
```bash
git clone https://github.com/Krishnan328/Indus3D.git ~/indus3d
cd ~/indus3d
bash integrations/kiauh/install-extension.sh
```
Then run `./kiauh/kiauh.sh`, navigate to **`[E]xtensions`**, and choose **`Indus3D`** -> **`[1] Install`**.

> [!TIP]
> To install from an internal or development fork, prefix the command with:
> `INDUS3D_REPO_URL=https://github.com/your-fork/Indus3D.git ./install.sh`

#### Option B: Standalone Debian Installer
```bash
git clone https://github.com/Krishnan328/Indus3D.git ~/indus3d
cd ~/indus3d
./install.sh
```
Once installed, your dashboard is accessible at `http://<your-pi-ip>:5001`.
The installer builds the dashboard and Rust DSP before starting the service.
It requires Node.js 20.19+ or 22.12+ and a Cargo version that supports the
committed lockfile. If the distribution packages are too old, installation
stops with an error; install supported toolchains and retry. No Python DSP
fallback is provided. Updates refuse locally modified checkouts rather than
overwriting printer configuration.

### 2. NixOS (Declarative Flake & Module)
For NixOS hosts (such as `nixos-ks`), Indus3D provides a native Nix Flake and sandboxed systemd service module:

```nix
# In your host flake inputs:
inputs.indus3d.url = "github:Krishnan328/Indus3D";

# In your NixOS configuration modules:
modules = [
  indus3d.nixosModules.indus3d
  {
    services.indus3d = {
      enable = true;
      port = 5001;
      openFirewall = true;
      # Connect to an existing printer stack without modifying its configuration.
      klipperIntegration = false;
      moonrakerIntegration = false;
      moonrakerHost = "127.0.0.1";
      moonrakerPort = 7125;
    };
  }
];
```
Apply with:
```bash
sudo nixos-rebuild switch --flake .#nixos-ks
```
For complete details, see [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).

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
