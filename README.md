# Indus3D: Real-Time Digital Twin & Closed-Loop Quality Controller

Indus3D is a next-generation real-time digital twin and closed-loop quality control platform for Klipper and Moonraker 3D printers.

> **Release Phase 6**: Bed Adaptation, OrcaSlicer Profile Import & REST API Architecture

---

## 🌟 Architecture Overview (Phase 1)

This foundation release establishes the core repository infrastructure, unified settings management, database schema migrations, and deployment automation:

- **Unified Configuration**: Centralized settings via `backend/config/settings.py` parsing environment variables with robust defaults.
- **Database Migrations Engine**: Built-in lightweight SQLite migration engine (`backend/db/migrator.py`) with versioned migrations (`001_baseline.py` through `009_config_history.py`).
- **Telemetry & Print Flight Records**: Structured SQLite flight logging schemas in `backend/db/models.py`.
- **Rotating File Logging**: Thread-safe rotating logging in `backend/core/logger.py` writing to `logs/indus3d.log`.
- **Worker Management**: Multi-threaded worker coordinator in `backend/workers/manager.py`.
- **Pruned Legacy Code**: Removed deprecated command queue and asynchronous IPC modules in favor of direct Moonraker communication.

---

## 🚀 Quickstart & Installation

### Prerequisites
- Python 3.9 or higher
- Klipper & Moonraker (for physical printer connection)

### Automated Install (Raspberry Pi / Linux)
```bash
git clone https://github.com/Krishnan328/indus3d.git
cd indus3d
./install.sh
```

### Manual Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Applying Database Migrations
To initialize or upgrade the SQLite flight record database:
```bash
cd backend
python -m db.migrator
```

---

## 🔐 Security & Access Control (Phase 2)

Indus3D provides security middleware to protect the printer control plane against unauthorized network access and abusive request flooding:

### 1. Token-Based Session Authentication (`api/auth.py`)
- Set `INDUS3D_PASSWORD` in `backend/.env` to require authentication.
- When configured, clients must exchange the password for a session token via `POST /api/v1/auth/login`.
- Authenticated requests must pass the header:
  ```http
  Authorization: Bearer <session_token>
  ```
- Secure constant-time token comparison prevents timing attacks. If `INDUS3D_PASSWORD` is omitted, the server operates in open local development mode.

### 2. Sliding-Window Rate Limiting (`api/rate_limiter.py`)
- **Login Throttling**: Limits authentication attempts to 5 per 60 seconds per IP to prevent brute-force attacks.
- **Hardware G-Code Throttling**: Restricts critical motion and temperature commands to 30 requests per minute per IP.
- **Automatic IP Ban**: Clients exceeding rate limits repeatedly receive a 15-minute temporary ban (`HTTP 429 Too Many Requests`).

### 3. Running Security Tests
```bash
pytest backend/tests/test_auth.py -v
```

---

## 📡 Extended Telemetry, Power & Alert Integrations (Phase 3)

Indus3D monitors workshop environment and electrical power parameters beyond standard Klipper thermals:

### 1. PZEM-004T AC Power Monitoring (`services/pzem_monitor.py`)
- Real-time voltage (V), current (A), active power (W), frequency (Hz), power factor (PF), and cumulative energy consumption (kWh) over Modbus RTU.
- Configurable serial port (`PZEM_PORT=/dev/ttyUSB0`) and baudrate (`PZEM_BAUD=9600`).

### 2. Spoolman Filament Integration (`services/spoolman_client.py`)
- Direct API integration with Spoolman server for active filament tracking, material spool weights, and remaining filament length warnings.

### 3. Flash Storage & Wear Monitor (`services/disk_monitor.py`)
- Tracks Raspberry Pi eMMC / SD card storage utilization and alerts when disk free space drops below critical thresholds.

### 4. Automated Print Timelapses (`core/timelapse.py`)
- High-resolution frame capture synchronized on layer change (`G-code Z-hop` or `M240`).
- Automated video rendering via `ffmpeg` on print completion.

### 5. Multi-Channel Webhook Notifications (`core/notifications.py`, `core/alert_actions.py`)
- Real-time print alerts and critical fault warnings dispatched to:
  - **Discord**: Rich embeds with print progress and sensor stats.
  - **Telegram**: Instant mobile push alerts with photo attachments.
  - **Pushover**: High-priority alert tones for thermal faults.

### 6. Running Telemetry & Alert Tests
```bash
pytest backend/tests/test_alert_actions.py -v
```

---

## 🦀 High-Speed Vibration DSP & Resonance Tuning (Phase 4)

Indus3D includes an ultra-low-latency accelerometer signal processing pipeline written in Rust and integrated with Python:

```
┌─────────────────────┐      UDP Stream      ┌─────────────────────┐
│  ADXL345 / LIS2DW   │ ───────────────────► │  Rust DSP Pipeline  │
│  Accelerometer Data │      (1600 Hz)       │  (backend/dsp/)     │
└─────────────────────┘                      └──────────┬──────────┘
                                                        │ UDP Metrics
                                                        ▼ (FFT/RMS/PSD)
┌─────────────────────┐  Harmonic Tracking   ┌─────────────────────┐
│ Klipper Shaper Tune │ ◄─────────────────── │  Python DSP Bridge  │
│ (core/shaper_tuner) │                      │ (dsp_bridge.py)     │
└─────────────────────┘                      └─────────────────────┘
```

### 1. Rust DSP Accelerometer Pipeline (`backend/dsp/`)
- Computes real-time Fast Fourier Transforms (FFT), Power Spectral Density (PSD), RMS acceleration, and dominant resonance peaks at up to 3200 Hz.
- Emits compact binary vibration metrics over local UDP socket.

