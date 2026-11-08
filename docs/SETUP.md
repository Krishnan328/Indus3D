# Indus3D — Setup Guide

Complete guide for deploying Indus3D on a Raspberry Pi (or any Linux box) with
a Klipper/Moonraker 3D printer stack.

---

## Prerequisites

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **Hardware** | Raspberry Pi 4 (2 GB) | Raspberry Pi 5 (4 GB+) |
| **OS** | Raspberry Pi OS Lite (64-bit) | Raspberry Pi OS Lite (64-bit) |
| **Klipper** | Installed and running | Latest stable |
| **Moonraker** | Installed, API accessible on port 7125 | Latest stable |
| **Node.js** | 18.x | 20.x+ (for frontend build) |
| **Python** | 3.9+ | 3.11+ |
| **Git** | Any | Any |

> **Note:** Klipper and Moonraker should be installed and working before
> setting up Indus3D. Test that `curl http://localhost:7125/server/info`
> returns a valid JSON response.

---

## 1. Clone the Repository

```bash
cd ~
git clone <your-repo-url> indus3d
cd indus3d
```

---

## 2. Backend Setup

### Create a Python virtual environment

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

This installs Flask, flask-cors, flask-sock, requests, python-dotenv, and
pyserial. The dependency list is intentionally lean.

### Configure environment variables

```bash
cp .env.example .env
nano .env
```

At a minimum, set:

```env
# Moonraker URL — if Klipper runs on the same Pi, the default is correct
MOONRAKER_URL=http://localhost:7125

# Flask binding — 0.0.0.0 makes it accessible from other devices on the LAN
FLASK_HOST=0.0.0.0
FLASK_PORT=5001
```

**Optional but recommended:**

```env
# Authentication — set a password to require login
INDUS3D_PASSWORD=your_secret_password

# PZEM-004T power monitor (if wired)
# Find the by-id path:  ls /dev/serial/by-id/
PZEM_SERIAL_PORT=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0

# Notifications — Discord and/or Telegram
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

See `.env.example` for the full list of options with descriptions.

### Test the backend

```bash
# From inside the venv:
python main.py --sim
```

You should see:
```
🗄️  Database initialized.
⚠️  SIMULATION MODE — shape=benchy, layers=240
🧠 Indus3D [SIM/benchy] started
🔓 No INDUS3D_PASSWORD set — running without authentication
🟢 Indus3D API on http://0.0.0.0:5001
```

Press `Ctrl+C` to stop.

---

## 3. Frontend Setup

### Install Node.js dependencies

```bash
cd frontend
npm install
```

### Configure API endpoint

```bash
cp .env.example .env
nano .env
```

Set `VITE_API_PORT` to match your backend's `FLASK_PORT`:

```env
VITE_API_PORT=5001
```

### Build for production

```bash
npm run build
```

This creates `frontend/dist/` with the static files. The backend serves them
or they can be served by nginx (see below).

### Development mode (optional)

For live-reloading during development:

```bash
npm run dev
```

This starts a Vite dev server on port 5173 with hot module replacement.

---

## 4. Running in Production

### Option A: systemd service (recommended)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/indus3d.service
```

```ini
[Unit]
Description=Indus3D Digital Twin Dashboard
After=network.target moonraker.service
Wants=moonraker.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/indus3d/backend
ExecStart=/home/pi/indus3d/backend/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

> **Adjust paths** to match your installation. Replace `pi` with your
> username if different. The `WorkingDirectory` must point to the `backend/`
> directory.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable indus3d
sudo systemctl start indus3d
```

Check status:

```bash
sudo systemctl status indus3d
sudo journalctl -u indus3d -f    # live logs
```

### Option B: screen/tmux (simpler, not recommended for production)

```bash
cd backend
source .venv/bin/activate
screen -S indus3d python main.py
# Detach: Ctrl+A, D
# Reattach: screen -r indus3d
```

---

## 5. Nginx Reverse Proxy (optional but recommended)

Nginx provides a single port (80/443) for both the frontend and API, proper
WebSocket upgrade handling, and optional HTTPS.

```bash
sudo apt install nginx
sudo nano /etc/nginx/sites-available/indus3d
```

