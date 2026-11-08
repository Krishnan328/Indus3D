# System page

Host, MCUs, services, software updates, database backups and devices, in one page (nav rail → **System**).
The browser never talks to Moonraker: `backend/api/routes/system.py` is a thin, validated proxy and
`backend/api/system_host.py` shapes the data. Everything degrades per feature: an endpoint this Moonraker lacks is
reported as "not available on this Moonraker" and never breaks the rest of the page.

Moonraker endpoints were checked against <https://moonraker.readthedocs.io> (latest) in Nov 2026; they have **not**
been exercised against a real Moonraker yet (see "Untested" below).

## Rules that apply to every route

| Rule | Detail |
|---|---|
| Auth | Behind the normal auth gate (`INDUS3D_PASSWORD`). |
| Moonraker down | `502 {"ok": false, "error": "Moonraker unreachable: …"}`. Moonraker refusing a call: `502` with its message and `upstream_status`. |
| Endpoint missing | `404 {"ok": false, "unsupported": true, "error": "<path> is not available on this Moonraker"}` (Moonraker answered 404/405). Aggregating routes (`/info`, `/alerts`, `/peripherals`) answer `200` and mark the missing part instead. |
| Confirmation | Every state-changing call needs `"confirmed": true` (the literal boolean) in the JSON body, else `400 {"needs": "confirmed"}`. |
| Busy | Refused with `409 {"busy": true, "reason": "print" \| "update"}` while a print is running/paused (see below), or while an update is already running. |
| Rate limit | `POST` and `DELETE` under `/api/v1/system/` use the strict `hardware_cmd` limit (10/min, violations count toward the 24 h IP ban). They are deliberately **not** in `ui_adjust`. Reads use the default 120/min; the page polls far below that. |
| Simulator | When the active worker is the simulator, every route answers from an in-memory stand-in for Moonraker (`system_host._sim_call`), including actions (a restarted service shows as restarted, an update clears itself, backups can be created/deleted). The `host_alerts` plugin stays silent. |
| Client input | Never forwarded unless it names a service / component / backup file that Moonraker itself just listed, and it matches a strict pattern. No raw G-code or Moonraker path is accepted. |

## Endpoints (`/api/v1/system`)

