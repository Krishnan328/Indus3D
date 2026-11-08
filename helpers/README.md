# Indus3D helpers

Everything that sits *around* the core backend lives here, so the whole folder
can later be turned into an installation package without hunting through the
host's home directory.

| Folder | What it is | Origin on the NixOS host |
| --- | --- | --- |
| `filament_sensor/` | RP2040 smart filament sensor: host daemon (diameter, auto-flow `M221`, spool weight, runout, clog watchdog, REST on :7126), calibration wizard, test tools, Pico firmware, ESP8266 bed-sensor hub | `~/filasens/` |
| `lab/` | Read-only field toolkit: telemetry capture, run analysis, prediction-vs-reality, system stats, calibration artifact generators | `~/indus3d-5391f4c/tools/indus3d_lab/` |
| `trackers/` | **New.** `corrective_gcode_tracker.py` — explains why corrective G-code is or is not being sent and keeps a durable trail of what was | — |
| `kiauh/` | **New.** KIAUH extension so Indus3D installs from KIAUH like Mobileraker, Obico or the Telegram bot | — |

The originals on the host were copied, not moved: `indus3d-filament-sensor.service`
runs `~/filasens/indus3d_sensor_daemon.py` and must keep working until the
package replaces it. Runtime data (CSV/JSON state, logs, captured plots) and
build/vendor directories were left out.

## Why so little corrective G-code was sent

Found on the host (`nixos-ks`, service `indus3d`, DB `/var/lib/indus3d/db`):

- `printer_config` has **no `auto_pilot_enabled` row**, so the auto-pilot is at
  its default: **off**. In that state the quality controller calculates and
  returns nothing — no `M221`/`M220`/`SET_PRESSURE_ADVANCE` ever leaves Indus3D.
- `command_log` and `action_log` have **0 rows** (330 k twin snapshots exist).
  Autopilot output is never written to either table; only the last ~10
  corrections / ~20 commands are kept in memory, so after the fact there is no
  evidence of what was or was not sent.
- Once the auto-pilot is on, the sensor daemon's auto-flow
  (`enable_auto_flow = true`) and the Indus3D flow loop both write `M221`.
  Run only one of them.

```bash
# why is nothing being sent right now? (read-only; GETs only)
python3 trackers/corrective_gcode_tracker.py --diagnose \
    --sensor-ini ~/filasens/indus3d_sensor.ini \
    --password-file /var/lib/indus3d/indus3d.env

# keep a durable trail of every corrective command / correction
python3 trackers/corrective_gcode_tracker.py --follow --password-file /var/lib/indus3d/indus3d.env
python3 trackers/corrective_gcode_tracker.py --summary ~/.local/share/indus3d/tracker/corrective_gcode.jsonl
```

The tracker never POSTs, so it cannot change the printer or toggle the
auto-pilot. The password file is read for `INDUS3D_PASSWORD` only and sent only
to the Indus3D URL as a Bearer token; it is never written to the trail.

Tests: `python -m pytest helpers/trackers/tests helpers/lab/tests`.

## KIAUH

KIAUH discovers extensions by scanning `kiauh/extensions/*/metadata.json`, so
Indus3D integrates without patching KIAUH:

```bash
git clone https://github.com/dw-0/kiauh.git ~/kiauh        # if not installed yet
helpers/kiauh/install_extension.sh                         # or --link while developing
~/kiauh/kiauh.sh                                           # Extensions -> Indus3D
```

The extension (`kiauh/indus3d/`) follows the same contract as the bundled
extensions (`BaseExtension` + `metadata.json`) and does what Mainsail/Fluidd
users expect from KIAUH:

- **Install** — clones the repo, creates the venv, installs requirements,
  builds the dashboard when `npm` exists, writes and enables `indus3d.service`,
  copies and `[include]`s `indus3d.cfg`, adds `[update_manager indus3d]` to
  `moonraker.conf` (with a KIAUH backup first), optionally installs the tracker
  service and links the ADXL streaming module into Klipper.