### 2. Building the Rust DSP Pipeline
```bash
cd backend/dsp
cargo build --release
```
The compiled binary runs automatically as a managed child process under `backend/workers/dsp_bridge.py`.

### 3. Vibration Monitor & Input Shaper Tuner (`core/shaper_tuner.py`)
- **Vibration Monitor**: Tracks mechanical harmonics, belt looseness, and frame resonance shifts during printing.
- **Input Shaper Tuner**: Recommends optimal Klipper shaper algorithms (`zv`, `mzv`, `ei`, `2hump_ei`) and shaper damping ratios based on measured frequency response.

---

## 🧠 Physics-Based Digital Twin & Closed-Loop Autopilot (Phase 5)

Indus3D runs a multi-physics mathematical digital twin that predicts print conditions in real time and applies closed-loop G-code interventions:

### 1. Mathematical Physics Models (`digital_twin/control_models.py`)
- **Kinematic Positional Lag**: Tracks instantaneous deviation between commanded G-code waypoints and live physical stepper positions, calculating finite-difference velocity and acceleration.
- **Thermal Lag Observer**: First-order lumped thermal resistance model predicting core melt-zone temperature vs heater block temperature.
- **Extrusion Dynamics**: Computes true volumetric flow rate ($Q = v \cdot w \cdot h\text{ mm}^3/s$) and stadium bead geometry to detect under/over-extrusion before surface defects form.
- **Stepper Motor & Acoustic Models**: Calculates electromagnetic motor torque ($\tau$) and estimates side-channel sound pressure level ($dB$) to detect belt slippage and mechanical binding.
- **Polymer Rheology Profiles**: Non-Newtonian shear-thinning and thermal properties for PLA, PETG, ABS, and TPU (`digital_twin/filament_profiles.py`).

### 2. Autopilot Quality Controller (`digital_twin/quality_controller.py`)
When Autopilot is enabled, Indus3D emits real-time closed-loop compensations via Moonraker:
- **Adaptive Flow (`M221`)**: Trims extrusion multiplier (85%–115%) to maintain uniform bead cross-section.
- **Speed Lag Throttle (`M220`)**: Scales print speed down during high-acceleration moves or mechanical resistance, recovering smoothly once lag clears.
- **Dynamic Pressure Advance**: Continuously adjusts `SET_PRESSURE_ADVANCE` based on instantaneous volumetric flow rate.
- **Anti-Windup Temperature Clamp**: Clamps dynamic temperature trims strictly within $\pm 2\text{ °C}$ (maximum $+12\text{ °C}$ over base temperature) to eliminate thermal runaway hazards.

### 3. QA Audit Reporter & Digital Twin Simulator
- **QA Reporter (`services/qa_reporter.py`)**: Automatically compiles print telemetry into structured PDF/JSON quality assurance certificates.
- **Simulator Mode**: Run standalone physics simulations with baked 3DBenchy geometry:
  ```bash
  python main.py --sim --shape benchy --layers 40
  ```

### 4. Running Physics & Quality Tests
```bash
pytest backend/tests/test_quality_controller.py backend/tests/test_extrusion_model.py backend/tests/test_thermal_model.py -v
```

---

## 🛡️ Bed Adaptation, Slicer Integration & REST API (Phase 6)

Indus3D features an intelligent bed safety engine to prevent toolhead collisions with bed hardware and provides a comprehensive REST & WebSocket API:

### 1. Bed Safety & Slicer Profile Import (`api/routes/bed.py`)
- **Direct OrcaSlicer / PrusaSlicer Import**: Parses printer `.json` configuration files, extracting `printable_area` vertices, `bed_origin`, and `bed_exclude_area` polygons.
- **Hardware Exclusion Zones**: Define keep-out zones for bed leveling screws, glass clips, wipe buckets, and purge lines.
- **Custom 3D Bed Meshes**: Upload and serve custom STL build plates (`/api/v1/bed/stl`) for accurate 3D visualization.
- **Collision Guardrails**: Prohibits toolhead downward movement over exclusion zones below clearance altitude ($Z < 10\text{ mm}$), clamping dynamic leveling offsets within `[-0.25mm, +0.50mm]`.

### 2. REST API & WebSocket Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/printer/status` | Current printer status, temperatures, position, and job state |
| `POST` | `/api/v1/printer/gcode` | Execute G-code command (rate-limited and sanitized) |
| `POST` | `/api/v1/printer/emergency_stop` | Trigger immediate Klipper `M112` emergency stop |
| `GET` | `/api/v1/bed/profile` | Current bed dimensions, origin, and exclusion zones |
| `POST` | `/api/v1/bed/import-orca` | Import OrcaSlicer/PrusaSlicer JSON profile |
| `POST` | `/api/v1/bed/exclusion-zones` | Add or update hardware exclusion zones |
| `GET` | `/api/v1/twin/status` | Live digital twin metrics (flow, lag, thermal, vibration) |
| `POST` | `/api/v1/twin/autopilot/toggle` | Enable or disable closed-loop Autopilot controller |
| `GET` | `/api/v1/spools/active` | Active filament spool information from Spoolman |
| `WS` | `/ws/twin` | 10 Hz real-time binary/JSON telemetry broadcast |

### 3. Running Bed Safety Tests
```bash
pytest backend/tests/test_bed_safety.py -v
```

---

## ⚙️ Configuration

Copy `backend/.env.example` to `backend/.env`:
```ini
MOONRAKER_HOST=127.0.0.1
MOONRAKER_PORT=7125
FLASK_HOST=0.0.0.0
FLASK_PORT=5001
TWIN_TICK_HZ=10
```

### Klipper Integration
Include the Indus3D configuration overrides in your `printer.cfg`:
```ini
[include indus3d.cfg]
```

---

## 🧪 Testing

Run backend tests using pytest:
```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for details.
