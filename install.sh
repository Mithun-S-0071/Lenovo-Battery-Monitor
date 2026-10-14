#!/usr/bin/env bash
set -e

# ==============================================================================
# Lenovo Battery Monitor - Clone & Install Script
# Works across Ubuntu, Debian, Arch Linux, Fedora, openSUSE, and any systemd Linux
# ==============================================================================

# Determine project root (works from repo root or release/ subdirectory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/setup.py" ]; then
    PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../setup.py" ]; then
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    echo "Error: Cannot locate project root directory containing setup.py."
    exit 1
fi

echo "=========================================================="
echo "    Lenovo Battery Monitor - Simple Installer"
echo "=========================================================="

# Parse command line flags
MODE=""
for arg in "$@"; do
    case "$arg" in
        --system)
            MODE="system"
            ;;
        --user)
            MODE="user"
            ;;
        --help|-h)
            echo "Usage: ./install.sh [OPTION]"
            echo ""
            echo "Options:"
            echo "  --system    Install system-wide into /usr/local & /opt (requires sudo/root)"
            echo "  --user      Install for current user only into ~/.local (no root required)"
            echo "  --help      Show this help message"
            echo ""
            echo "If run without options, an interactive prompt will ask, or default to"
            echo "system-wide if run as root, or user-local if run without root."
            exit 0
            ;;
    esac
done

# Determine installation mode:
# - Run as regular user: installs directly to ~/.local (no root needed, zero friction)
# - Run as root (sudo ./install.sh): installs system-wide to /usr/local & /opt
if [ -z "$MODE" ]; then
    if [ "$EUID" -eq 0 ]; then
        MODE="system"
    else
        MODE="user"
    fi
fi

# If system mode was explicitly requested but not running as root, re-exec with sudo
if [ "$MODE" == "system" ] && [ "$EUID" -ne 0 ]; then
    echo "System-wide installation requires administrator privileges."
    echo "Requesting sudo access..."
    exec sudo bash "$0" --system
fi

# Detect Linux Distribution
DISTRO="unknown"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO="${ID:-unknown}"
fi

echo "Detected OS: ${NAME:-$DISTRO} ($DISTRO)"
echo "Installation Mode: $MODE"
echo ""

# ------------------------------------------------------------------------------
# 1. Check & Prepare Python Environment
# ------------------------------------------------------------------------------
PYTHON_EXEC="python3"
if ! command -v "$PYTHON_EXEC" >/dev/null 2>&1; then
    echo "Error: Python 3 is not installed. Please install python3 first."
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_EXEC" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Found Python: $PYTHON_EXEC ($PYTHON_VERSION)"

# Check if PySide6 is available
PYSIDE_INSTALLED=false
if "$PYTHON_EXEC" -c "import PySide6" >/dev/null 2>&1; then
    PYSIDE_INSTALLED=true
elif [ -f "$PROJECT_ROOT/.venv/bin/python" ] && "$PROJECT_ROOT/.venv/bin/python" -c "import PySide6" >/dev/null 2>&1; then
    PYTHON_EXEC="$PROJECT_ROOT/.venv/bin/python"
    PYSIDE_INSTALLED=true
fi

# Attempt automatic PySide6 installation if missing
if [ "$PYSIDE_INSTALLED" = false ]; then
    echo ""
    echo "PySide6 Qt6 bindings are not detected in the current Python environment."
    echo "Attempting to install PySide6..."

    if [ "$MODE" == "system" ] && [ "$EUID" -eq 0 ]; then
        case "$DISTRO" in
            ubuntu|debian|linuxmint|pop|zorin|elementary)
                echo "Installing python3-pyside6 via apt..."
                apt-get update -qq || true
                apt-get install -y python3-pyside6.qtwidgets python3-pyside6 policykit-1 || true
                ;;
            fedora|rhel|centos|rocky|almalinux)
                echo "Installing python3-pyside6 via dnf..."
                dnf install -y python3-pyside6 polkit || true
                ;;
            arch|manjaro|endeavouros|steamos|garuda)
                echo "Installing pyside6 via pacman..."
                pacman -S --needed --noconfirm pyside6 polkit || true
                ;;
            opensuse*|suse)
                echo "Installing python3-pyside6 via zypper..."
                zypper install -y python3-pyside6 polkit || true
                ;;
        esac
    fi

    # Check if system package manager succeeded
    if "$PYTHON_EXEC" -c "import PySide6" >/dev/null 2>&1; then
        PYSIDE_INSTALLED=true
        echo "✓ PySide6 successfully installed via system package manager!"
    else
        # Set up a dedicated virtual environment fallback
        echo "Setting up a dedicated application virtual environment for PySide6..."
        if [ "$MODE" == "system" ]; then
            VENV_DIR="/opt/lenovo-conservation/venv"
        else
            VENV_DIR="$HOME/.local/share/lenovo-conservation/venv"
        fi

        mkdir -p "$(dirname "$VENV_DIR")"
        if [ ! -d "$VENV_DIR" ]; then
            python3 -m venv "$VENV_DIR" || {
                echo "Warning: python3-venv might not be installed."
                if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                    echo "Please install python3-venv: sudo apt install python3-venv"
                fi
            }
        fi

        if [ -f "$VENV_DIR/bin/pip" ]; then
            echo "Installing PySide6 into dedicated environment ($VENV_DIR)..."
            "$VENV_DIR/bin/pip" install --upgrade pip
            "$VENV_DIR/bin/pip" install PySide6
            PYTHON_EXEC="$VENV_DIR/bin/python"
            PYSIDE_INSTALLED=true
            echo "✓ PySide6 successfully installed in $VENV_DIR!"
        fi
    fi
