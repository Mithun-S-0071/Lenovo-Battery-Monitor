#!/usr/bin/env bash
set -e

# ==============================================================================
# Lenovo Battery Monitor - Uninstaller Script
# ==============================================================================

echo "=========================================================="
echo "    Lenovo Battery Monitor - Uninstaller"
echo "=========================================================="

PURGE=false
for arg in "$@"; do
    case "$arg" in
        --purge)
            PURGE=true
            ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [OPTION]"
            echo ""
            echo "Options:"
            echo "  --purge   Also delete saved configuration in ~/.config/lenovo-conservation"
            echo "  --help    Show this help message"
            exit 0
            ;;
    esac
done

echo "Removing Lenovo Battery Monitor components..."

# 1. Stop and disable user background service if active
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop lenovo-conservation.service 2>/dev/null || true
    systemctl --user disable lenovo-conservation.service 2>/dev/null || true
fi

# 2. User installation cleanup
rm -f "$HOME/.local/bin/lenovo-battery-monitor"
rm -f "$HOME/.local/bin/lenovo-conservation"
rm -f "$HOME/.local/bin/lenovo-conservation-daemon"
rm -rf "$HOME/.local/share/lenovo-conservation"
rm -f "$HOME/.local/share/applications/lenovo-battery-monitor.desktop"
rm -f "$HOME/.local/share/applications/lenovo-conservation.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/lenovo-battery-monitor.svg"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/lenovo-conservation.svg"
rm -f "$HOME/.local/share/icons/hicolor/*/apps/lenovo-battery-monitor.png"
rm -f "$HOME/.local/share/icons/hicolor/*/apps/lenovo-conservation.png"
rm -f "$HOME/.config/systemd/user/lenovo-conservation.service"

# 3. System installation cleanup (if root or sudo available)
if [ "$EUID" -eq 0 ]; then
    echo "Cleaning up system-wide files..."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop lenovo-conservation.service 2>/dev/null || true
        systemctl disable lenovo-conservation.service 2>/dev/null || true
    fi

    rm -f "/usr/local/bin/lenovo-battery-monitor"
    rm -f "/usr/local/bin/lenovo-conservation"
    rm -f "/usr/local/bin/lenovo-conservation-daemon"
    rm -f "/usr/libexec/lenovo-conservation-helper"
    rm -f "/usr/local/libexec/lenovo-conservation-helper"
    rm -rf "/opt/lenovo-conservation"
    rm -f "/usr/local/share/applications/lenovo-battery-monitor.desktop"
    rm -f "/usr/local/share/applications/lenovo-conservation.desktop"
    rm -f "/usr/share/applications/lenovo-battery-monitor.desktop"
    rm -f "/usr/share/applications/lenovo-conservation.desktop"
    rm -f "/usr/local/share/icons/hicolor/scalable/apps/lenovo-battery-monitor.svg"
    rm -f "/usr/local/share/icons/hicolor/scalable/apps/lenovo-conservation.svg"
    rm -f "/usr/share/icons/hicolor/scalable/apps/lenovo-battery-monitor.svg"
    rm -f "/usr/share/icons/hicolor/scalable/apps/lenovo-conservation.svg"
    rm -f "/usr/local/share/icons/hicolor/*/apps/lenovo-battery-monitor.png"
    rm -f "/usr/local/share/icons/hicolor/*/apps/lenovo-conservation.png"
    rm -f "/usr/share/icons/hicolor/*/apps/lenovo-battery-monitor.png"
    rm -f "/usr/share/icons/hicolor/*/apps/lenovo-conservation.png"
    rm -f "/usr/share/polkit-1/actions/org.lenovo.conservation.policy"
    rm -f "/usr/lib/systemd/system/lenovo-conservation.service"
    rm -f "/etc/systemd/system/lenovo-conservation.service"
fi

# 4. Optional purge of configuration
if [ "$PURGE" = true ]; then
    echo "Purging configuration files..."
    rm -rf "$HOME/.config/lenovo-conservation"
fi

# 5. Refresh desktop and icon databases
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 --noincremental 2>/dev/null || true
command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 --noincremental 2>/dev/null || true

if [ "$EUID" -eq 0 ]; then
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "/usr/share/applications" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "/usr/share/icons/hicolor" 2>/dev/null || true
fi

echo "=========================================================="
echo "✓ Lenovo Battery Monitor has been uninstalled."
if [ "$EUID" -ne 0 ] && [ -f "/opt/lenovo-conservation" ]; then
    echo "Note: If you previously installed system-wide, run 'sudo ./uninstall.sh' to remove system files."
fi
echo "=========================================================="
