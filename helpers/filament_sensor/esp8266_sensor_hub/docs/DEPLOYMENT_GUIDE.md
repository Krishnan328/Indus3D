# Deployment & Setup Guide
## Indus3D ESP8266 Multi-Sensor Hub (Bed Collision Monitor + Input Shaping + Chamber Telemetry)

The hub is pre-configured to run **100% over USB Serial** out of the box (zero Wi-Fi delay, instant boot, and plug-and-play operation with your Raspberry Pi / Klipper host or laptop). Wi-Fi can easily be re-enabled whenever needed by setting `#define ENABLE_WIFI true` in `config.h`.

---

## 1. Fast USB Quickstart (Recommended)

### Step 1: Plug in the ESP8266 via USB
Connect the ESP8266 to your computer or Raspberry Pi with a USB data cable.

### Step 2: Flash Firmware
```bash
cd /Users/krishnanh/Projects/filasens/esp8266_sensor_hub/firmware
pio run --target upload
```

### Step 3: Verify Serial Initialization
Open the serial monitor at 115200 baud:
```bash
pio device monitor -b 115200
```
Upon boot, you will immediately see:
```text
=====================================================
 Indus3D ESP8266 Multi-Sensor Hub v1.0.0
 Bed Collision Monitor + Input Shaping + Chamber
=====================================================
[HW] Initializing ADXL345 on HSPI (CS=D8/GPIO15)... OK! (DEVID: 0xE5, Range: +-16g, 200 Hz)
[HW] Initializing BME280 on I2C (SDA=D2, SCL=D1)... OK! (Addr: 0x76, Type: BME280)
[CRASH] Detection threshold: 2000 mg (2.0 g delta)
[SYSTEM] Running in PURE USB SERIAL MODE (Wi-Fi disabled).
[SYSTEM] Instant boot: 200 Hz crash monitor + 1 Hz JSON telemetry over USB.
```
And every 1 second, it outputs live JSON telemetry:
```json
{"bed_accel":{"x_mg":145,"y_mg":-12,"z_mg":-980,"jerk_mg":18},"chamber":{"temp_c":26.4,"humidity_pct":43.1,"pressure_hpa":1012.8},"crash_detected":false,"uptime_sec":1}
```

### Step 4: Run Real-Time Telemetry Dashboard
```bash
python3 scripts/esp_bed_monitor_daemon.py
```
*(Auto-detects the USB serial port and displays live terminal metrics & logs to `chamber_telemetry.csv`)*

### Step 5: Run Automated Input Shaper Calibration over USB
```bash
python3 scripts/esp_shaper_analyzer.py --duration 7 --rate 1600
```
*(Sends `START_SHAPER 7 1600` over USB serial, streams high-frequency frames, computes Welch PSD, calculates optimal shapers, and generates the comparison plot!)*

---

## 1. Prerequisites & Toolchain Setup

### Option A: Using PlatformIO (Recommended)
PlatformIO handles toolchain downloads, libraries, and compilation automatically.

```bash
# Clone or navigate to the firmware repository
cd /path/to/filasens/esp8266_sensor_hub/firmware

# Build firmware
pio run

# Connect ESP8266 via USB and upload
pio run --target upload

# Open serial monitor (115200 baud)
pio device monitor -b 115200
```

### Option B: Using Arduino IDE
1. Open Arduino IDE -> Preferences -> **Additional Board Manager URLs**:
   `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
2. Install **esp8266 by ESP8266 Community** from Boards Manager.
3. Install **ArduinoJson by Benoît Blanchon (version 6.x or 7.x)** from Library Manager.
4. Select Board: **LOLIN(WEMOS) D1 R2 & mini** or **NodeMCU 1.0 (ESP-12E Module)**.
5. CPU Frequency: **80 MHz** (or 160 MHz for maximum streaming headroom).
6. Flash Size: **4MB (FS:2MB OTA:~1019KB)**.
7. Open `firmware/src/main.cpp` and click **Upload**.

---

## 2. Network & Moonraker Configuration

### 2.1 Default Credentials & SoftAP Mode
1. Edit `firmware/include/config.h` before flashing:
   ```cpp
   #define DEFAULT_WIFI_SSID    "Your_WiFi_Name"
   #define DEFAULT_WIFI_PASS    "Your_WiFi_Password"
   #define DEFAULT_MOONRAKER_IP "192.168.1.100"  // IP of your Raspberry Pi / Klipper host
   #define DEFAULT_MOONRAKER_PORT 7125
   ```
2. If Wi-Fi fails to connect within 8 seconds, the ESP8266 will automatically activate **SoftAP Mode**:
   - **SSID**: `ESP8266-BedHub-AP`
   - **Password**: `bedhub1234`
   - **IP Address**: `192.168.4.1`
3. The hub also registers mDNS at: `http://esp8266-bedhub.local`.

### 2.2 Moonraker Authorization Setup
For the ESP8266 to pause the print on collision without requiring an API token, its IP address must be trusted by Moonraker.

Open `moonraker.conf` on your Raspberry Pi:
```ini
[authorization]
trusted_clients:
    10.0.0.0/8
    127.0.0.0/8
    169.254.0.0/16
    172.16.0.0/12
    192.168.0.0/16
    # Add your local network subnet or specific ESP8266 IP here
```
Restart Moonraker: `sudo systemctl restart moonraker`.