fi

if [ "$PYSIDE_INSTALLED" = false ]; then
    echo "Warning: PySide6 could not be automatically configured."
    echo "You can install it manually using:"
    echo "  Ubuntu/Debian: sudo apt install python3-pyside6.qtwidgets"
    echo "  Fedora:        sudo dnf install python3-pyside6"
    echo "  Arch:          sudo pacman -S pyside6"
    echo "  Pip:           pip install PySide6"
    echo "Continuing installation..."
fi

# ------------------------------------------------------------------------------
# 2. Installation Implementation
# ------------------------------------------------------------------------------

if [ "$MODE" == "system" ]; then
    PREFIX="/usr/local"
    BIN_DIR="$PREFIX/bin"
    LIBEXEC_DIR="/usr/libexec"
    SHARE_DIR="$PREFIX/share"
    APP_DIR="$SHARE_DIR/applications"
    ICON_DIR="$SHARE_DIR/icons/hicolor"
    POLKIT_DIR="/usr/share/polkit-1/actions"
    SYSTEMD_DIR="/usr/lib/systemd/system"
    INSTALL_TARGET="/opt/lenovo-conservation"

    # Fallback systemd location if /usr/lib/systemd/system doesn't exist
    if [ ! -d "$SYSTEMD_DIR" ] && [ -d "/etc/systemd/system" ]; then
        SYSTEMD_DIR="/etc/systemd/system"
    fi

    echo "Installing system-wide into $PREFIX & $INSTALL_TARGET..."

    mkdir -p "$BIN_DIR" "$LIBEXEC_DIR" "$APP_DIR" "$POLKIT_DIR" "$SYSTEMD_DIR" "$INSTALL_TARGET"
    mkdir -p "$ICON_DIR/scalable/apps" "$ICON_DIR/128x128/apps" "$ICON_DIR/64x64/apps" "$ICON_DIR/48x48/apps" "$ICON_DIR/32x32/apps" "$ICON_DIR/256x256/apps"

    # Copy application package files
    rm -rf "$INSTALL_TARGET/lenovo_conservation"
    cp -r "$PROJECT_ROOT/lenovo_conservation" "$INSTALL_TARGET/"
    cp -r "$PROJECT_ROOT/bin" "$INSTALL_TARGET/"
    chmod +x "$INSTALL_TARGET/bin/"*

    # Copy privileged helper to /usr/libexec and /usr/local/libexec for Polkit
    cp "$PROJECT_ROOT/bin/lenovo-conservation-helper" "$LIBEXEC_DIR/lenovo-conservation-helper"
    chmod 755 "$LIBEXEC_DIR/lenovo-conservation-helper"
    mkdir -p "/usr/local/libexec"
    ln -sf "$LIBEXEC_DIR/lenovo-conservation-helper" "/usr/local/libexec/lenovo-conservation-helper"

    # Create binary launcher wrappers
    cat << EOF > "$BIN_DIR/lenovo-battery-monitor"
#!/usr/bin/env bash
export PYTHONPATH="$INSTALL_TARGET:\$PYTHONPATH"
exec "$PYTHON_EXEC" -m lenovo_conservation.main "\$@"
EOF
    chmod 755 "$BIN_DIR/lenovo-battery-monitor"
    ln -sf "$BIN_DIR/lenovo-battery-monitor" "$BIN_DIR/lenovo-conservation"

    cat << EOF > "$BIN_DIR/lenovo-conservation-daemon"
#!/usr/bin/env bash
export PYTHONPATH="$INSTALL_TARGET:\$PYTHONPATH"
exec "$PYTHON_EXEC" -m lenovo_conservation.service "\$@"
EOF
    chmod 755 "$BIN_DIR/lenovo-conservation-daemon"

    # Install Desktop launcher
    cat << EOF > "$APP_DIR/lenovo-battery-monitor.desktop"
