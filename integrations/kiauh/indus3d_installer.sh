#!/usr/bin/env bash
# ==============================================================================
# Indus3D Debian & KIAUH Integration Installer
# Installs, updates, removes, and monitors Indus3D on Debian / Ubuntu / Pi OS
# ==============================================================================

set -euo pipefail

# Color Codes
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

initialize_paths() {
    TARGET_USER="${SUDO_USER:-$(id -un)}"
    USER_HOME="$(python3 -c 'import pwd,sys; print(pwd.getpwnam(sys.argv[1]).pw_dir)' "$TARGET_USER")"
    if [ -f "${SCRIPT_DIR}/../../backend/main.py" ]; then
        INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
    else
        INSTALL_DIR="${USER_HOME}/indus3d"
    fi
    SYSTEMD_FILE="/etc/systemd/system/indus3d.service"
    KLIPPER_CONFIG_DIR="${USER_HOME}/printer_data/config"
    MOONRAKER_CONF="${KLIPPER_CONFIG_DIR}/moonraker.conf"
    PRINTER_CFG="${KLIPPER_CONFIG_DIR}/printer.cfg"
    REPO_URL="https://github.com/Krishnan328/Indus3D.git"
    REPO_BRANCH="codex/packaging-fixes"
}

echo_info() { echo -e "${CYAN}[INDUS3D]${NC} $1"; }
echo_ok()   { echo -e "${GREEN}[✔ OK]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[▲ WARN]${NC} $1"; }
echo_err()  { echo -e "${RED}[✖ ERR]${NC} $1"; }

require_root_or_sudo() {
    if [ "$EUID" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
        echo_err "This command requires sudo or root privileges."
        exit 1
    fi
}

run_as_user() {
    if [ "$EUID" -eq 0 ]; then
        sudo -H -u "${TARGET_USER}" "$@"
    else
        "$@"
    fi
}

install_system_deps() {
    echo_info "Installing Debian system prerequisites via apt..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y --no-install-recommends \
            python3 python3-venv python3-pip \
            ffmpeg curl git build-essential \
            libatlas-base-dev libopenblas-dev \
            pkg-config libssl-dev nodejs npm cargo rustc
        echo_ok "System dependencies installed."
    else
        echo_err "This installer requires Debian/Ubuntu/Raspberry Pi OS. Use the Nix module on NixOS."
        return 1
    fi
}

setup_codebase() {
    if [ ! -d "${INSTALL_DIR}" ]; then
        echo_info "Cloning Indus3D repository to ${INSTALL_DIR}..."
        run_as_user git clone --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
    else
        echo_info "Indus3D directory already exists at ${INSTALL_DIR}."
    fi
}

setup_python_env() {
    echo_info "Configuring Python virtual environment in ${INSTALL_DIR}/backend/.venv..."
    run_as_user bash -euc '
        cd "$1/backend"
        if [ ! -d .venv ]; then
            python3 -m venv .venv
        fi
        source .venv/bin/activate
        pip install --upgrade pip setuptools wheel
        pip install -r requirements.txt
    ' _ "$INSTALL_DIR"
    echo_ok "Python environment configured."
}

build_frontend() {
    echo_info "Building the dashboard from the locked frontend dependencies..."
    run_as_user bash -euc '
        cd "$1/frontend"
        node -e '\''const [major, minor] = process.versions.node.split(".").map(Number);
            if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) {
                console.error("Node.js 20.19+ or 22.12+ is required; install a supported Node version and retry.");
                process.exit(1);
            }'\''
        npm ci --include=dev
        npm run build
        test -s dist/index.html
    ' _ "$INSTALL_DIR"
}

build_rust_dsp() {
    echo_info "Checking Rust DSP acceleration engine..."
    if command -v cargo >/dev/null 2>&1; then
        echo_info "Building high-performance indus3d-dsp binary..."
        run_as_user bash -euc 'cd "$1/backend/dsp"; cargo build --release --locked; test -x target/release/indus3d-dsp' _ "$INSTALL_DIR"
        echo_ok "Rust DSP binary built at backend/dsp/target/release/indus3d-dsp."
    else
        echo_err "Cargo is required to build vibration DSP; no Python fallback exists. Install a current Rust toolchain and retry."
        return 1
    fi
}

setup_systemd_service() {
    echo_info "Registering Indus3D systemd service..."
    cat << EOF | sudo tee "${SYSTEMD_FILE}" >/dev/null
[Unit]
Description=Indus3D Digital Twin and Quality Controller
After=network-online.target moonraker.service klipper.service
Wants=network-online.target moonraker.service

[Service]
Type=simple
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${INSTALL_DIR}/backend
ExecStart=${INSTALL_DIR}/backend/.venv/bin/python main.py
Restart=always
RestartSec=5
SupplementaryGroups=dialout
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable indus3d.service
    sudo systemctl restart indus3d.service
    echo_ok "Indus3D service created and started."
}

