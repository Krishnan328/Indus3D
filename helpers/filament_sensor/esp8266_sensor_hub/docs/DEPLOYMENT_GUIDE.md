# Deployment & Setup Guide
## Indus3D ESP8266 bed sensor hub (bed crash detection, Y input shaping, chamber telemetry)

The hub talks to the printer's host over **USB serial only** (`ENABLE_WIFI` is `false`). A small daemon on the
host owns the serial port; Klipper macros, Moonraker and Indus3D all go through that daemon.

```
ESP8266 --USB--> esp_bed_monitor_daemon.py (systemd: esp8266_bed_hub.service, 127.0.0.1:7127)
                    |-- crash alert --> Moonraker POST /printer/print/pause, then BED_CRASH_HANDLER JERK=<mg>
                    |-- 1 Hz status  --> MQTT (optional) --> Moonraker [sensor] --> Fluidd/Mainsail
                    |-- HTTP API     <-- esp_hub_ctl.py  <-- Klipper gcode_shell_command <-- macros
                    `-- HTTP API     <-- Indus3D backend plugin esp_bed_hub (SQLite telemetry_samples, UI card)
```

Hardware: NodeMCU ESP8266, ADXL345 on HSPI with CS on GPIO16 mounted on the bed's Y carriage, BME280 on
GPIO0 (SDA) / GPIO2 (SCL) at 0x76. See `WIRING_AND_PINOUT.md`.

> **What has and has not been verified.** The firmware was verified on the real hardware by its author at version
> 1.0. Version 1.1.0 (serial command protocol, baud switch for shaper captures, crash alert with the real jerk value),
> the daemon, the macros, the installer and the analyzer were written and tested **in software only** (host-side
> firmware logic tests, a software model of the hub on a fake serial port, Jinja rendering of the macros against a mock
> printer, unit tests). Flash 1.1.0 and run the procedure in section 6 on the real printer before trusting it.

---

## 1. Flash the firmware

```bash
cd firmware
pio run --target upload        # PlatformIO; board and flags are in platformio.ini
pio device monitor -b 115200   # optional: you should see one JSON line per second
```

Every second the hub prints one line:

```json
{"bed_accel":{"x_mg":145,"y_mg":-12,"z_mg":-980,"jerk_mg":18},"chamber":{"temp_c":26.4,"humidity_pct":43.1,"pressure_hpa":1012.8},"crash_detected":false,"crash_threshold_mg":2000,"adxl_ok":true,"bme_ok":true,"uptime_sec":1}
```

`chamber` is `null` when the BME280 does not answer, so a dead sensor never shows up as 0 °C.
Close the serial monitor before starting the daemon: only one program can hold the port.

Serial commands (typed or sent by the daemon): `PING`, `STATUS`, `SET_CRASH_THRESHOLD <500-8000>`, `RESET_CRASH`,
`START_SHAPER [duration_s 1-15] [rate_hz] [baud]`, `STOP_SHAPER`.

## 2. Install on the host

Requirements: Klipper + Moonraker, the **G-Code Shell Command** Klipper extension (KIAUH: *Advanced -> G-Code Shell
Command*), a `[pause_resume]` section and PAUSE/RESUME macros (the Mainsail or Fluidd client config provides both),
and a Python with `pyserial numpy scipy matplotlib`:

```bash
python3 -m venv helpers/filament_sensor/esp8266_sensor_hub/.venv
helpers/filament_sensor/esp8266_sensor_hub/.venv/bin/pip install pyserial numpy scipy matplotlib
```

The Python must be readable and executable by the user Klipper runs as (the shell commands run as that user). A
virtual environment inside a `0700` home directory will not work: put it somewhere world-readable.

Then, with the hub plugged in:

```bash
cd helpers/filament_sensor/esp8266_sensor_hub
./install_hub.py --dry-run                 # shows every step, changes nothing
./install_hub.py [--device /dev/ttyUSB0] [--mqtt localhost]
```

This does, idempotently:

| Step | Result |
|---|---|
| udev | `/etc/udev/rules.d/99-esp8266-bedhub.rules`: symlink `/dev/esp8266_bed_hub`, group `dialout`, mode `0660`, ModemManager told to ignore the device. The adapter is matched by its USB serial number, or by the **physical USB port** if it has none (CH340 boards). In that case keep it in the same port, or re-run the installer after moving it. |
| systemd | `esp8266_bed_hub.service` (runs as you, `dialout` as supplementary group, restarts on failure, state in `/var/lib/indus3d/bed_hub`) |
| Klipper | `<config>/esp8266_sensor_hub/bed_sensor_hub.cfg` (kept if it exists), `bed_sensor_hub_shell.cfg` (regenerated), and two `[include]` lines in `printer.cfg` |
| Moonraker | `<config>/esp8266_sensor_hub/moonraker_bed_hub.conf` and its `[include]` in `moonraker.conf` |

Backups of `printer.cfg` / `moonraker.conf` are written next to them (`*.indus3d_bak_<time>`) before any change.
NixOS or other declarative hosts: `./install_hub.py --print-only` prints the udev rule and the unit to translate into
your configuration, and `--no-udev --no-service` does just the config files.

### Manual include instructions (instead of the installer)

1. Copy `klipper/bed_sensor_hub.cfg` to `~/printer_data/config/esp8266_sensor_hub/`; set `variable_printer_cfg` and
   `variable_outdir` in `_BED_HUB_VARS`.
2. Copy `klipper/bed_sensor_hub_shell.cfg.in` to `bed_sensor_hub_shell.cfg` and replace `@PYTHON@`, `@SCRIPTS@`
   (the absolute `scripts/` directory) and `@HUB_URL@` (`http://127.0.0.1:7127`).
