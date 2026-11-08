# Indus3D ESP8266 Multi-Sensor Hub
### Bed Collision Monitor + Automated Input Shaping + Chamber Telemetry

A production-grade embedded firmware, Klipper macro suite, and host Python analysis engine running on an **ESP8266** (NodeMCU / Wemos D1 Mini) mounted directly near the 3D printer's Y-carriage / bed frame.

The hub eliminates long-wire inductive noise by digitizing sensor data directly at the carriage, transmitting telemetry over **Wi-Fi** (with transparent **USB Serial fallback**).

---

## System Architecture

```text
  +-------------------------------------------------------------------------+
  |                             3D PRINTER BED                              |
  |  +------------------------+             +----------------------------+  |
  |  | ADXL345 Accelerometer  |             |      BME280 Sensor         |  |
  |  | (Hardware SPI - HSPI)  |             |  (I2C - SDA: D2, SCL: D1)  |  |
  |  +-----------+------------+             +--------------+-------------+  |
  |              | 5 MHz SPI                               | 100 kHz I2C    |
  |              v                                         v                |
  |  +-------------------------------------------------------------------+  |
  |  |                   ESP8266 MULTI-SENSOR HUB                        |  |
  |  |  * Mode A: 200 Hz Bed Crash & Instantaneous Jerk Monitoring       |  |
  |  |  * Mode A: 0.5 Hz Chamber Temp, Humidity & Pressure Sampling      |  |
  |  |  * Mode B: 1600 Hz / 3200 Hz High-Speed Resonance Streaming       |  |
  |  |  * REST API Web Server (Port 80) + TCP Binary Stream (Port 8266)  |  |
  |  +-------------------+-----------------------------+-----------------+  |
  +----------------------|-----------------------------|--------------------+
                         | Wi-Fi (HTTP / TCP)          | USB Serial (115200)
                         v                             v
  +-------------------------------------------------------------------------+
  |                        HOST (Raspberry Pi / Laptop)                     |
  |  +--------------------+   +-------------------+   +------------------+  |
  |  | Moonraker HTTP API |   | Klipper Firmware  |   | Python Analyzer  |  |
  |  | (/printer/print/   |-->| (BED_CRASH_       |   | (PSD, Shaper     |  |
  |  |  pause)            |   |  HANDLER macro)   |   |  Math, Plots)    |  |
  |  +--------------------+   +-------------------+   +------------------+  |
  +-------------------------------------------------------------------------+
```

---

## Key Features

1. **Deterministic 200 Hz Bed Crash & Jerk Detection (Mode A)**:
   - Polls ADXL345 at 200 Hz over 5 MHz Hardware SPI.
   - Computes instantaneous jerk delta:
     $$\Delta a = \sqrt{(x_t - x_{t-1})^2 + (y_t - y_{t-1})^2 + (z_t - z_{t-1})^2}$$
   - Latches `BED_CRASH_DETECTED` if $|\Delta a| > 2000\text{ mg}$ (configurable).
   - Automatically issues emergency pause to Moonraker (`POST /printer/print/pause`) and USB Serial (`// action:paused` and `PAUSE`).

2. **Chamber Environmental Telemetry (0.5 Hz / Every 2 Seconds)**:
   - Samples Bosch BME280 for Temperature (°C), Relative Humidity (%), and Barometric Pressure (hPa).
   - Exposes REST endpoint (`GET /telemetry`) and dedicated Klipper endpoint (`GET /chamber`).

3. **Automated Input Shaping & Resonance Calibration (Mode B)**:
   - Shifts ADXL345 to 1600 Hz (or 3200 Hz) for high-frequency vibration recording.
   - Streams 15-byte binary frames with monotonic sequence numbering and XOR checksums over TCP port 8266.
   - `esp_shaper_analyzer.py` calculates Welch Power Spectral Density (PSD), models all 6 Klipper shapers (**ZV, MZV, ZVD, EI, 2HUMP_EI, 3HUMP_EI**), computes vibration reduction percentages, recommends optimal shaper frequency and max acceleration, and renders publication-grade Matplotlib plots.

4. **Transparent USB Serial Fallback**:
   - If Wi-Fi is disconnected or unavailable, the hub continues 200 Hz crash monitoring and outputs crash alerts and telemetry directly over USB Serial at 115200 baud.
   - Full serial CLI (`HELP`, `TELEMETRY`, `CHAMBER`, `STATUS`, `RESET_CRASH`, `SET_THRESHOLD <mg>`, `START_SHAPER`).

