#!/usr/bin/env bash
# ==============================================================================
# Seamless Pico 2 (RP2350) Flasher for NixOS, Linux, and macOS
# Automatically handles software reboot, flashing, and restart without BOOTSEL.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_UF2="${SCRIPT_DIR}/build_pico2/smart_filament_sensor.uf2"
UF2_FILE="${1:-$DEFAULT_UF2}"

if [ ! -f "$UF2_FILE" ]; then
    echo "Error: Firmware file not found: $UF2_FILE"
    echo "Usage: $0 [path/to/firmware.uf2]"
    exit 1
fi

echo "=================================================="
echo " Flashing Pico 2 (RP2350) Firmware"
echo " Target: $UF2_FILE"
echo "=================================================="

# Check if picotool is natively in PATH
if command -v picotool >/dev/null 2>&1; then
    PICOTOOL_CMD="picotool"
# If running on NixOS / Nix system without picotool installed
elif command -v nix >/dev/null 2>&1; then
    echo "picotool not in PATH, using Nix (nix run nixpkgs#picotool)..."
    PICOTOOL_CMD="nix run nixpkgs#picotool --"
elif command -v nix-shell >/dev/null 2>&1; then
    echo "picotool not in PATH, using nix-shell..."
    PICOTOOL_CMD="nix-shell -p picotool --run picotool"
else
    echo "Error: picotool is not installed and Nix was not detected."
    echo "On NixOS: Add 'picotool' to environment.systemPackages or run:"
    echo "  nix-shell -p picotool --run \"$0 $UF2_FILE\""
    exit 1
fi

echo "Sending reboot signal and flashing firmware..."
$PICOTOOL_CMD load -f -x --ignore-partitions "$UF2_FILE"

echo ""
echo "Firmware successfully loaded! Pico 2 has rebooted into application mode."
