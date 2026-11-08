# Plugins

Backend plugins are single files in `backend/plugins/` (names not starting with
`_`). They load at startup, after authentication is installed, so their routes
are protected like every other route. A plugin that fails to import or register
is logged and skipped; it can never stop the backend from starting.

Disable any plugin with `INDUS3D_DISABLED_PLUGINS=arbiter,watchdog`.
`GET /api/v1/plugins` lists what is loaded.

## Contract

A plugin module may define any of:

```python
PLUGIN_INFO = {"title": "…", "description": "…"}

def register_hooks(hooks):      # subscribe to the control loop
    hooks.on("commands.filter", my_filter, priority=50)   # lower runs first

def register_routes(app):       # add Flask routes under /api/v1/plugins/<name>
    ...
```

### Hooks (`core/plugin_hooks.py`)

| Hook | Callback | When |
| --- | --- | --- |
| `tick` | `fn(snap, ctx)` | every telemetry tick |
| `controller.inputs` | `fn(snap, kin, thm, ext, ctx)` | before the controller runs; mutate `ext` to add measured values |
| `commands.filter` | `fn(commands, ctx) -> commands` | on the controller's output, before sending; drop a command with `ctx_veto(ctx, cmd, plugin, reason)` |
| `commands.sent` | `fn(results, ctx)` | after sending; `results = [{command, ok, ts}]`; `ctx["corrections"]` carries the reasons |
| `commands.vetoed` | `fn(vetoes, ctx)` | commands a filter dropped |
| `shadow.commands` | `fn(commands, ctx)` | commands the controller *would* send while the auto-pilot is off |

A hook that raises is logged and skipped; a failing filter leaves the commands
unchanged. Both the live worker and the simulator route commands through
`core/command_pipeline.py`, so plugins behave the same in both.

## Built-in plugins

| Plugin | What it does | Endpoint |
| --- | --- | --- |
| `shadow_mode` | While the auto-pilot is off, a side-effect-free second controller computes what it would send and records it. Nothing is ever sent (the clog *pause* is reported, not performed). | `GET /api/v1/plugins/shadow_mode` |
| `audit_trail` | Writes every command to `command_log` (source `qc` / `qc-shadow`; status `ok`, `failed`, `shadow`, `vetoed:…`) and every correction with its reason to `action_log` (`qc:<type>` / `qc_shadow:<type>`). | — (see the Action Log) |
| `arbiter` | Stops Indus3D fighting other writers of M221/M220. `INDUS3D_ARBITER_EXTERNAL=flow,speed` declares families something else owns; external changes to the live flow/speed factor are detected and Indus3D yields that family for `INDUS3D_ARBITER_YIELD_S` (default 30 s). | `GET /api/v1/plugins/arbiter` |
| `watchdog` | Disables the auto-pilot, notifies, and blocks corrections if it runs away: >`INDUS3D_WATCHDOG_MAX_PER_MIN` commands/min (60), ≥`INDUS3D_WATCHDOG_MAX_REVERSALS` direction reversals of flow/speed/temp in 120 s (8), or `INDUS3D_WATCHDOG_MAX_FAILS` consecutive send failures (5). Re-arms when a human re-enables the auto-pilot. | `GET /api/v1/plugins/watchdog`, `POST …/reset` |
| `approval` | **Off by default.** When on (`INDUS3D_APPROVAL_MODE=1` or `POST …/approval/mode`), holds every correction (safety commands excepted) until approved; only the newest per family is kept and held commands expire after `INDUS3D_APPROVAL_TTL_S` (30 s). | `GET /api/v1/plugins/approval`, `POST …/<id>/approve`, `…/<id>/reject`, `…/approve_all`, `…/mode` |
| `first_layer_guard` | Drops corrections while commanded Z is below `INDUS3D_FIRST_LAYER_Z_MM` (0.8). `INDUS3D_FIRST_LAYER_BLOCK=all` (default) or a family list. Safety commands pass. | `GET /api/v1/plugins/first_layer_guard` |
| `thermal_sanity` | Warn-only: sensor spikes, sustained off-target temperature, heater at full PWM without heating. Notifies once per event; never sends G-code. | `GET /api/v1/plugins/thermal_sanity` |
| `filament_sensor` | Polls the sensor daemon (`INDUS3D_SENSOR_URL`, default `http://127.0.0.1:7126`; empty disables) in a background thread; alerts on faults/runout; makes the arbiter yield `flow` while the daemon's auto-flow is active (or `INDUS3D_SENSOR_INI` says it is enabled). | `GET /api/v1/plugins/filament_sensor` |
| `health_score` | A 0-100 score per print with its components; the final score is written to `action_log` (`print_health`). Heuristic weights, not a validated metric. Uses live controller values with the auto-pilot on, the shadow run otherwise. | `GET /api/v1/plugins/health_score` |
| `prometheus_exporter` | Prometheus text format: telemetry, controller values, command/veto counters, plugin state. Behind the auth gate; use a Bearer credential in Prometheus when a password is set. | `GET /metrics` |

### Analysis, integration and data plugins