---

## Directory Structure

```text
esp8266_sensor_hub/
├── README.md                      # Project documentation and quickstart
├── docs/
│   ├── WIRING_AND_PINOUT.md       # Pinout tables, schematics, boot-strap constraints
│   └── DEPLOYMENT_GUIDE.md        # Compilation, flashing, and Klipper setup guide
├── firmware/
│   ├── platformio.ini             # PlatformIO build configuration for d1_mini / nodemcu
│   ├── include/
│   │   ├── config.h               # Pin assignments, defaults, EEPROM layout
│   │   ├── adxl345_spi.h          # ADXL345 HSPI hardware driver
│   │   ├── bme280_i2c.h           # Bosch BME280 I2C sensor driver
│   │   ├── crash_detector.h       # 3-axis jerk computation and collision latch
│   │   ├── shaper_streamer.h      # High-speed binary TCP streaming engine (1600 Hz)
│   │   ├── moonraker_client.h     # Moonraker HTTP pause and G-code client
│   │   ├── network_manager.h      # Wi-Fi Station, SoftAP fallback, mDNS
│   │   └── web_server.h           # REST API endpoints (/telemetry, /chamber, etc.)
│   └── src/
│       ├── main.cpp               # 200 Hz loop, Mode state machine, Serial CLI
│       ├── adxl345_spi.cpp
│       ├── bme280_i2c.cpp
│       ├── crash_detector.cpp
│       ├── shaper_streamer.cpp
│       ├── moonraker_client.cpp
│       ├── network_manager.cpp
│       └── web_server.cpp
├── klipper/
│   ├── bed_sensor_hub.cfg         # Klipper macros: BED_CRASH_HANDLER, BED_SHAPER_CALIBRATE
│   └── moonraker_bed_hub.conf     # Moonraker trusted clients & sensor configuration
├── scripts/
│   ├── esp_shaper_analyzer.py     # Input Shaper PSD analysis, filter modeling & plotting
│   ├── esp_bed_monitor_daemon.py  # Real-time console monitor & CSV telemetry logger
│   ├── test_shaper_math.py        # Automated unit test suite (checksum, jerk, PSD, filters)
│   └── mock_esp8266_server.py     # Mock HTTP & TCP server for offline verification
└── output/
    ├── resonances_bed_y.csv       # Klipper-format resonance test CSV
    ├── bed_input_shaper_y.cfg     # Generated Klipper [input_shaper] configuration
    └── shaper_calibration_bed_y.png # 4-panel publication-grade resonance plot
```

---

## Quickstart

### 1. Build and Flash Firmware
```bash
cd firmware
pio run --target upload
```

### 2. Run Resonance Calibration (Input Shaping)
```bash
# Capture 7 seconds @ 1600 Hz from ESP8266 and compute optimal shaper
python3 scripts/esp_shaper_analyzer.py --ip 192.168.1.150 --duration 7 --outdir output
```

### 3. Run Real-Time Telemetry Monitor
```bash
python3 scripts/esp_bed_monitor_daemon.py --ip 192.168.1.150 --log chamber_telemetry.csv
```

---

## REST API Reference

| Endpoint | Method | Description | Example Response |
|---|---|---|---|
| `/telemetry` | `GET` | Instantaneous bed acceleration, jerk, and chamber telemetry | `{"bed_accel":{"x_mg":145,"y_mg":-12,"z_mg":-980,"jerk_mg":18},"chamber":{"temp_c":26.4,"humidity_pct":43.1,"pressure_hpa":1012.8},"crash_detected":false,"uptime_sec":1420}` |
| `/chamber` | `GET` | Dedicated temperature/humidity endpoint for Klipper | `{"temperature":26.4,"humidity":43.1,"pressure":1012.8}` |
| `/status` | `GET` | Diagnostics, RSSI, ADXL/BME online status, free heap | `{"device":"ESP8266-BedHub","version":"1.0.0","adxl345_online":true,...}` |
| `/reset_crash`| `POST`| Clears latched collision state | `{"status":"ok","message":"Crash latch cleared"}` |
| `/config` | `POST`| Dynamically update jerk threshold or Moonraker IP | `{"threshold_mg": 2200}` |
| `/shaper/start`| `POST`| Initiates high-speed 1600 Hz sampling session | `{"status":"started","duration_s":5,"tcp_stream_port":8266}` |
| `/shaper/status`| `GET`| High-speed stream progress and sample count | `{"running":false,"samples_recorded":8000,"rate_hz":1600}` |