| Method and path | What it does | Moonraker calls |
|---|---|---|
| `GET /info` | `host` (hostname, OS, model, CPU load/temperature, memory, uptime, network, throttle state, Klipper/Moonraker versions, failed components), `mcus` (version, chip, clock, awake %, task average, retransmits), `sections` (per-source ok/unsupported/error). | `machine/system_info`, `machine/proc_stats`, `printer/info`, `server/info`, `printer/objects/list` + `query` for `mcu*` |
| `GET /services` | Services Moonraker may manage with state, `is_self`, `print_critical`, `manageable`. | `machine/system_info` |
| `POST /services/<name>/<restart\|start\|stop>` | Name must be in the service list. `confirmed`. Klipper/Moonraker/klipper_mcu `restart`/`stop` refused during a print (`start` allowed). Stopping the service that serves Indus3D needs `"confirm_self": true` as well. | `POST machine/services/<action>` |
| `GET /updates` | Components with versions, `update_available`, commits behind, `pending`, `busy`, GitHub allowance, and `job` (Indus3D's own view of the update it started). | `machine/update/status` |
| `POST /updates/<component>` | `klipper`, `moonraker`, a client name, `system`, or `full` (name must be in the update list, `full` = everything). `confirmed`. Refused during a print, when Moonraker reports `busy`, or while another update runs. Answers `202` at once and runs the call on a background thread: Moonraker only answers when the update has finished, so poll `GET /updates` (the page does, every 5 s while `job.state` is `running`). | `POST machine/update/upgrade` `{name}`; on 404/405 the legacy `machine/update/{full,system,klipper,moonraker,client}` |
| `POST /updates/<component>/recover` | `{"hard": bool}`. Git repositories only. Same gates as an update. | `POST machine/update/recover` |
| `GET /backups` | Database backup files. `supported: false` when Moonraker has no `backups` list. | `GET server/database/list` |
| `POST /backups` | `{"filename"?: "x.db"}` (`[A-Za-z0-9][A-Za-z0-9_.-]*\.db`). `409` if it exists or a print runs. | `POST server/database/backup` |
| `POST /backups/<file>/restore` | `confirmed`; file must be listed; refused during a print. Moonraker restarts right after, so a dropped connection is reported as `{"restarting": true}`. | `POST server/database/restore` |
| `DELETE /backups/<file>` | `confirmed` in the JSON body; file must be listed. | `DELETE server/database/backup?filename=` |
| `GET /peripherals` | `usb`, `serial` (with `recommended_path`: `by-id`, else `by-path`, else the device node, plus `recommended_kind`), `video`, each independently available or not; `link_health` = the `usb_link_health` suspects when that plugin is running. `canbus` is **only queried with `?canbus=can0`**: querying unassigned CAN nodes can put them in bus-off. | `machine/peripherals/{usb,serial,video,canbus}` |
| `GET /announcements` | Moonraker announcements that are not dismissed. | `server/announcements/list` |
| `GET /alerts` | Active alerts (below) with severities and counts. | `proc_stats`, `server/info`, `update/status`, `announcements/list` |

Responses carry `ok`, `ts` and `simulated`. Moonraker answers are cached for 4 s so several browsers cost one request.

### Alerts

| id | Severity | Notified | Condition |
|---|---|---|---|
| `throttle:undervoltage` | critical | yes | `throttled_state` bit 0 set now (Raspberry Pi only) |
| `throttle:throttled` | warning | yes | frequency capped / throttled / temperature limit set now |
| `throttle:history` | info | no | the "since boot" bits are set |
| `moonraker:outdated` | warning | yes | Moonraker older than the minimum version |
| `component:<name>` | warning | yes | `server/info` lists it in `failed_components` |
| `update:<component>:<remote version>` / `update:system` | info | yes | update_manager reports something newer |
| `announcement:<entry id>` | warning (high priority) / info | high priority only | non-dismissed Moonraker announcement |

**Minimum Moonraker version: `v0.9.0`.** It is the first release line with the sqlite database (backup/restore API)
and the `machine/update/upgrade` endpoint (API 1.5.0). Older versions still work, with the legacy update
endpoints and "not available" for backups, but get the "outdated" warning. Change it with
`INDUS3D_MIN_MOONRAKER`.

## `host_alerts` plugin

Raises the notifiable alerts above as notifications (Discord / Telegram / browser toast) even when nobody has the page
open. Edge-triggered: a condition notifies once and re-arms when it clears (an update is keyed on the version it would
install, so the next release notifies again). The active set is persisted in the plugin data dir, so restarts do not
repeat notifications. It skips the simulator and unreachable Moonraker without clearing state, and keeps the alerts of a
source whose request failed, so a transient error never "clears and re-notifies". At most 4 notifications per check,
then a summary line. Status: `GET /api/v1/plugins/host_alerts`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `INDUS3D_HOST_ALERTS` | `1` | `0` disables the background check (the page and `/alerts` still work). |
| `INDUS3D_HOST_ALERTS_INTERVAL_S` | `300` | Check period, minimum 30. |
| `INDUS3D_MIN_MOONRAKER` | `v0.9.0` | Oldest Moonraker without the "outdated" alert. |
| `INDUS3D_SELF_SERVICE` | `indus3d` | Comma-separated service-name prefixes that serve Indus3D itself (`indus3d` also matches `indus3d-backend`). Stopping one needs `confirm_self`. Set it to your real unit name if it differs (e.g. on NixOS). |
| `INDUS3D_PLUGIN_DATA` | plugin default | Where the plugin keeps `host_alerts.json`. |

## Frontend

`SystemPage.jsx` with panels in `src/system/`, state in `slices/systemSlice.js`. Tabs: Host, MCUs, Services,
Updates, Backups, Devices, with the alert banners above them (critical ones cannot be closed). Data is polled only
while the page is mounted and the browser tab is visible: alerts every 60 s plus the visible tab (host 10 s, services
15 s, backups/devices 30 s, updates 60 s or every 5 s while an update runs), at most about 20 requests a minute.
Confirmation dialogs guard every state-changing button; Klipper/Moonraker actions and updates are also disabled in the
UI while the printer is printing or paused (the backend enforces it regardless). Settings → Machine links to the page.

## Untested against a real Moonraker

Only mocked Moonraker responses and the simulator were available. Worth checking on the real host:

* `machine/services/*` under your Moonraker's service provider and PolicyKit rules (a refusal surfaces as a `502` with Moonraker's message).
* The blocking `machine/update/upgrade` request: how long it stays open for Klipper/Moonraker, and that a Moonraker restart during it ends the job as `unknown` (the status poll then shows the truth).
* `server/database/*` on your version (the `backups` key is the capability test) and the restore restart.
* `printer/objects/query` of `mcu` objects (field names `mcu_version`, `mcu_constants`, `last_stats` are Klipper's).
* `throttled_state` and `system_memory` in `proc_stats` (older Moonraker lacks `system_memory`; the card then uses the `system_info` total only).
* The `by-id` paths on a NixOS host, and that `INDUS3D_SELF_SERVICE` matches your unit name.
* `usb_link_health` measures the machine running Indus3D; if Moonraker runs on another host its suspects do not describe the printer's USB.
