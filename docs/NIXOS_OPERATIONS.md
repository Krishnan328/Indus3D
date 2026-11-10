# Indus3D NixOS operations

This guide keeps deployment, secret handling, recovery, and calibration safety
separate from ordinary dashboard use on a self-hosted Klipper/Moonraker host.

## Deploy safely

Build before switching a running printer host. A build changes nothing on the
machine; a switch activates the new system generation and may restart services.

```bash
cd /etc/nixos
sudo nixos-rebuild build --flake .#nixos-ks
sudo nixos-rebuild switch --flake .#nixos-ks
systemctl status indus3d.service
```

The Nix package builds the locked frontend from `frontend/package-lock.json`;
it does not require a locally generated `frontend/dist` directory. CI runs
`nix flake check`, which builds both the frontend and Indus3D package.

After a switch, verify read-only state first:

```bash
curl -fsS http://127.0.0.1:5001/api/v1/health
systemctl is-active indus3d.service
journalctl -u indus3d.service -n 80 --no-pager
```

Deployment and health checks never authorize heater, motion, homing, or
calibration commands.

## Secrets

Keep credentials out of Git, the Nix store, screenshots, and service logs.
Use an `EnvironmentFile` outside the source tree with mode `0600`:

```ini
# /var/lib/indus3d/indus3d.env
INDUS3D_PASSWORD=replace-with-a-strong-local-password
FLASK_SECRET_KEY=replace-with-a-random-secret
```

```nix
services.indus3d.environmentFile = "/var/lib/indus3d/indus3d.env";
```

Create or rotate secrets with a root-owned editor or secret manager; do not
echo values into shell history. Then restrict the file with `chmod 600` and
restart only the service: `sudo systemctl restart indus3d.service`.

## Backup and recovery

Before a system switch or calibration campaign, back up mutable state and the
NixOS configuration. Stop Indus3D briefly for a consistent SQLite copy:

```bash
sudo systemctl stop indus3d.service
sudo install -d -m 0700 /var/backups/indus3d
sudo cp -a /var/lib/indus3d /var/backups/indus3d/indus3d-$(date +%Y%m%d-%H%M%S)
sudo systemctl start indus3d.service
sudo cp -a /etc/nixos /var/backups/indus3d/nixos-$(date +%Y%m%d-%H%M%S)
```

If a new generation is unhealthy, inspect logs first. Roll back only after
confirming the target generation:

```bash
sudo nixos-rebuild switch --rollback
systemctl status indus3d.service
```

To restore state, stop the service, replace only intended backed-up files
inside `/var/lib/indus3d`, verify ownership and mode, then restart. Never
restore over an actively written database. Recovery does not authorize printer
motion or heater commands.

## Calibration safety model

Indus3D's **Controlled calibration** screen is analysis-first. It checks that
Klipper is ready and no job is active, then requires an operator at the
printer, a clear bed/nozzle path, accessible emergency stop, confirmation of
no active or paused job, and an Indus3D profile snapshot for rollback
comparison.

It may collect passive telemetry and analyze results. For mesh, PID, input
shaping, flow, pressure advance, and first-layer work, it creates a review
plan only. It never uploads G-code, queues a job, sends a command, or persists
a Klipper setting. Offline lab artifacts retain their `.review` extension until
a human validates and approves them.

A final validation print requires a report path and confirmation that the
finished part was inspected. Persistence approval is an audit record, not
automatic configuration writing. Apply resulting settings manually through the
printer's supervised configuration workflow, retain the rollback snapshot, and
verify another print before treating calibration as complete.
