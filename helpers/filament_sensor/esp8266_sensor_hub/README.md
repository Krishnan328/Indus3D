# Indus3D ESP8266 bed sensor hub
### Bed crash detection, Y input shaping and chamber telemetry over USB

An ESP8266 (NodeMCU) on the printer's Y carriage reads an **ADXL345** (bed acceleration, 3.9 mg/LSB, SPI) and a
**BME280** (chamber temperature, humidity, pressure, I2C) and talks to the printer's host over **USB serial**.
A host daemon owns the serial port and connects the hub to Klipper, Moonraker and Indus3D.

```text
  ADXL345 (HSPI, CS = GPIO16)   BME280 (I2C, SDA = GPIO0, SCL = GPIO2, 0x76)
              \                  /
               ESP8266 firmware v1.1.0  -- 200 Hz jerk monitor, 1 Hz JSON, 1600 Hz capture on request
                       | USB serial (115200; faster only during a capture)
                       v
   esp_bed_monitor_daemon.py   systemd: esp8266_bed_hub.service    /dev/esp8266_bed_hub (udev)
     |  HTTP 127.0.0.1:7127          reconnects by itself, never resets the ESP, CSV log
     |-- crash while printing --> Moonraker /printer/print/pause --> BED_CRASH_HANDLER JERK=<mg>
     |-- MQTT (optional) ---------> Moonraker [sensor] ------------> Fluidd / Mainsail sensor card
     |-- esp_hub_ctl.py <-- Klipper gcode_shell_command <-- macros (reset latch, status, threshold, shaper)
     `-- Indus3D plugin esp_bed_hub --> SQLite telemetry_samples, dashboard card, /metrics, command hold
```

## What it does

1. **Crash detection.** The ESP samples the ADXL345 at 200 Hz; a 3-axis jerk above the threshold (default 2000 mg,
   500-8000, changeable at run time) latches and sends an alert line immediately. The daemon pauses the print through
   Moonraker and runs `BED_CRASH_HANDLER` (retract, Z-hop bounded by the axis maximum, park, hotend off, bed stays on,
   beeps). `BED_CRASH_RESUME` reheats to the saved targets, re-primes, clears the latch and resumes. A crash while no
   print is running is logged and the latch is cleared; the handler never moves an idle printer.
2. **Chamber telemetry.** One JSON line per second; a missing BME280 is reported as `null`, never as 0.
3. **Y input shaping.** `BED_SHAPER_CALIBRATE_Y` sweeps the bed 5-120 Hz while the hub streams 15-byte checksummed
   frames at up to 1600 Hz; the analyzer estimates the resonance and damping, evaluates ZV/MZV/ZVD/EI/2HUMP_EI/3HUMP_EI,
   derives the maximum acceleration from the smoothing limit, writes a plot and a config snippet, and can update
   `[input_shaper]` in `printer.cfg` (backup first).
4. **Indus3D.** Samples go into the SQLite table `telemetry_samples`; chamber values feed `/api/v1/environment`; a crash
   raises a notification and holds corrective commands until the latch is cleared; a dashboard card shows it all.

## Install

Flash the firmware (`cd firmware && pio run --target upload`), then run `./install_hub.py` on the host and follow
**docs/DEPLOYMENT_GUIDE.md** (udev rule, systemd unit, Klipper and Moonraker includes, the end-to-end crash test).

## Layout

```text
esp8266_sensor_hub/
├── install_hub.py                   installer / uninstaller (udev, systemd, Klipper + Moonraker includes)
├── esp8266_bed_hub.service.in       systemd unit template
├── docs/
│   ├── DEPLOYMENT_GUIDE.md          setup, daily use, crash and shaper procedures, troubleshooting
│   └── WIRING_AND_PINOUT.md         pins, boot-strap notes, cable guidance
├── firmware/                        PlatformIO project (v1.1.0)
│   ├── include/serial_protocol.h    command parser, baud/rate selection (host-testable, no Arduino deps)
│   ├── src/main.cpp                 200 Hz loop, serial commands, 1 Hz telemetry, crash alert
│   ├── src/crash_detector.cpp       jerk latch with peak tracking
│   ├── src/shaper_streamer.cpp      binary capture sessions (baud switch for the session)
│   └── test/run.sh                  host-side logic tests with Arduino stubs
├── klipper/
│   ├── bed_sensor_hub.cfg           macros: _BED_HUB_VARS, BED_CRASH_HANDLER, BED_CRASH_RESUME, BED_HUB_STATUS,
│   │                                BED_HUB_RESET_CRASH, SET_BED_CRASH_THRESHOLD, BED_SHAPER_CALIBRATE_Y
│   ├── bed_sensor_hub_shell.cfg.in  gcode_shell_command entries (rendered by the installer)
│   └── moonraker_bed_hub.conf       [mqtt] + [sensor bed_hub]
├── scripts/
│   ├── esp_bed_monitor_daemon.py    the host daemon (HTTP API, crash handling, captures, CSV, MQTT feed)
│   ├── esp_hub_ctl.py               command line used by the macros: status, reset-crash, set-threshold, shaper-capture
│   ├── esp_shaper_analyzer.py       PSD, damping, shaper fits, smoothing, plot, printer.cfg updater
│   ├── hub_protocol.py              wire format shared by daemon, CLI and analyzer
│   ├── mqtt_publish.py              minimal MQTT publisher (stdlib)
│   ├── test_shaper_math.py          analyzer tests
│   └── mock_esp8266_server.py       mock for the optional Wi-Fi mode (HTTP + TCP)
└── tests/                           daemon (software model of the hub), macros (Jinja against a mock printer),
                                     MQTT, installer
```

## Daemon HTTP API (127.0.0.1:7127; POSTs need the header `X-Indus3D-Action: 1`)

| Endpoint | Method | Purpose |
|---|---|---|
| `/telemetry` (`/status`) | GET | latest hub state, `connected`, `age_s`, daemon info incl. `last_crash` |
| `/chamber` | GET | chamber values only |
| `/health` | GET | `{"ok", "connected", "age_s"}` |
| `/shaper/last` | GET | metadata of the last capture |
| `/reset_crash` | POST | clear the hub's crash latch |
| `/threshold` | POST | `{"mg": 2500}` (500-8000), re-applied after reconnects and ESP resets |
| `/shaper/capture` | POST | `{"duration": 7, "rate": 1600, "baud": 921600}` -> samples, loss %, CSV path |

The old Wi-Fi mode (`ENABLE_WIFI`, REST on the ESP, TCP stream on 8266) is still in the firmware sources but is
disabled and not used by anything here.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyserial numpy scipy matplotlib jinja2
.venv/bin/python -m pytest tests scripts/test_shaper_math.py     # daemon, macros, installer, analyzer
firmware/test/run.sh                                              # firmware logic (host C++ compiler)
```

None of this replaces the on-printer procedure in the deployment guide (section 6).