3. `printer.cfg`: `[include esp8266_sensor_hub/bed_sensor_hub.cfg]` and `[include esp8266_sensor_hub/bed_sensor_hub_shell.cfg]`.
4. `moonraker.conf`: `[include esp8266_sensor_hub/moonraker_bed_hub.conf]`.
5. Install and enable the unit from `esp8266_bed_hub.service.in` and the udev rule (`install_hub.py --print-only`).
6. `FIRMWARE_RESTART` Klipper and `sudo systemctl restart moonraker`.

### Moonraker

* The daemon runs on the printer's own host and calls Moonraker on `127.0.0.1:7125`. Your `[authorization]` must trust
  `127.0.0.0/8` (the stock Mainsail and Fluidd configs do). **Do not add a second `[authorization]` section**: Moonraker
  would refuse to start. Add Fluidd/Mainsail origins to your existing `cors_domains` only if you open the UI from
  another machine.
* The chamber/crash "sensor" card needs an MQTT broker (Moonraker's `[sensor]` component is MQTT-only), for example
  `sudo apt install mosquitto`, plus `--mqtt localhost` on the daemon (the installer's `--mqtt` flag). Fluidd shows the
  card in its Sensors panel; recent Mainsail versions list Moonraker sensors too (not verified here). Without a broker
  everything else works, and `BED_HUB_STATUS` prints the same values.

## 3. Daily use

| Console command / button | Does |
|---|---|
| `BED_HUB_STATUS` | prints hub connection, chamber, bed accel, jerk, threshold, crash latch |
| `BED_HUB_RESET_CRASH` | clears the hub's crash latch ("Reset Bed Crash Latch") |
| `SET_BED_CRASH_THRESHOLD VALUE=2500` | sets the crash threshold in mg (500-8000), remembered across hub resets |
| `BED_CRASH_RESUME` | after a crash: reheat to the saved targets, re-prime, clear the latch, restore the toolhead state and resume |
| `BED_SHAPER_CALIBRATE_Y [APPLY=1] [RATE=1600]` | Y input shaper calibration with the bed accelerometer (section 5) |

Mainsail and Fluidd name their macro buttons after the macros; Klipper has no separate display label.
Command line (same thing the macros call): `scripts/esp_hub_ctl.py status | reset-crash | set-threshold 2500 | shaper-capture ...`.
Logs: `journalctl -u esp8266_bed_hub -f`. State and a size-rotated `telemetry.csv`: `/var/lib/indus3d/bed_hub/`.

## 4. How a crash is handled

1. The ESP samples the ADXL345 at 200 Hz; when the 3-axis jerk exceeds the threshold (default 2000 mg) it latches and
   prints `// Klipper: BED_CRASH_DETECTED jerk=2450 mg (accel=[...] mg) -> ...` at once.
2. The daemon reads that line (or the latch in the next telemetry line as a fallback). **Only while a print is
   running** it posts `/printer/print/pause` to Moonraker, retrying, and then runs `BED_CRASH_HANDLER JERK=2450`.
   While idle or already paused it only logs: the handler moves the toolhead and must never run on an unhomed printer.
   A second alert within 10 s is treated as the same crash.
3. `BED_CRASH_HANDLER`: saves the hotend/bed targets, `SAVE_GCODE_STATE`, `PAUSE` (skipped if already paused),
   retracts 2 mm, lifts Z by up to 10 mm (never beyond the Z maximum), parks at X10 Y220 (clamped to the axis ranges),
   switches the hotend heater off (the bed stays on), and beeps three times if you have an `[output_pin beeper]`.
   If the axes are not homed it does not move anything. All of these values are variables in `_BED_HUB_VARS`.
4. The Indus3D plugin raises a notification and an audit entry, and holds every corrective command until the latch is
   cleared (so a queued `M104` cannot reheat the hotend that was just switched off).
5. `BED_CRASH_RESUME` (after you inspected the bed) reheats bed and hotend to the saved targets, re-primes, clears the
   latch, restores the toolhead state and resumes.

Tuning: normal printing produces jerk spikes of roughly 250-700 mg; the default of 2000 mg separates that from a real
collision. If a gentle tap does not trigger it, lower it for the test (`SET_BED_CRASH_THRESHOLD VALUE=1200`) and put it
back afterwards.

## 5. Y input shaper calibration

`BED_SHAPER_CALIBRATE_Y` (printer idle, not printing or paused): homes if needed, moves to the bed centre, switches
the active input shaper off, starts the capture, then drives the bed along Y in a stepped sweep from 5 to 120 Hz and
restores the acceleration limits and the shaper. At each frequency *f* the amplitude is `min(max_amp, max_accel / (16 f^2))`
with the matching acceleration, so each half-cycle lasts exactly `1 / (2 f)`.
**At the highest frequencies the amplitude is a few hundredths of a millimetre**: the sweep excites the low and
middle resonances well and the top end only weakly (limited by `sweep_max_accel`, default 7000 mm/s^2). If your bed
resonates above about 70 Hz, raise it carefully.

The capture (at most 15 s; the macro refuses a sweep that does not fit) runs in the daemon and the analysis in the same
shell command:

1. the hub switches its serial link to a faster baud for the session (1600 Hz needs about 240 kbit/s) and back after;
2. the CSV is resampled onto a uniform grid, a Welch PSD is taken over 5-120 Hz, the peak and the damping ratio
   (half-power bandwidth, default 0.1) are estimated;
3. for ZV, MZV, ZVD, EI, 2HUMP_EI and 3HUMP_EI the shaper frequency is scanned and the residual vibration
   `V(w) = exp(-z w t_N) * sqrt((sum A_i e^{z w t_i} cos(w_d t_i))^2 + (sum A_i e^{z w t_i} sin(w_d t_i))^2)` is evaluated
   over damping ratios 0.075/0.1/0.15; the choice minimises `smoothing * (vibr^1.5 + 0.2 vibr + 0.01)`;
4. the maximum acceleration comes from the smoothing limit (0.12 mm at 5 mm/s corner speed);
5. output in `variable_outdir`: `shaper_calibration_bed_y.png`, `bed_input_shaper_y.cfg`, the CSV, and the report in
   the console. With `APPLY=1` (or `variable_shaper_autoapply: 1`) `[input_shaper]` in `printer.cfg` is updated
   (`shaper_type_y: mzv`, `shaper_freq_y: 42.6`; a backup is written first) and you run `RESTART`.

If a previous `SHAPER_CALIBRATE` + `SAVE_CONFIG` left an `[input_shaper]` block under `#*# <---- SAVE_CONFIG ---->`,
Klipper gives that block precedence over the edit; the analyzer warns and you delete those `#*#` lines.
The shaper definitions are the published textbook forms; Klipper's `SHAPER_CALIBRATE` uses refined coefficient fits, so
numbers can differ slightly. Use Klipper's own tools wherever an accelerometer can sit on the toolhead.

## 6. End-to-end crash test (do this once, with the printer on)

1. Check: `BED_HUB_STATUS` shows `hub connected`, a chamber temperature and a small jerk; `systemctl status
   esp8266_bed_hub` is active; `ls -l /dev/esp8266_bed_hub` exists; the Indus3D "Bed Sensor Hub" card says *live*.
2. **Dry run (idle printer):** tap the bed. The daemon logs `crash response: ignored: no print running (standby)` and
   clears the hub's latch itself so it stays armed; the macro does not run and the toolhead does not move.
3. Start a print (or any file that stays above the bed for a while) with bed and hotend hot. Once it prints, lower the
   threshold if needed (`SET_BED_CRASH_THRESHOLD VALUE=1200`) and **tap the bed**.
4. Expected within about a second: Mainsail shows *Paused*; the console shows `BED COLLISION: ... jerk N mg`; the
   toolhead retracts, lifts and parks at X10 Y220; the hotend cools down, the bed stays hot; the Indus3D card turns red
   with the jerk value; you receive the notification; `journalctl -u esp8266_bed_hub` shows the pause and the handler.
5. Inspect the bed, then run `BED_CRASH_RESUME`. Expected: bed and hotend reheat to their old targets, the nozzle is
   primed, the latch clears (card back to *live*), the toolhead returns and the print continues.
6. Put the threshold back (`SET_BED_CRASH_THRESHOLD VALUE=2000`).

Failure checks worth doing once: stop Moonraker and tap the bed during a print (the daemon cannot pause; the Indus3D
notification then says `FAILED to pause ... PAUSE THE PRINT YOURSELF`); pull the USB cable (daemon reconnects by itself
when it is back, and the threshold is re-applied; the card says *hub unplugged* meanwhile).

## 7. Indus3D integration

The backend plugin `esp_bed_hub` (default `http://127.0.0.1:7127`; `INDUS3D_BED_HUB_URL=` empty disables) polls the
daemon once a second and: stores every new sample in SQLite table `telemetry_samples` (`timestamp_utc` ISO-8601,
`chamber_temp_c`, `chamber_humidity_pct`, `chamber_pressure_hpa`, `bed_accel_x_mg`, `bed_accel_y_mg`, `bed_accel_z_mg`,
`bed_jerk_mg`, `crash_detected`; written in batches, kept 7 days: `INDUS3D_BED_TELEMETRY_DAYS`,
`INDUS3D_BED_TELEMETRY_DB=0` to switch storage off); feeds `/api/v1/environment`, `chamber_environment` and `/metrics`;
raises the crash notification and audit entry; holds corrective commands while the crash is latched
(`INDUS3D_BED_CRASH_HOLD=0` to disable); and shows the dashboard card.
Optional hook, **off by default**: `INDUS3D_BED_CRASH_EXCLUDE_OBJECT=1` sends `EXCLUDE_OBJECT NAME=<current object>`
after a crash while the print is paused, so the resume skips that object. An acceleration spike says the bed was hit,
not which object caused it, so enable this only if you know your failure mode.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `BED_HUB_STATUS`: cannot reach the hub daemon | service not running | `systemctl status esp8266_bed_hub`, `journalctl -u esp8266_bed_hub` |
| daemon up, `hub NOT CONNECTED` | USB cable/port, serial monitor open, wrong device | close other programs on the port; `ls /dev/serial/by-id`; re-run `install_hub.py --device ...` |
| symlink `/dev/esp8266_bed_hub` missing after moving the cable | rule matches the old USB port (no serial number) | re-run `install_hub.py` |
| `hub` data but `chamber: null` | BME280 not answering | check SDA/SCL on GPIO0/GPIO2, address 0x76/0x77, 3V3 |
| board does not start from power-up | GPIO0/GPIO2 held low | see wiring doc section 3.1 (pull-ups) |
| macros: `reset_hub_crash is not configured` | shell cfg not included, or the G-Code Shell Command extension missing | include `bed_sensor_hub_shell.cfg`; install the extension from KIAUH |
| shaper command prints a Python import error | the Python in the shell cfg lacks numpy/scipy/matplotlib | install them there; re-run the installer with `--python` |
| shaper capture "loss" high | serial overruns | lower `RATE` to 800; use a short, good USB cable |
| calibration changed nothing after `APPLY=1` | an auto-saved `[input_shaper]` block overrides it | delete those `#*#` lines (the report warns) |
| Moonraker will not start after editing | a second `[authorization]` section | remove it; only the include of `moonraker_bed_hub.conf` is needed |