[Desktop Entry]
Name=Lenovo Battery Monitor
GenericName=Battery & Conservation Monitor
Comment=Manage battery health, charging thresholds, and conservation mode for Lenovo laptops
Exec=$BIN_DIR/lenovo-battery-monitor
Icon=lenovo-battery-monitor
Terminal=false
Type=Application
Categories=Settings;HardwareSettings;System;
Keywords=battery;health;lenovo;conservation;charge;threshold;ideapad;thinkpad;legion;loq;monitor;capacity;power;
StartupNotify=true
StartupWMClass=lenovo-battery-monitor
X-KDE-SubstituteUID=false
EOF
    chmod 644 "$APP_DIR/lenovo-battery-monitor.desktop"
    ln -sf "$APP_DIR/lenovo-battery-monitor.desktop" "$APP_DIR/lenovo-conservation.desktop"

    # Also link to /usr/share/applications so desktop environments find it immediately
    if [ "$APP_DIR" != "/usr/share/applications" ]; then
        mkdir -p "/usr/share/applications"
        ln -sf "$APP_DIR/lenovo-battery-monitor.desktop" "/usr/share/applications/lenovo-battery-monitor.desktop"
        ln -sf "$APP_DIR/lenovo-conservation.desktop" "/usr/share/applications/lenovo-conservation.desktop"
    fi

    # Install Icons
    cp "$PROJECT_ROOT/data/icons/lenovo-conservation.svg" "$ICON_DIR/scalable/apps/lenovo-battery-monitor.svg"
    cp "$PROJECT_ROOT/data/icons/lenovo-conservation.svg" "$ICON_DIR/scalable/apps/lenovo-conservation.svg"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-256x256.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-256x256.png" "$ICON_DIR/256x256/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-128x128.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-128x128.png" "$ICON_DIR/128x128/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-64x64.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-64x64.png" "$ICON_DIR/64x64/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-48x48.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-48x48.png" "$ICON_DIR/48x48/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-32x32.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-32x32.png" "$ICON_DIR/32x32/apps/lenovo-battery-monitor.png"

    # Also install icons into /usr/share/icons/hicolor
    if [ "$ICON_DIR" != "/usr/share/icons/hicolor" ] && [ -d "/usr/share/icons/hicolor" ]; then
        mkdir -p "/usr/share/icons/hicolor/scalable/apps"
        ln -sf "$ICON_DIR/scalable/apps/lenovo-battery-monitor.svg" "/usr/share/icons/hicolor/scalable/apps/lenovo-battery-monitor.svg"
        ln -sf "$ICON_DIR/scalable/apps/lenovo-conservation.svg" "/usr/share/icons/hicolor/scalable/apps/lenovo-conservation.svg"
    fi

    # Install Polkit policy & systemd service
    install -Dm644 "$PROJECT_ROOT/data/org.lenovo.conservation.policy" "$POLKIT_DIR/org.lenovo.conservation.policy"
    install -Dm644 "$PROJECT_ROOT/data/lenovo-conservation.service" "$SYSTEMD_DIR/lenovo-conservation.service"

    echo "Updating system desktop database and icon caches..."
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" 2>/dev/null || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "/usr/share/applications" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "/usr/share/icons/hicolor" 2>/dev/null || true
    command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 --noincremental 2>/dev/null || true
    command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 --noincremental 2>/dev/null || true

else
    # --------------------------------------------------------------------------
    # User-Local Installation (No sudo required)
    # --------------------------------------------------------------------------
    PREFIX="$HOME/.local"
    BIN_DIR="$PREFIX/bin"
    SHARE_DIR="$PREFIX/share"
    APP_DIR="$SHARE_DIR/applications"
    ICON_DIR="$SHARE_DIR/icons/hicolor"
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    INSTALL_TARGET="$SHARE_DIR/lenovo-conservation"

    echo "Installing for current user ($USER) into $PREFIX..."
    mkdir -p "$BIN_DIR" "$APP_DIR" "$SYSTEMD_USER_DIR" "$INSTALL_TARGET"
    mkdir -p "$ICON_DIR/scalable/apps" "$ICON_DIR/128x128/apps" "$ICON_DIR/64x64/apps" "$ICON_DIR/48x48/apps" "$ICON_DIR/32x32/apps" "$ICON_DIR/256x256/apps"

    # Copy application package files
    rm -rf "$INSTALL_TARGET/lenovo_conservation"
    cp -r "$PROJECT_ROOT/lenovo_conservation" "$INSTALL_TARGET/"
    cp -r "$PROJECT_ROOT/bin" "$INSTALL_TARGET/"
    chmod +x "$INSTALL_TARGET/bin/"*

    # Launcher wrapper in ~/.local/bin
    cat << EOF > "$BIN_DIR/lenovo-battery-monitor"