`run_recorder` is the base for the analysis plugins: it keeps what the controller did during each print and archives finished runs (last 30) under the plugin data dir (`INDUS3D_PLUGIN_DATA`, default `backend/data/plugins`).

| Plugin | What it does | Endpoint (under `/api/v1/plugins/…`) |
| --- | --- | --- |
| `run_recorder` | Per-print record: applied/vetoed/shadow commands, correction reasons, progress, hotend tracking error. Subscribe with `recorder.on_finish(fn)`. | `run_recorder`, `run_recorder/<id>` |
| `corrective_tracker` | Live ring buffer + JSONL trail of every command/veto/shadow command, and a "why is nothing being sent?" diagnosis. | `corrective_tracker`, `…/diagnose` |
| `corrections_timeline` | Chart-ready corrections vs print progress per family. | `corrections_timeline?run=<id\|current>` |
| `model_scorer` | After each print: slicer-estimate vs actual print time and filament, and hotend tracking error (±10 % tolerance). | `model_scorer` |
| `controller_tuner` | Advice (never applied) on gains/deadbands from chatter, clamping, flooring and veto rates. | `controller_tuner` |
| `slicer_feedback` | Per-material suggested flow multiplier and pressure advance from what the controller applied (needs ≥3 completed prints). | `slicer_feedback`, `…/export?format=orca\|prusa\|json` |
| `print_report` | Self-contained HTML report per print (print-to-PDF from the browser). | `print_report`, `print_report/<id>` |
| `calibration_runner` | Ordered, reviewable calibration checklist (templates full/pid/mesh/flow/pa) that validates results and recommends; **executes nothing** — it names the existing safety-gated endpoints. | `calibration_runner` (+ `POST`, `…/<id>/steps/<key>/complete\|skip`) |
| `spool_planner` | Will the spool finish this file? Slicer figure vs sensor / virtual-spool remainder, with margin; notifies at print start if not. | `spool_planner?filename=` |
| `maintenance_advisor` | % of each maintenance limit used, projected print hours left, one-time "soon"/"due" alerts. | `maintenance_advisor` |
| `energy_cost` | Energy and cost per print and per day/week/month at `INDUS3D_ENERGY_PRICE_PER_KWH`. | `energy_cost?period=&limit=` |
| `fleet_aggregator` | One summary of every registered printer (Moonraker read-only), with attention reasons; Indus3D's view for the active one. | `fleet` |
| `esp_bed_hub` | ESP8266 bed hub: bed accel, chamber climate, crash-latch alert. `INDUS3D_ESP_HUB_URL` (empty = off). | `esp_bed_hub` |
| `chamber_environment` | Warn-only: humid chamber air, heat-creep risk for PLA/PETG/TPU (needs the hub). | `chamber_environment` |
| `tmc_current` | **Opt-in** (`INDUS3D_TMC_CURRENT=1`): estimates extruder current from the TMC `cs_actual` so the clog detector can fire. Validate with shadow mode first: a wrong estimate pauses healthy prints. | `tmc_current` |
| `chat_actions` | **Opt-in** (`INDUS3D_CHAT_ACTIONS=1`): Telegram /status /pause /resume /cancel(+confirm) /autopilot_off, only from your chat. Discord is outbound-only and cannot receive commands. | `chat_actions` |
| `mqtt_bridge` | State and events to an MQTT broker with Home Assistant discovery (`INDUS3D_MQTT_HOST`; plain TCP, no TLS). | `mqtt_bridge` |
| `webhook_events` | Forwards every notification as a signed webhook (`INDUS3D_WEBHOOK_URLS`, `…_SECRET`). A generic webhook, **not** an Obico/OctoEverywhere client. | `webhook_events` |
| `spoolman_sync` | **Opt-in** (`INDUS3D_SPOOLMAN_RECONCILE=report\|apply`): compares Spoolman's recorded use with the sensor's; `apply` tops up only when the sensor measured more. It never re-reports usage Moonraker already sent. | `spoolman_sync` |

The dashboard-widget items (corrections timeline, maintenance advisor, energy/cost) are **data endpoints only**; no frontend component has been added for them yet.

### A vetoed command is not lost

When a plugin drops a command, the pipeline calls `controller.notify_vetoed()`
so the controller forgets it assumed the value was applied and proposes it
again on its next cycle. Without this, a command held back by the first-layer
guard or approval mode would never be sent once the hold ended.

Limits worth knowing:

- Shadow output only exists while a print is running and the auto-pilot is off.
- The arbiter can only *detect* external writes to flow and speed (the two
  factors Klipper reports). Other families need declared ownership.
- The watchdog guards against the controller misbehaving, not against a bad print.
- The first-layer guard and approval mode are the only plugins that hold commands back by design; everything else only observes, except the arbiter and watchdog.
- Thermal-sanity spike detection is skipped in the simulator, which teleports temperatures.
- Measured extruder current is still not available anywhere, so the clog detector stays idle regardless of plugins.
- There is no dashboard UI for these yet; use the endpoints, `/metrics`, or the Action Log.