configure_moonraker_update_manager() {
    if [ -f "${MOONRAKER_CONF}" ]; then
        echo_info "Configuring Moonraker Update Manager in ${MOONRAKER_CONF}..."
        if ! grep -q "\[update_manager indus3d\]" "${MOONRAKER_CONF}"; then
            cat << EOF | sudo tee -a "${MOONRAKER_CONF}" >/dev/null

[update_manager indus3d]
type: git_repo
path: ${INSTALL_DIR}
origin: ${REPO_URL}
primary_branch: ${REPO_BRANCH}
is_system_service: True
install_script: integrations/kiauh/refresh_dependencies.sh
managed_services: indus3d
EOF
            echo_ok "Added [update_manager indus3d] to moonraker.conf."
            sudo systemctl restart moonraker.service 2>/dev/null || true
        else
            echo_ok "Moonraker update manager entry already present."
        fi
    fi
}

configure_klipper_macros() {
    if [ -f "${PRINTER_CFG}" ]; then
        echo_info "Wiring Indus3D integration macros into ${PRINTER_CFG}..."
        run_as_user cp "${INSTALL_DIR}/indus3d.cfg" "${KLIPPER_CONFIG_DIR}/indus3d.cfg"
        if ! grep -q "\[include indus3d.cfg\]" "${PRINTER_CFG}"; then
            cat << EOF | sudo tee -a "${PRINTER_CFG}" >/dev/null

# Indus3D Digital Twin Integration
[include indus3d.cfg]
EOF
            echo_ok "Added [include indus3d.cfg] to printer.cfg."
        fi
    fi
}

do_install() {
    echo_info "Starting Indus3D installation for user ${TARGET_USER}..."
    install_system_deps
    setup_codebase
    setup_python_env
    build_frontend
    build_rust_dsp
    setup_systemd_service
    configure_moonraker_update_manager
    configure_klipper_macros

    echo ""
    echo -e "${GREEN}===================================================================${NC}"
    echo -e "${GREEN}   🎉 Indus3D Successfully Installed & Running!                    ${NC}"
    echo -e "${GREEN}===================================================================${NC}"
    echo_info "Dashboard Web UI:     http://<your-printer-ip>:5001"
    echo_info "REST & WebSocket API: http://<your-printer-ip>:5001/api/v1/telemetry"
    echo_info "Systemd Service:      sudo systemctl status indus3d.service"
}

do_update() {
    echo_info "Updating Indus3D codebase..."
    update_codebase
    refresh_dependencies
    sudo systemctl restart indus3d.service
    echo_ok "Indus3D updated and service restarted successfully."
}

update_codebase() {
    run_as_user bash -euc '
        cd "$1"
        if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
            echo "Refusing update: checkout has local changes. Back up/commit configuration and other edits before retrying." >&2
            exit 1
        fi
        if [ "$(git symbolic-ref --short HEAD)" != "$2" ]; then
            echo "Refusing update: check out the configured branch before retrying." >&2
            exit 1
        fi
        git fetch origin "$2"
        git merge --ff-only "origin/$2"
    ' _ "$INSTALL_DIR" "$REPO_BRANCH"
}

refresh_dependencies() {
    setup_python_env
    build_frontend
    build_rust_dsp
}

do_remove() {
    echo_info "Uninstalling Indus3D..."
    sudo systemctl stop indus3d.service 2>/dev/null || true
    sudo systemctl disable indus3d.service 2>/dev/null || true
    sudo rm -f "${SYSTEMD_FILE}"
    sudo systemctl daemon-reload

    if [ -f "${MOONRAKER_CONF}" ]; then
        sudo python3 "${SCRIPT_DIR}/config_file.py" "$MOONRAKER_CONF" "update_manager indus3d"
        sudo systemctl restart moonraker.service 2>/dev/null || true
    fi

    if [ -f "${PRINTER_CFG}" ]; then
        sudo python3 "${SCRIPT_DIR}/config_file.py" "$PRINTER_CFG" "include indus3d.cfg"
    fi

    echo_ok "Indus3D service removed. (Code directory ${INSTALL_DIR} preserved; delete manually if desired)."
}

do_status() {
    echo -e "${CYAN}=== Indus3D Status ===${NC}"
    if systemctl is-active --quiet indus3d.service; then
        echo_ok "Service: Running (active)"
        if command -v curl >/dev/null 2>&1; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5001/api/v1/health || echo "000")
            if [ "${HTTP_CODE}" = "200" ]; then
                echo_ok "API Health: 200 OK (http://127.0.0.1:5001)"
            else
                echo_warn "API Health: HTTP ${HTTP_CODE} on port 5001"
            fi
        fi
    else
        echo_err "Service: Inactive or Stopped"
    fi
}

main() {
    initialize_paths
    ACTION="${1:-status}"
    if [ "$ACTION" != status ]; then
        if [ "$TARGET_USER" = root ]; then
            echo_err "Run as the normal printer user, not root."
            return 1
        fi
        require_root_or_sudo
    fi
    case "${ACTION}" in
        install|setup) do_install ;;
        update) do_update ;;
        remove|uninstall) do_remove ;;
        status) do_status ;;
        refresh-dependencies) refresh_dependencies ;;
        start|stop|restart) sudo systemctl "$ACTION" indus3d.service ;;
        *)
            echo "Usage: $0 {install|update|remove|status|start|stop|restart|refresh-dependencies}"
            return 1
            ;;
    esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