---

## 3. Klipper Macro Installation

1. Copy `klipper/bed_sensor_hub.cfg` into your Klipper configuration directory:
   ```bash
   cp /path/to/esp8266_sensor_hub/klipper/bed_sensor_hub.cfg ~/printer_data/config/
   ```
2. In your `printer.cfg`, add:
   ```ini
   [include bed_sensor_hub.cfg]
   ```
3. Update the global variables in `bed_sensor_hub.cfg` to match your printer:
   ```ini
   [gcode_macro _BED_HUB_VARS]
   variable_esp_ip: "192.168.1.150"     # IP of your ESP8266
   variable_park_x: 10.0                # Safe X parking position
   variable_park_y: 220.0               # Safe Y parking position (away from print)
   variable_zhop: 10.0                  # Lift nozzle 10mm on collision
   ```
4. Restart Klipper: `RESTART`.

---

## 4. Bed Collision Monitor Operation (Mode A)

In Mode A, the ESP8266 executes a deterministic **200 Hz sampling loop** evaluating instantaneous 3-axis jerk:
$$\Delta a = \sqrt{(x_t - x_{t-1})^2 + (y_t - y_{t-1})^2 + (z_t - z_{t-1})^2}$$

### Crash Event Sequence:
1. When $|\Delta a| > 2000\text{ mg}$ (configurable):
   - Firmware latches `crash_detected = true`.
   - Sends HTTP POST `http://<moonraker_ip>:7125/printer/print/pause`.
   - Emits G-code emergency command over USB Serial: `// action:paused` and `PAUSE`.
   - Status LED flashes a rapid double-strobe.
2. Klipper executes `BED_CRASH_HANDLER`:
   - Lifts Z by 10mm.
   - Retracts 2mm filament.
   - Parks toolhead at safe corner (X=10, Y=220).
   - Shuts off nozzle heater (prevents filament degradation).
   - Sounds audible alarm beeps.
3. Resuming Print:
   - Inspect bed and clear physical obstruction.
   - Click `BED_CRASH_RESUME` in Fluidd/Mainsail or issue `BED_CRASH_RESUME` in console.
   - Automatically unlatches ESP8266 crash state, reheats nozzle, primes, and resumes.

### Tuning the Jerk Threshold:
- Normal printing accelerations and direction reversals typically produce jerk deltas between **250 mg and 700 mg**.
- The default threshold is **2000 mg (2.0g delta in 5 ms)**, which cleanly differentiates between aggressive infill direction changes and a physical nozzle/bed collision or detached print jam.
- Adjust threshold dynamically without reflashing:
  ```bash
  # Via HTTP REST API
  curl -X POST http://192.168.1.150/config -d '{"threshold_mg": 2200}'

  # Via Serial CLI
  SET_THRESHOLD 2200
  ```

---

## 5. Automated Input Shaping Calibration (Mode B)

### Procedure:
1. Ensure your printer is homed (`G28`).
2. Run the Python analysis tool from your laptop or Raspberry Pi:
   ```bash
   python3 scripts/esp_shaper_analyzer.py --ip 192.168.1.150 --duration 7 --rate 1600
   ```
3. Simultaneously trigger the Klipper frequency sweep in Fluidd/Mainsail:
   ```gcode
   BED_SHAPER_CALIBRATE DURATION=7
   ```
4. The analyzer captures 11,200 samples over high-speed TCP socket, computes Power Spectral Density (PSD), evaluates ZV, MZV, ZVD, EI, 2HUMP_EI, 3HUMP_EI shaper transfer functions, and outputs:
   - A tabular comparison report with vibration reduction percentages.
   - A 4-panel publication-quality Matplotlib chart: `shaper_calibration_bed_y.png`.
   - A ready-to-paste Klipper config snippet: `bed_input_shaper_y.cfg`.
5. Paste the recommended shaper settings into your `printer.cfg`:
   ```ini
   [input_shaper]
   shaper_type_y = mzv
   shaper_freq_y = 48.1
   ```

---

## 6. Real-Time Chamber Telemetry Monitoring

To continuously view real-time bed vibrations and chamber temperature/humidity/pressure:
```bash
python3 scripts/esp_bed_monitor_daemon.py --ip 192.168.1.150 --log chamber_log.csv
```

---

## 7. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `[HW] Initializing ADXL345 FAILED!` | Wiring loose or incorrect CS pin | Verify HSPI wiring: D5(SCK), D6(MISO), D7(MOSI), D8(CS). Ensure ribbon cable is <= 3 inches. |
| ESP8266 will not boot / enters flash mode | D8 (GPIO15) pulled HIGH externally | Remove any external pull-up on D8. GPIO15 must be LOW during boot. |
| `[HW] Initializing BME280 FAILED!` | Wrong I2C pins or address | Verify SDA is D2 (GPIO4) and SCL is D1 (GPIO5). Check address (0x76 vs 0x77). |
| Moonraker pause not executing on collision | Subnet not in `trusted_clients` | Add ESP8266 IP or subnet (`192.168.0.0/16`) to `trusted_clients` in `moonraker.conf`. |
| High packet drops during input shaping | Wi-Fi interference | Ensure strong RSSI (>-70 dBm) or use transparent USB Serial fallback. |