```nginx
server {
    listen 80;
    server_name _;

    # Frontend static files
    root /home/pi/indus3d/frontend/dist;
    index index.html;

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # WebSocket proxy
    location /ws {
        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Enable the site:

```bash
sudo ln -sf /etc/nginx/sites-available/indus3d /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Access the dashboard at `http://<pi-ip-address>/`.

---

## 6. Updating

```bash
cd ~/indus3d
git pull

# Backend
cd backend
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
npm run build

# Restart
sudo systemctl restart indus3d
```

The database migration system runs automatically on startup — any new
migrations are applied before the telemetry loop begins.

---

## 7. Troubleshooting

### Backend won't start

```bash
# Check what's using the port
sudo lsof -i :5001
sudo ss -ltnp | grep 5001

# Check Moonraker is reachable
curl http://localhost:7125/server/info

# Check logs
sudo journalctl -u indus3d -n 50
```

### Frontend build fails

```bash
# Check Node.js version (needs 18+)
node --version

# Clear and reinstall
rm -rf node_modules package-lock.json
npm install
npm run build
```

### WebSocket not connecting

- If using nginx, ensure the `/ws` proxy block is present and has
  `proxy_http_version 1.1` and `Upgrade` headers.
- If accessing directly (no nginx), ensure `FLASK_HOST=0.0.0.0` in `.env`
  and that port 5001 is not firewalled.

### PZEM-004T not reading

```bash
# List serial devices
ls -la /dev/serial/by-id/

# Check permissions (your user needs dialout group)
sudo usermod -aG dialout $USER
# Log out and back in for this to take effect

# Test with a simple read
python -c "import serial; s = serial.Serial('/dev/ttyUSB0', 9600, timeout=1); print(s.read(25).hex())"
```

### Authentication locked out

If you forget your password:
```bash
# Remove or clear INDUS3D_PASSWORD in .env
nano backend/.env
# Comment out or empty the line:
# INDUS3D_PASSWORD=

sudo systemctl restart indus3d
```

---