- **Update** — stop, `git pull`, reinstall requirements, start.
- **Remove** — removes services and config entries; keeps the checkout (and
  your database) unless you confirm deletion.

Constants (repo, branch, paths, service names) are in `kiauh/indus3d/__init__.py`.
`INDUS_BRANCH` is `v2.0-staging` because `main` still holds the initial public
release; switch it to `main` after merging. `index` in `metadata.json` is `90`
(KIAUH assigns 1–16 today); to get listed in KIAUH proper, open a pull request
adding the folder to `kiauh/extensions/` in `dw-0/kiauh`.

Verified against KIAUH `485b7bc` in a scratch checkout: the extension is
discovered and its class loads. The install/update/remove flows themselves have
**not** been run end-to-end on a real Klipper host yet.

## Filament sensor

```bash
helpers/filament_sensor/install_sensor.py --dry-run     # shows exactly what it would change
helpers/filament_sensor/install_sensor.py               # config dir auto-detected (--klipper-config DIR to override)
helpers/filament_sensor/install_sensor.py --uninstall   # keeps your indus3d_sensor.ini unless --purge
```

It copies `indus3d_sensor.ini` (never overwrites yours), installs
`smart_filament_sensor.cfg` with any `[respond]` / `[gcode_macro …]` that your
config already defines commented out **as a whole block** (commenting only a
header leaves its body attached to the previous macro and silently overwrites
it), adds the `[include]` to `printer.cfg` after a timestamped backup, and
installs the templated `indus3d-filament-sensor.service`. The daemon listens on
`127.0.0.1:7126` only and its state-changing endpoints need the
`X-Indus3D-Action: 1` header; Indus3D proxies the calibration actions through
its own authenticated API (`POST /api/v1/plugins/filament_sensor/action`) and
shows the sensor on the Digital Twin page. Tests: `python -m pytest helpers/filament_sensor/tests`.

## ESP8266 bed sensor hub

```bash
helpers/filament_sensor/esp8266_sensor_hub/install_hub.py --dry-run   # udev rule, systemd unit, Klipper + Moonraker includes
helpers/filament_sensor/esp8266_sensor_hub/install_hub.py [--device /dev/ttyUSB0] [--mqtt localhost]
```

The hub (ADXL345 on the bed, BME280 in the chamber) talks USB serial to a host daemon
(`esp8266_bed_hub.service`, API on `127.0.0.1:7127`). On a crash while printing the daemon pauses the print
through Moonraker and runs `BED_CRASH_HANDLER`; `BED_CRASH_RESUME` continues;
`BED_SHAPER_CALIBRATE_Y` runs the Y input shaper calibration. The Indus3D `esp_bed_hub` plugin stores the
telemetry in `telemetry_samples`, feeds the environment endpoint and holds corrections during a crash.
Setup, the end-to-end crash test and troubleshooting: `filament_sensor/esp8266_sensor_hub/docs/DEPLOYMENT_GUIDE.md`.
Tests: `python -m pytest helpers/filament_sensor/esp8266_sensor_hub/tests helpers/filament_sensor/esp8266_sensor_hub/scripts/test_shaper_math.py`
and `helpers/filament_sensor/esp8266_sensor_hub/firmware/test/run.sh`. The firmware 1.1.0 changes and all host
software are tested in software only; the on-printer procedure has not been run yet.

## Known gaps before packaging

- On the NixOS host the sensor's service is declared in the Nix configuration
  (it still runs the daemon from `~/filasens`). Point it at
  `helpers/filament_sensor/indus3d_sensor_daemon.py` and use
  `install_sensor.py --no-service` for the Klipper side; `install_sensor.py`
  itself targets Debian-family hosts with systemd.
- The extension targets Debian-family hosts (KIAUH itself is Debian-only). The
  NixOS deployment keeps using its Nix module.
- The host's `indus3d-5391f4c` snapshot contains backend pieces the repo does
  not have yet (`api/routes/lab.py`, `calibration_workflow.py`, migrations
  010–012, `nix/`). Only the `tools/indus3d_lab` scripts were imported here.
