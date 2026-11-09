# Parity hardening: verification and release gates

This patch starts from public parity commit `017f106` and brings in the earlier
unpublished safety patch. It is a reliability improvement, not a claim of complete
Mainsail/Fluidd equivalence or hardware certification.

## Corrected behavior

- Explicit live/simulator identity replaces command-injection capability as a mode check.
- Approval rechecks current filters, autopilot, job identity and fresh state. Pause/idle
  ticks update approval state even when there is no quality-control cycle.
- A command-filter exception or invalid return blocks corrections while retaining emergency
  commands. Vetoes are reported instead of being treated as applied adjustments.
- Bed crash holds survive loss of telemetry until a connected hub clears the latch.
- Pausing/resuming retains job history, run identity, timelapse and consumption baselines.
- Real Klipper `// action:prompt_...` messages are recognized. Prompt commands report
  rejection, remain reviewable on failure, and are claimed once before dispatch. New prompt
  IDs prevent stale browser clicks from answering a replacement dialog.
- Filament, M73 and hardware status fields survive backend snapshots and frontend ingestion.
- History recognizes both existing `complete` and legacy `completed` records.
- Reprints validate paths, refuse active jobs/simulation, and surface Klipper rejection.
- Settings sync reads the specific key it writes, validates payloads, and reports whether
  changes were saved remotely, locally only, or not at all.
- Navigation fetches a fresh shell online, retains offline fallback, and never caches
  printer APIs or external camera traffic. Cache cleanup is limited to Indus3D-owned caches.
- Container database, config, session key and timelapses use the mounted data directory.
  Health checks work with authentication enabled; local credentials/runtime data are excluded
  from the build context.
- Spool identifiers are bounded integers, rejected remote changes are not persisted, and
  filament ETA no longer compares length with mass.

## Deliberately gated features

The ESP automatic resonance sweep remains disabled. Its previous shell command completed
capture before starting motion. Re-enabling it requires synchronized capture, full-sweep
sample coverage and supervised hardware validation. Offline analysis remains available.

The multi-material panel displays actual available status only. It does not fabricate gates
or call nonexistent store actions. Generic load/eject commands have been removed; firmware
specific operations require verified command schemas and real Happy Hare/AFC test fixtures.
Do not interpret the status panel as validated MMU control.

The direct-Klipper transport proposal remains deferred. No hardware bypass is introduced here.

## Local verification

The backend/hub regression suite, frontend unit suite, production build, fatal Python lint
checks and secret-scanner controls are run separately. Fixtures use temporary databases,
fake Moonraker responses and simulated hub data; no real printer actions are involved.
Container tests check configuration contracts, not actual image startup or volume recreation.

The browser smoke-test attempt was blocked because the browser automation environment has
no configured Chrome installation. Docker and Nix are also unavailable locally. Those checks
must not be marked passed on the strength of unit tests or a frontend build.

The pre-existing frontend dependency audit reported eight high-severity advisories before this
patch. Lockfile/dependency upgrades are not included here: update and test them separately,
including the Nix npm dependency hash, before release.

## Before a production release

1. Review the patch, commit it and run public CI, including secret scanning and Nix checks.
2. Complete dependency remediation and browser checks against a mocked backend: offline,
   slow/rejected requests, reconnect, prompt replacement, settings fallback and fresh deployment.
3. Build the container; verify authenticated startup, persistence after recreation and a clean
   build context. Verify the actual Nix service configuration separately.
4. Exercise supported camera protocols, LDAP configuration, MMU/AFC status schemas and
   per-tool spool assignments against their real integrations. These are not all covered
   end-to-end by the current fixtures.
5. Obtain explicit approval for a supervised printer session. Check readiness, no active job,
   homing, cold-extrusion refusal, pause/resume, manual Mainsail overrides and sensor disconnects.
   Preserve rollback configuration. Approve any tuning/persistence operation separately.

No universal latency, CPU or print-quality improvement has been established. Use comparable
workloads and measurements before making performance or parity claims.
