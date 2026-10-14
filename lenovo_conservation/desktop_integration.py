"""Desktop integration module for Lenovo Conservation.

Detects desktop environment (KDE Plasma, GNOME, or fallback) and dark/light mode
preferences to apply native-looking QSS stylesheets matching Breeze or Adwaita.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from enum import Enum
from typing import Optional


class DesktopEnvironment(str, Enum):
    KDE = "kde"
    GNOME = "gnome"
    FALLBACK = "fallback"


def detect_desktop_environment() -> DesktopEnvironment:
    """Detect the current running desktop environment."""
    xdg_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    desktop_session = os.environ.get("DESKTOP_SESSION", "").upper()

    if "KDE" in xdg_desktop or "PLASMA" in xdg_desktop or "KDE" in desktop_session:
        return DesktopEnvironment.KDE
    if "GNOME" in xdg_desktop or "GNOME" in desktop_session:
        return DesktopEnvironment.GNOME
    return DesktopEnvironment.FALLBACK


def is_dark_mode_active() -> bool:
    """Detect whether system dark mode preference is enabled."""
    desktop = detect_desktop_environment()

    if desktop == DesktopEnvironment.GNOME and shutil.which("gsettings"):
        try:
            res = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            return "dark" in res.stdout.lower()
        except Exception:
            pass

    if desktop == DesktopEnvironment.KDE:
        # Check kreadconfig6 / kreadconfig5
        kread = shutil.which("kreadconfig6") or shutil.which("kreadconfig5")
        if kread:
            try:
                res = subprocess.run(
                    [kread, "--group", "General", "--key", "ColorScheme"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                theme_name = res.stdout.lower()
                if "dark" in theme_name or "breezedark" in theme_name:
                    return True
            except Exception:
                pass

    # Generic check or default to dark (common for modern Linux desktop users)
    return True


def get_application_stylesheet() -> str:
    """Generate the matching stylesheet for the current desktop environment."""
    desktop = detect_desktop_environment()
    dark = is_dark_mode_active()

    if desktop == DesktopEnvironment.KDE:
        return _get_breeze_stylesheet(dark)
    elif desktop == DesktopEnvironment.GNOME:
        return _get_adwaita_stylesheet(dark)
    else:
        return _get_fallback_stylesheet(dark)


def _get_breeze_stylesheet(dark: bool) -> str:
    """KDE Breeze-inspired stylesheet."""
    if dark:
        bg = "#232629"
        card_bg = "#2a2e32"
        card_hover = "#31363b"
        card_selected = "#1d3b53"
        border = "#31363b"
        border_selected = "#3daee9"
        text = "#eff0f1"
        text_muted = "#bdc3c7"
        accent = "#3daee9"
        badge_bg = "#1b2a38"
        danger = "#ed1515"
    else:
        bg = "#eff0f1"
        card_bg = "#ffffff"
        card_hover = "#f7f7f7"
        card_selected = "#e3f2fd"
        border = "#d0d3d4"
        border_selected = "#3daee9"
        text = "#232629"
        text_muted = "#5d6d7e"
        accent = "#3daee9"
        badge_bg = "#e1f5fe"
        danger = "#da4453"

    return f"""
    QMainWindow, QDialog {{
        background-color: {bg};
        color: {text};
        font-family: system-ui, -apple-system, sans-serif;
    }}
    QWidget {{
        color: {text};
    }}
    QLabel {{
        border: none;
        background: transparent;
    }}
    QFrame#HeaderFrame {{
        background-color: {card_bg};
        border-bottom: 1px solid {border};
        padding: 14px;
    }}
    QLabel#TitleLabel {{
        font-size: 18px;
        font-weight: 700;
        color: {text};
    }}
    QLabel#SubtitleLabel {{
        font-size: 13px;
        color: {text_muted};
    }}
    QFrame#ProfileCard {{
        background-color: {card_bg};
        border: 2px solid {border};
        border-radius: 8px;
        padding: 16px;
    }}
    QFrame#ProfileCard:hover {{
        background-color: {card_hover};
        border-color: {accent};
    }}
    QFrame#ProfileCardSelected {{
        background-color: {card_selected};
        border: 2px solid {border_selected};
        border-radius: 8px;
        padding: 16px;
    }}
    QPushButton {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {card_hover};
        border-color: {accent};
    }}
    QPushButton:pressed {{
        background-color: {card_selected};
    }}
    QPushButton#PrimaryButton {{
        background-color: {accent};
        color: #ffffff;
        border: none;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: #2980b9;
    }}
    QFrame#StatusChip {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 14px;
        padding: 4px 12px;
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 8px;
        color: {text};
        font-family: monospace;
    }}
    """


def _get_adwaita_stylesheet(dark: bool) -> str:
    """GNOME Adwaita-inspired stylesheet."""
    if dark:
        bg = "#242424"
        card_bg = "#303030"
        card_hover = "#383838"
        card_selected = "#1c3d5a"
        border = "#3d3d3d"
        border_selected = "#3584e4"
        text = "#ffffff"
        text_muted = "#9a9996"
        accent = "#3584e4"
    else:
        bg = "#fafafa"
        card_bg = "#ffffff"
        card_hover = "#f6f6f6"
        card_selected = "#e1f0fa"
        border = "#deddda"
        border_selected = "#3584e4"
        text = "#2e3436"
        text_muted = "#77767b"
        accent = "#3584e4"

    return f"""
    QMainWindow, QDialog {{
        background-color: {bg};
        color: {text};
        font-family: Cantarell, Inter, system-ui, sans-serif;
    }}
    QWidget {{
        color: {text};
    }}
    QLabel {{
        border: none;
        background: transparent;
    }}
    QFrame#HeaderFrame {{
        background-color: {card_bg};
        border-bottom: 1px solid {border};
        padding: 16px;
    }}
    QLabel#TitleLabel {{
        font-size: 19px;
        font-weight: 700;
        color: {text};
    }}
    QLabel#SubtitleLabel {{
        font-size: 13px;
        color: {text_muted};
    }}
    QFrame#ProfileCard {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 12px;
        padding: 16px;
    }}
    QFrame#ProfileCard:hover {{
        background-color: {card_hover};
    }}
    QFrame#ProfileCardSelected {{
        background-color: {card_selected};
        border: 2px solid {border_selected};
        border-radius: 12px;
        padding: 16px;
    }}
    QPushButton {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {card_hover};
    }}
    QPushButton#PrimaryButton {{
        background-color: {accent};
        color: #ffffff;
        border: none;
    }}
    QFrame#StatusChip {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 16px;
        padding: 4px 12px;
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 8px;
        color: {text};
        font-family: monospace;
    }}
    """


def _get_fallback_stylesheet(dark: bool) -> str:
    """Modern fallback stylesheet."""
    return _get_breeze_stylesheet(dark)