#!/usr/bin/env bash
export PYTHONPATH="$INSTALL_TARGET:\$PYTHONPATH"
exec "$PYTHON_EXEC" -m lenovo_conservation.main "\$@"
EOF
    chmod 755 "$BIN_DIR/lenovo-battery-monitor"
    ln -sf "$BIN_DIR/lenovo-battery-monitor" "$BIN_DIR/lenovo-conservation"

    cat << EOF > "$BIN_DIR/lenovo-conservation-daemon"
#!/usr/bin/env bash
export PYTHONPATH="$INSTALL_TARGET:\$PYTHONPATH"
exec "$PYTHON_EXEC" -m lenovo_conservation.service "\$@"
EOF
    chmod 755 "$BIN_DIR/lenovo-conservation-daemon"

    # Install Icons
    cp "$PROJECT_ROOT/data/icons/lenovo-conservation.svg" "$ICON_DIR/scalable/apps/lenovo-battery-monitor.svg"
    cp "$PROJECT_ROOT/data/icons/lenovo-conservation.svg" "$ICON_DIR/scalable/apps/lenovo-conservation.svg"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-256x256.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-256x256.png" "$ICON_DIR/256x256/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-128x128.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-128x128.png" "$ICON_DIR/128x128/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-64x64.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-64x64.png" "$ICON_DIR/64x64/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-48x48.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-48x48.png" "$ICON_DIR/48x48/apps/lenovo-battery-monitor.png"
    [ -f "$PROJECT_ROOT/data/icons/lenovo-conservation-32x32.png" ] && cp "$PROJECT_ROOT/data/icons/lenovo-conservation-32x32.png" "$ICON_DIR/32x32/apps/lenovo-battery-monitor.png"

    # Desktop Launcher
    cat << EOF > "$APP_DIR/lenovo-battery-monitor.desktop"
[Desktop Entry]
Name=Lenovo Battery Monitor
GenericName=Battery & Conservation Monitor
Comment=Manage battery health, charging thresholds, and conservation mode for Lenovo laptops
Exec=$BIN_DIR/lenovo-battery-monitor
Icon=lenovo-battery-monitor
Terminal=false
Type=Application
Categories=Settings;HardwareSettings;System;
Keywords=battery;health;lenovo;conservation;charge;threshold;ideapad;thinkpad;legion;loq;monitor;capacity;power;
StartupNotify=true
StartupWMClass=lenovo-battery-monitor
X-KDE-SubstituteUID=false
EOF
    chmod 644 "$APP_DIR/lenovo-battery-monitor.desktop"
    ln -sf "$APP_DIR/lenovo-battery-monitor.desktop" "$APP_DIR/lenovo-conservation.desktop"

    # Install user systemd service
    cat << EOF > "$SYSTEMD_USER_DIR/lenovo-conservation.service"
[Unit]
Description=Lenovo Battery Conservation & Smart 80% Background Service
After=default.target

[Service]
Type=simple
ExecStart=$BIN_DIR/lenovo-conservation-daemon --daemon
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
EOF
    chmod 644 "$SYSTEMD_USER_DIR/lenovo-conservation.service"

    echo "Refreshing desktop database and icon caches..."
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" 2>/dev/null || true
    command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 --noincremental 2>/dev/null || true
    command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 --noincremental 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# 3. Post-Install Check & Output
# ------------------------------------------------------------------------------
echo ""
echo "=========================================================="
echo "  ✓ Lenovo Battery Monitor installed successfully!"
echo "=========================================================="
echo ""
echo "Installation Details:"
echo "  • Launcher Binary:  $BIN_DIR/lenovo-battery-monitor"
echo "  • Desktop Shortcut: $APP_DIR/lenovo-battery-monitor.desktop"
echo "  • Mode:             $MODE"
echo ""

if [ "$MODE" == "user" ]; then
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            echo "Notice: $BIN_DIR is not yet in your PATH."
            echo "You can add it by running:"
            echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
            echo "or adding that line to your ~/.bashrc or ~/.zshrc."
            echo ""
            ;;
    esac
fi

echo "Quick Start:"
echo "  1. Desktop Menu: Search for 'Lenovo Battery Monitor' in your application launcher"
echo "  2. Terminal GUI: Run 'lenovo-battery-monitor'"
echo "  3. CLI Status:   Run 'lenovo-battery-monitor --status'"
echo "  4. Diagnostics:  Run 'lenovo-battery-monitor --diagnostics'"
echo ""

if [ "$MODE" == "system" ]; then
    echo "To enable background monitoring automatically at boot:"
    echo "  sudo systemctl enable --now lenovo-conservation.service"
else
    echo "To enable background monitoring for your user session:"
    echo "  systemctl --user enable --now lenovo-conservation.service"
fi

echo ""
echo "To uninstall anytime:"
echo "  ./uninstall.sh"
echo "=========================================================="
