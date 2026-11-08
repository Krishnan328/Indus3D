# Indus3D Multi-Distribution Packaging & Installation Guide

Indus3D provides two official distribution channels tailored to different host operating systems and Klipper deployment philosophies:

1. **Debian / Raspberry Pi OS / Ubuntu**: Managed via the **KIAUH Extension System** or a standalone installation script with Moonraker Update Manager integration.
2. **NixOS**: Managed declaratively via a **Nix Flake** and the official `services.indus3d` NixOS module with systemd sandboxing.

---

## 1. Debian / Raspberry Pi OS (KIAUH & APT)

For standard Raspberry Pi or Debian SBC setups where Klipper was installed via KIAUH:

### Option A: Install via KIAUH Extension (Recommended for KIAUH Users)
Register the extension from a local checkout of the public preview branch:

```bash
git clone --branch codex/packaging-fixes https://github.com/Krishnan328/Indus3D.git ~/indus3d
cd ~/indus3d
bash integrations/kiauh/install-extension.sh
```

Once linked:
1. Launch KIAUH:
   ```bash
   ./kiauh/kiauh.sh
   ```
2. Navigate to **`[E]xtensions`** in the main menu.
3. Select **`Indus3D`** -> **`[1] Install`**.

KIAUH will automatically:
* Provision Python 3 virtual environment in `~/indus3d/backend/.venv`.
* Install all wheel dependencies (`pyserial`, `opencv`, `requests`, `numpy`, etc.).
* Build the dashboard using `npm ci` and `npm run build`.
* Build the Rust DSP binary (`indus3d-dsp`) with its committed Cargo lockfile.
* Register and start `indus3d.service` on port `5001`.
* Add Moonraker's `[update_manager indus3d]` entry into `moonraker.conf` for 1-click updates from Mainsail/Fluidd.
* Include `indus3d.cfg` macros in `printer.cfg`.

The extension is registered under `<kiauh checkout>/kiauh/extensions/indus3d`
with menu index 99. If another local extension uses that index, choose an unused
index in the installed `metadata.json` and restart KIAUH.

The Debian installer provisions Node/npm and Rust/Cargo through APT. Node.js
20.19+ or 22.12+ and a Cargo toolchain supporting the committed lockfile are
required. Older distribution packages may need upgrading separately; a failed
build stops installation instead of starting an incomplete service. There is
no Python vibration-DSP fallback. Run installation and service restarts only
while the printer is idle.

Updates use a fast-forward merge and refuse local modifications, including
tracked printer configuration. Back up and commit/move those edits before
updating; do not discard them to satisfy the check. The Moonraker dependency
hook rebuilds Python dependencies, the dashboard, and DSP without resetting
Git history. Uninstall backs up each changed config file and removes only the
Indus3D update-manager section and exact Klipper include line.

### Option B: Standalone Debian Installer (No KIAUH Required)
If you do not use KIAUH, install Indus3D directly:

```bash
git clone --branch codex/packaging-fixes https://github.com/Krishnan328/Indus3D.git ~/indus3d
cd ~/indus3d
./install.sh
```

To uninstall:
```bash
cd ~/indus3d && ./uninstall.sh
```

---

## 2. NixOS (Declarative Nix Flake & Module)

For immutable, reproducible systems (such as `nixos-ks`):

### Flake Outputs
Indus3D's `flake.nix` exports:
* `packages.<system>.indus3d`: The complete Python backend bundled with ffmpeg, frontend dist, and Rust DSP binary.
* `packages.<system>.indus3d-dsp`: The Rust 1000Hz FFT acceleration binary (`indus3d-dsp`).
* `packages.<system>.indus3d-frontend`: The Vite/React Three.js production web bundle.
* `nixosModules.indus3d`: Declarative systemd service module.

### Configuration (`/etc/nixos/configuration.nix` or host flake)
Add Indus3D to your host flake inputs:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    indus3d.url = "github:Krishnan328/Indus3D?ref=codex/packaging-fixes";
  };

  outputs = { self, nixpkgs, indus3d, ... }: {
    nixosConfigurations.nixos-ks = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        indus3d.nixosModules.indus3d
        {
          services.indus3d = {
            enable = true;
            port = 5001;
            address = "0.0.0.0";
            openFirewall = true;
            # Existing Klipper/Moonraker services are configured separately.
            klipperIntegration = false;
            moonrakerIntegration = false;
            moonrakerHost = "127.0.0.1";
            moonrakerPort = 7125;
          };
        }
      ];
    };
  };
}
```

This is the Indus3D portion of a host configuration, not a replacement for
hardware/boot/filesystem configuration. Keep those host modules in `modules`.
If you want automatic Klipper/Moonraker integration instead, explicitly enable
both NixOS services and supply your printer-specific configuration.

### Applying Changes
```bash
sudo nixos-rebuild switch --flake .#nixos-ks
```

### Automated Remote Deployment & Health Verification
For developers deploying from a workstation to the NixOS host:
```bash
./scripts/deploy_and_verify.sh
```
This script compiles frontend assets, rsyncs codebase changes, applies the Nix flake, restarts services, and executes `scripts/check_system_stability.py` across 22 hardware and bus checks.

---

## Architecture Comparison

| Feature | Debian / KIAUH Package | NixOS Package |
|---|---|---|
| **Target OS** | Raspberry Pi OS, Ubuntu, Debian SBCs | NixOS (x86_64, aarch64) |
| **Package Management** | APT + Python Virtualenv + Cargo | Nix Store (`/nix/store`) + Flake |
| **Service Execution** | Standard Systemd (`indus3d.service`) | Hardened NixOS Systemd Sandbox (`ProtectSystem = strict`) |
| **Updates** | Mainsail/Fluidd Update Manager or `kiauh.sh` | Declarative flake lock update (`nix flake update`) |
| **DSP Acceleration** | Built via local `cargo` during install | Built reproducibly via `rustPlatform.buildRustPackage` |
| **Frontend Serving** | Served via Python API or optional Nginx proxy | Bundled into derivation or served via `frontendPackage` |
