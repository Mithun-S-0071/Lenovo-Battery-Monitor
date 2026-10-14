"""Diagnostics dialog displaying hardware details and diagnostic report."""

from __future__ import annotations

import platform
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lenovo_conservation.desktop_integration import detect_desktop_environment
from lenovo_conservation.hardware_detection import HardwareCapabilities
from lenovo_conservation.profile_manager import ProfileManager


def generate_diagnostic_report(profile_mgr: ProfileManager) -> str:
    """Construct a formatted diagnostics report without requiring QWidget/QApplication."""
    caps: HardwareCapabilities = profile_mgr.caps
    desktop = detect_desktop_environment().value
    health = profile_mgr.get_service_health()
    snap = profile_mgr.monitor.get_snapshot()

    lines = [
        "============================================================",
        "           LENOVO BATTERY MONITOR DIAGNOSTIC REPORT         ",
        "============================================================",
        "",
        "--- SYSTEM INFORMATION ---",
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Distribution: {platform.freedesktop_os_release().get('PRETTY_NAME', platform.version()) if hasattr(platform, 'freedesktop_os_release') else platform.version()}",
        f"Desktop Environment: {desktop.upper()}",
        f"Kernel: {caps.kernel_version}",
        "",
        "--- DMI HARDWARE ---",
        f"Manufacturer / Vendor: {caps.laptop_vendor}",
        f"Product Name: {caps.product_name}",
        f"Product Version: {caps.product_version}",
        f"Product Family: {caps.product_family}",
        f"Chassis Type: {caps.chassis_type}",
        f"BIOS Version: {caps.bios_version}",
        f"Is Lenovo: {caps.is_lenovo}",
        "",
        "--- CAPABILITY DETECTION ---",
        f"Capability State: {caps.state.value}",
        f"Interface Type: {caps.interface_type.value}",
        f"Interface Path: {caps.interface_path or 'None'}",
        f"Driver Name: {caps.driver_name or 'None'}",
        f"Can Read: {caps.can_read}",
        f"Can Write Direct: {caps.can_write_direct}",
        f"Requires Elevation: {caps.requires_elevation}",
        f"Reason: {caps.reason}",
        f"Supported Profiles: {[p.value for p in caps.supported_profiles]}",
        "",
        "--- POWER SUPPLIES & BATTERY HEALTH ---",
        f"AC Adapter Online: {snap.ac_online}",
        f"AC Adapters Count: {len(snap.ac_adapters)}",
    ]

    for ac in snap.ac_adapters:
        lines.append(f"  • {ac.name}: path={ac.path}, online={ac.online}")

    lines.append(f"Batteries Count: {len(snap.batteries)}")
    for b in snap.batteries:
        lines.append(f"  • {b.name}:")
        lines.append(f"      present: {b.present}")
        lines.append(f"      capacity: {b.capacity}%")
        lines.append(f"      status: {b.status}")
        health_str = f"{b.health_percent}% ({b.health_grade})" if b.health_percent is not None else "N/A"
        lines.append(f"      battery_health: {health_str}")
        lines.append(f"      design_capacity: {b.design_capacity_wh} Wh" if b.design_capacity_wh else "      design_capacity: N/A")
        lines.append(f"      full_charge_capacity: {b.full_charge_capacity_wh} Wh" if b.full_charge_capacity_wh else "      full_charge_capacity: N/A")
        lines.append(f"      remaining_capacity: {b.remaining_capacity_wh} Wh" if b.remaining_capacity_wh else "      remaining_capacity: N/A")
        temp_str = f"{b.temperature_c} °C ({b.temperature_source})" if b.temperature_c is not None else "N/A"
        lines.append(f"      temperature: {temp_str}")
        lines.append(f"      power_rate: {b.power_rate_w} W" if b.power_rate_w is not None else "      power_rate: N/A")
        lines.append(f"      voltage_now: {b.voltage_v} V" if b.voltage_v is not None else "      voltage_now: N/A")
        lines.append(f"      voltage_min_design: {b.voltage_min_design_v} V" if b.voltage_min_design_v is not None else "      voltage_min_design: N/A")
        lines.append(f"      cycle_count: {b.cycle_count if b.cycle_count is not None else 'N/A'}")
        lines.append(f"      manufacturer: {b.manufacturer}")
        lines.append(f"      model_name: {b.model_name}")
        lines.append(f"      technology: {b.technology}")
        lines.append(f"      start_thresh: {b.charge_start_threshold} (path: {b.charge_start_threshold_path})")
        lines.append(f"      end_thresh: {b.charge_end_threshold} (path: {b.charge_end_threshold_path})")

    lines.extend([
        "",
        "--- BACKGROUND SERVICE HEALTH ---",
        f"Service Running: {health.is_running}",
        f"Service PID: {health.pid or 'None'}",
        f"Systemd Unit Enabled: {health.systemd_enabled}",
        f"Active Profile in State: {health.state.active_profile}",
        f"Controller State: {health.state.last_controller_state}",
        f"Last Controller Action: {health.state.last_action}",
        f"Consecutive Errors: {health.state.consecutive_errors}",
        "",
        "--- DETECTION TRACE NOTES ---",
    ])
    for note in caps.diagnostic_notes:
        lines.append(f"  - {note}")

    lines.append("============================================================")
    return "\n".join(lines)


class DiagnosticsDialog(QDialog):
    """Dialog showing detailed system hardware and battery diagnostics."""

    def __init__(self, profile_mgr: ProfileManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.profile_mgr = profile_mgr
        self.caps: HardwareCapabilities = profile_mgr.caps

        self.setWindowTitle("Lenovo Battery Monitor — Diagnostics Report")
        self.resize(650, 500)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("System Hardware & Firmware Diagnostics")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Detailed inspection of sysfs interfaces, kernel modules, battery nodes, "
            "and permissions. Useful for reporting issues and verifying hardware support."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 12px; color: #888888;")
        layout.addWidget(subtitle)

        # Diagnostics text area
        self.text_area = QPlainTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet(
            "font-family: monospace; font-size: 12px; line-height: 1.4; "
            "padding: 10px; border-radius: 6px;"
        )
        report_text = generate_diagnostic_report(self.profile_mgr)
        self.text_area.setPlainText(report_text)
        layout.addWidget(self.text_area)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.copy_btn = QPushButton("📋 Copy Diagnostic Report")
        self.copy_btn.setObjectName("PrimaryButton")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(self.copy_btn)

        btn_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _copy_to_clipboard(self) -> None:
        """Copy diagnostic text to clipboard and show feedback."""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.text_area.toPlainText())
            self.copy_btn.setText("✓ Copied to Clipboard!")
            self.copy_btn.setEnabled(False)