## 8. Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  Raspberry Pi                                                  │
│                                                                │
│  ┌─────────────┐    ┌───────────────┐    ┌─────────────────┐  │
│  │   Klipper    │◄──│   Moonraker   │◄──│  Indus3D Backend │  │
│  │  (firmware)  │   │  (port 7125)  │   │   (port 5001)    │  │
│  └─────────────┘    └───────────────┘    └────────┬────────┘  │
│                                                   │            │
│                                          WebSocket + REST      │
│                                                   │            │
│                                          ┌────────▼────────┐  │
│                                          │ Indus3D Frontend │  │
│                                          │  (React SPA)     │  │
│                                          └─────────────────┘  │
│                                                                │
│  Optional:                                                     │
│  ┌─────────────┐    ┌───────────────┐                         │
│  │  PZEM-004T  │──RS485──│ USB-FTDI │                         │
│  │  (AC power) │    │   adapter     │                         │
│  └─────────────┘    └───────────────┘                         │
└────────────────────────────────────────────────────────────────┘
```

**Data flow:** Moonraker → TelemetryWorker (10 Hz poll) → digital twin
models → quality controller → `self.latest` dict → Flask WebSocket →
frontend Zustand store → React render.

The frontend **never calls Moonraker directly** — all printer access goes
through the Flask API proxy routes (`/api/printer/*`).

---

## 9. File Structure

```
indus3d/
├── backend/
│   ├── main.py              # Entry point
│   ├── .env                 # Configuration (copy from .env.example)
│   ├── .env.example         # Documented config template
│   ├── requirements.txt     # Python dependencies
│   ├── api/
│   │   ├── server.py        # Flask app + WebSocket
│   │   ├── auth.py          # Authentication
│   │   └── routes/          # Blueprint routes
│   ├── config/
│   │   ├── settings.py      # Centralized config (reads .env)
│   │   ├── loader.py        # Profile/override loader
│   │   └── printer_profile.json
│   ├── core/
│   │   ├── quality_controller.py
│   │   ├── alert_actions.py
│   │   ├── notifications.py
│   │   ├── timelapse.py
│   │   └── shaper_tuner.py
│   ├── db/
│   │   ├── models.py        # SQLite schema
│   │   ├── migrator.py      # Migration runner
│   │   └── migrations/      # Numbered migration scripts
│   ├── digital_twin/
│   │   ├── kinematic_model.py
│   │   ├── thermal_model.py
│   │   ├── extrusion_model.py
│   │   └── snapshot_logger.py
│   ├── services/
│   │   ├── moonraker_client.py
│   │   └── pzem_monitor.py
│   └── workers/
│       ├── telemetry_worker.py
│       └── simulator.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Root component
│   │   ├── store.js         # Zustand state management
│   │   ├── theme.js         # Theme tokens
│   │   ├── LoginScreen.jsx  # Auth gate
│   │   └── ...              # Page/component files
│   ├── .env                 # VITE_API_PORT
│   └── package.json
├── docs/
│   ├── SETUP.md             # This file
│   └── DEVELOPMENT.md       # Feature documentation
└── CLAUDE_CONTEXT.md        # AI handoff document
```

---

## 10. Physics-Based Quality Control — Configuration

Indus3D v2.0 integrates six research-driven mathematical models into the real-time
quality-control loop. All models run as O(1) scalar arithmetic — safe for Raspberry Pi.
They are configured via `backend/config/indus_overrides.cfg` under `[indus3d]`.

> **Autopilot required:** Quality corrections (M104, M106, M220, Z-hop) are only
> emitted when **Autopilot mode** is enabled in the dashboard. Metrics are always
> computed and displayed regardless of autopilot state.

---

### 10.1 Sintering & Adhesion Healing (Group J — Papers 2.1.69–71)

**What it does:** Models inter-filament neck growth and molecular diffusion using
Costa's analytical bead cooling solution (lumped-capacitance) and a 5-point
Gauss-Legendre diffusion integral. The healing degree D_h indicates the fraction
of ultimate weld strength achieved before the bead freezes below T_g.

```
T(t) = (T_bead - T_inf) * exp(-beta*t) + T_inf
D_h  = [Integral_0^t_freeze 1/t_w(T(tau)) dtau]^(1/4)
t_w  = A * exp(Q_d / R*T(tau))
```

When `D_h < 0.95`, the fan is reduced by up to 30% to extend the above-T_g
healing window and improve layer adhesion.

**Dashboard metric:** `adhesion_score` (0–1, orange < 0.95, red < 0.70)

**`indus_overrides.cfg` parameters:**
```ini
# Glass transition temperature (°C): PLA=60, PETG=80, ABS=105, ASA=100
filament_t_glass_c            = 60.0

# Reptation activation energy (J/mol): PLA=220000, PETG=260000, ABS=388700
filament_q_diffusion_j_mol    = 220000.0

# Average layer time from slicer preview (seconds)
estimated_layer_time_s        = 30.0
```

---

### 10.2 Graetz Number Undercooling (Group K — Paper 2.1.26)

**What it does:** At high volumetric flow rates, thermal advection outpaces radial
conduction. The polymer core exits the nozzle cooler than the heater block setpoint.
Indus3D computes this deficit and adds a feedforward temperature boost (max +10 degC).

```
Gz = v_fil * d^2 / (4 * alpha * L)
DeltaT = k_Gz * ln(Gz)   for Gz > 1
T_cmd = T_nominal + min(10, DeltaT)
```

**Dashboard metric:** `undercooling_c` (degC, yellow > 5, orange > 10)

**`indus_overrides.cfg` parameters:**
```ini
# Heated melt zone length (mm): E3D V6=15.5, Volcano=22.0, Dragon=18.0
melt_length_mm                = 15.5

# Thermal diffusivity of molten filament (mm^2/s): PLA=0.085, PETG=0.10
thermal_diffusivity_mm2_s     = 0.085
```

---

### 10.3 Warpage Observer & Z-Hop Correction (Group L — Paper 2.1.28)

**What it does:** Reconstructs upward part warpage height from the ADXL345
Z-axis stress score using a compliance observer. Issues a Z-hop babystep
(`G91 G1 Z0.3 G90`) when warpage exceeds 0.35 mm.

```
F_z = S_Z * 20 N               (Z-stress score -> estimated force)
1/k_eq = 1/k_machine + 1/k_part
Delta_h = F_z / k_eq + h_layer
```

**Dashboard metric:** `warpage_mm` (mm, red if > 0.35 mm)

> No dedicated load cell required — uses ADXL Z-axis kurtosis/RMS from the Rust DSP
> pipeline as a hardware-free warpage proxy.

---

### 10.4 Non-Newtonian Backpressure & Nozzle Health (Groups I–H — Paper 2.1.27)

**What it does:** Computes true melt backpressure using Cross-Arrhenius shear-thinning
across three zones (barrel, conical transition, capillary). Predicted motor current
is compared to TMC telemetry to detect clogs and filament stripping.

```
K(T) = K0 * exp[Ea/R * (1/T - 1/T0)]    (Arrhenius viscosity)
I_pred = (DeltaP * A_fil + F_friction) * r_gear / (gear_ratio * K_t)
-> CLOG_WARNING      if I_meas/I_pred > 1.35
-> STRIPPING_WARNING if I_meas/I_pred < 0.60
```

**Dashboard metrics:** `nozzle_status` badge and `pressure` (kPa).

> TMC current telemetry requires `[tmc2209 extruder]` in `printer.cfg` with
> `sense_resistor` configured. Without it, predicted pressure is still computed
> and displayed but cannot be compared to a measured value.

---

### 10.5 Surface Roughness Minimization (Group N — Paper 2.1.15)

**What it does:** Predicts arithmetic Ra (um) from layer height and perimeter speed
using kinematic scallop geometry and an empirical response surface. Trims M220 speed
when Ra exceeds `target_ra_um`.

```
Ra = (h / 4*cos(theta)) * (1 + 0.008*(v-40)) * (1 - 0.005*(T-200))  [um]
v* = v_nominal / sqrt(Ra/Ra_target)   (optimal speed)
```

**Dashboard metric:** `ra_predicted_um` (um, orange > 12, red > 20)

**`indus_overrides.cfg` parameter:**
```ini
# Target surface roughness Ra (um): visual=12, engineering=8
target_ra_um                  = 12.0
```

---

### 10.6 Mass-Adaptive Input Shaping — TVIST (Group M — Paper 2.1.64)

**What it does:** Full TVIST (Time-Varying Input Shaping Theory) model — tracks
both resonance frequency shift **and viscoelastic damping ratio growth** as the
part mass accumulates. Supersedes the legacy `f ~ 1/sqrt(m)` formula.

```
zeta(t) = zeta_0 * (1 + k_zeta * m_part/m_bed)
f_n(t)  = f_0/sqrt(1-zeta_0^2) * sqrt(m_bed / (m_bed + m_part(t)))
f_d(t)  = f_n(t) * sqrt(1 - zeta(t)^2)
```

**Dashboard metric:** `zeta` (live structural damping ratio).

**`indus_overrides.cfg` parameters** (same as before):
```ini
y_resonance_hz  = 0.0    # From SHAPER_CALIBRATE — empty bed Y resonance
bed_mass_g      = 0.0    # Weigh bed assembly (kg -> g)
y_shaper_type   = mzv
```

---

### 10.7 Quality Dashboard Metrics Reference

| Metric | Unit | Description | Autopilot action |
|---|---|---|---|
| `flow_pct` | % | M221 flow override | Flow error -> M221 |
| `speed_pct` | % | M220 speed override | Lag or Ra -> M220 |
| `shaper_hz` | Hz | Live Y-axis shaper frequency | Mass -> SET_INPUT_SHAPER |
| `zeta` | — | Structural damping ratio (TVIST) | Informational only |
| `pa` | — | Pressure advance K factor | Flow -> SET_PRESSURE_ADVANCE |
| `temp` | degC | Active nozzle setpoint | Lag / Gz boost -> M104 |
| `fan` | 0–255 | Fan PWM | Cooling / sintering -> M106 |
| `pressure` | kPa | Predicted melt backpressure | High -> CLOG detection |
| `z_offset` | mm | Cumulative Z babystep total | Thermal / layer -> SET_GCODE_OFFSET |
| `accel` | mm/s^2 | Dynamic acceleration limit | Vibration -> SET_VELOCITY_LIMIT |
| `velocity` | mm/s | Dynamic velocity limit | Volumetric -> SET_VELOCITY_LIMIT |
| `scv` | mm/s | Square corner velocity | Vibration -> SET_VELOCITY_LIMIT |
| `retraction` | mm | Firmware retraction length | Temp/flow -> SET_RETRACTION |
| `adhesion_score` | 0–1 | Sintering healing degree D_h | D_h < 0.95 -> M106 trim |
| `undercooling_c` | degC | Graetz nozzle exit deficit | > 1 degC -> M104 boost |
| `warpage_mm` | mm | Part warpage height estimate | > 0.35 mm -> Z-hop |
| `nozzle_status` | string | NORMAL / CLOG / STRIPPING / DUAL_CLOG | CLOG / DUAL_CLOG -> PAUSE |
| `thermal_ratio` | — | Thermodynamic mass-flow ratio (Group O) | < 0.45 + TMC alarm -> PAUSE |
| `ra_predicted_um` | um | Predicted surface roughness Ra | > target -> M220 |

---

### 10.8 Thermodynamic PWM Clog Observer (Group O)

Estimates mass flow rate dynamically from heater block PWM duty cycle and nozzle temperature using a first-law energy balance:

$$\dot{Q}_{heater} - \dot{Q}_{loss} = \dot{m} \left( c_p \Delta T + \Delta h_{fusion} \right)$$

$$\dot{m}_{thermal} = \frac{\text{PWM} \cdot W_{heater} - h_{loss} (T_{nozzle} - T_{ambient})}{c_p (T_{nozzle} - T_{ambient}) + \Delta h_{fusion}}$$

When commanded volumetric flow is high but estimated thermal mass flow drops significantly ($\text{thermal\_ratio} = \dot{m}_{thermal} / \dot{m}_{cmd} < 0.45$), a clog is suspected. When both the thermodynamic observer and the TMC extruder motor back-EMF observer alarm simultaneously, `nozzle_status` escalates to `DUAL_CLOG_WARNING` and automatically pauses the print.

**`indus_overrides.cfg` parameters:**
```ini
heater_rated_w   = 40.0    # Nozzle heater cartridge wattage (W)
t_ambient_c      = 25.0    # Ambient / enclosure temperature (°C)
```

---

## 11. Multi-Tier Computer Vision & Defect Detection Architecture

Indus3D features an edge-decoupled, compute-budgeted vision pipeline structured across **4 hardware device tiers**. This guarantees metrology-grade defect detection without ever starving Klipper kinematics or overloading low-cost Raspberry Pi boards.

### Device-Tier Support Matrix

| Tier | Target Hardware | Compute Budget | Active Vision Modules | Detection Modality |
|---|---|---|---|---|
| **Tier 0** | Raspberry Pi 3 / Zero 2W / Budget SBC | < 2% CPU, < 25 MB RAM | • Thermodynamic PWM Observer<br>• OpenCV Hu Moment Contour Inspector | Energy balance + geometric shape moments |
| **Tier 1** | Raspberry Pi 4B (2GB–8GB) | ~15% single-core burst | • All Tier 0 modules<br>• Cambridge CAXTON (RAN-56 ONNX) | 4-head classifier (flow, speed, Z, temp) at layer change |
| **Tier 2** | Raspberry Pi 5 (4GB–8GB) | ~25% single-core | • All Tier 1 modules<br>• ProtoNet (ShuffleNetV2 few-shot) | Metric-learning visual anomaly detection (~15 FPS) |
| **Tier 3** | Desktop / Workstation / x86 Server | Full CPU/GPU acceleration | • All Tier 0–2 modules<br>• YOLOv8 real-time failure detector | 1–30 FPS bounding box detection (spaghetti, detachment) |

---

### Tier 0: Baseline Geometric Contour Matching (All Devices)
- **Engine**: OpenCV Gaussian adaptive thresholding + 7-element log-Hu moments.
- **Latency**: `< 5 ms` per frame.
- **Reference**: Compared against bundled `workers/data/benchy_contours.json` or custom reference sidecar.
- **Anomaly Score**: Normalised Mahalanobis distance squashed through sigmoid activation ($[0.0, 1.0]$).

### Tier 1: Cambridge CAXTON 4-Head Classifier (Raspberry Pi 4B+)
- **Architecture**: Residual Attention Network (RAN-56) with 4 task heads.
- **Inference Runtime**: CPU-only `onnxruntime` (~7 MB footprint, no PyTorch needed on printer).
- **Execution Strategy**: Triggered during `M400` toolhead parking at layer changes to avoid motion blur.
- **Corrective Actions**:
  - Head 0 (Extrusion State): Low $\rightarrow$ `M221 S+5%`, High $\rightarrow$ `M221 S-5%`
  - Head 1 (Speed State): Visual feedback for kinematic lag
  - Head 2 (Z-Offset State): Low $\rightarrow$ `SET_GCODE_OFFSET Z=+0.02`, High $\rightarrow$ `SET_GCODE_OFFSET Z=-0.02`
  - Head 3 (Temperature State): Low $\rightarrow$ `M104 S+5`, High $\rightarrow$ `M104 S-5`

### Tier 2: Few-Shot Prototypical Network (Raspberry Pi 5)
- **Backbone**: ShuffleNetV2-x0.5 with stripped classification head (1024-d embeddings).
- **Inference**: Euclidean distance in metric embedding space against support prototypes (`prototypes.npz`).
- **Advantage**: Requires only 5–10 "good" and "bad" reference images from user's printer to adapt to new filaments, lighting, or bed textures.

### Tier 3: Real-Time YOLOv8 Bounding-Box Detection (Desktop / Pi 5)
- **Model**: `3dai_best.pt` pre-trained cross-printer weights (YOLOv8s, 19 MB).
- **Classes**: Detects spaghetti failures, bed detachments, and severe layer shifts.
- **Reporting**: Dispatches alerts to `/api/v1/edge/inspection-alert` which triggers coordinated print pauses via Moonraker.

---

## 12. NixOS Deployment (Klipper Host Machine)

For deployment, secrets, backup/recovery, and the controlled-calibration
safety model, see [NixOS operations](NIXOS_OPERATIONS.md).

Indus3D provides a native NixOS module (`nix/modules/indus3d.nix`) modelled directly after the upstream [`nixpkgs/nixos/modules/services/misc/klipper.nix`](https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/services/misc/klipper.nix).

### Features of the Indus3D NixOS Module
- **Declarative & Reproducible**: Builds the Python backend, Rust DSP binary (`indus3d-dsp`), and native dependencies (`ffmpeg`, `opencv`) into isolated `/nix/store` paths.
- **Auto-Klipper Integration**: Automatically injects `[gcode_macro PAUSE_INDUS3D]` and `[gcode_macro CANCEL_INDUS3D]` into `services.klipper.settings`.
- **Auto-Moonraker Integration**: Configures Moonraker CORS domains and trusted clients so the Indus3D dashboard can interact with the printer without manual JSON edits.
- **Mutable vs Declarative Config**: Supports both pure NixOS declarative configuration (`services.indus3d.settings`) or mutable live editing (`services.indus3d.mutableConfig = true`).
- **Serial Port & Systemd Security**: Configured with `DynamicUser = true`, `SupplementaryGroups = [ "dialout" ]` for PZEM-004T / ADXL345 sensors, and automatic restart policies.

### Example Configuration (`/etc/nixos/configuration.nix`)

```nix
{ config, pkgs, ... }:

{
  imports = [
    # If using Flakes:
    # inputs.indus3d.nixosModules.default
    # Or importing directly from local clone:
    /path/to/Indus3D/nix/modules/indus3d.nix
  ];

  # 1. Klipper Service
  services.klipper = {
    enable = true;
    # settings = ...
  };

  # 2. Moonraker Service
  services.moonraker = {
    enable = true;
    address = "0.0.0.0";
    port = 7125;
  };

  # 3. Indus3D Digital Twin & Quality Controller
  services.indus3d = {
    enable = true;
    openFirewall = true; # Opens TCP port 5001 for web dashboard
    deviceTier = 1;      # 0: Pi 3, 1: Pi 4B, 2: Pi 5, 3: Desktop

    # Declarative overrides (generated via pkgs.formats.ini)
    settings = {
      indus3d = {
        layer_height_mm = 0.2;
        target_ra_um = 12.0;
        heater_rated_w = 40.0;
        t_ambient_c = 25.0;
      };
    };
  };
}
```

Rebuild your NixOS system:
```bash
sudo nixos-rebuild switch
systemctl status indus3d.service
```


