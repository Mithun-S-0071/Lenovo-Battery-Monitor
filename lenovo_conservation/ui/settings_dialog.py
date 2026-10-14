"""Settings dialog for configuring thresholds, hysteresis, and service."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lenovo_conservation.hardware_detection import CapabilityState
from lenovo_conservation.profile_manager import ProfileManager


class SettingsDialog(QDialog):
    """Configuration dialog for hysteresis and background service options."""

    def __init__(self, profile_mgr: ProfileManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.profile_mgr = profile_mgr
        self.state = profile_mgr.get_persistent_state()

        self.setWindowTitle("Lenovo Battery Monitor — Settings")
        self.resize(520, 500)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Smart 80% Settings Group
        smart_group = QGroupBox("Smart 80% Software Controller Settings")
        smart_group.setStyleSheet("font-weight: 600; font-size: 13px;")
        smart_layout = QVBoxLayout(smart_group)
        smart_layout.setSpacing(10)

        expl = QLabel(
            "Configure charging thresholds for Smart 80% mode. "
            "Hysteresis ensures the laptop does not rapidly toggle charging on and off."
        )
        expl.setWordWrap(True)
        expl.setStyleSheet("font-weight: normal; font-size: 12px; color: #888888;")
        smart_layout.addWidget(expl)

        form = QFormLayout()
        form.setSpacing(10)

        self.upper_spin = QSpinBox()
        self.upper_spin.setRange(75, 90)
        self.upper_spin.setValue(self.state.smart80_upper)
        self.upper_spin.setSuffix("%")
        form.addRow("Stop charging target (upper):", self.upper_spin)

        self.lower_spin = QSpinBox()
        self.lower_spin.setRange(60, 78)
        self.lower_spin.setValue(self.state.smart80_lower)
        self.lower_spin.setSuffix("%")
        form.addRow("Resume charging threshold (lower):", self.lower_spin)

        smart_layout.addLayout(form)
        layout.addWidget(smart_group)

        # Background Service Group
        svc_group = QGroupBox("Background Daemon Service")
        svc_group.setStyleSheet("font-weight: 600; font-size: 13px;")
        svc_layout = QVBoxLayout(svc_group)
        svc_layout.setSpacing(8)

        health = self.profile_mgr.get_service_health()
        status_text = "🟢 Active (Running)" if health.is_running else "⚪ Not Running"
        self.svc_status_label = QLabel(f"Status: {status_text} (PID: {health.pid or 'N/A'})")
        self.svc_status_label.setStyleSheet("font-weight: normal; font-size: 12px;")
        svc_layout.addWidget(self.svc_status_label)

        btn_row = QHBoxLayout()
        self.start_svc_btn = QPushButton("Start Background Service")
        self.start_svc_btn.clicked.connect(self._start_service)
        btn_row.addWidget(self.start_svc_btn)

        svc_layout.addLayout(btn_row)
        layout.addWidget(svc_group)

        # Community & Support Group with Embedded Links
        links_group = QGroupBox("Support & Project Links")
        links_group.setStyleSheet("font-weight: 600; font-size: 13px;")
        links_layout = QVBoxLayout(links_group)
        links_layout.setSpacing(8)

        issue_lbl = QLabel(
            '🐞 Report an issue: <a href="https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor/issues" style="color: #3daee9; text-decoration: underline; font-weight: 600;">https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor/issues</a>'
        )
        issue_lbl.setOpenExternalLinks(True)
        issue_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        issue_lbl.setStyleSheet("font-size: 12px; font-weight: normal;")
        links_layout.addWidget(issue_lbl)

        repo_lbl = QLabel(
            '🌐 GitHub Repository: <a href="https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor" style="color: #3daee9; text-decoration: underline; font-weight: 600;">https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor</a>'
        )
        repo_lbl.setOpenExternalLinks(True)
        repo_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        repo_lbl.setStyleSheet("font-size: 12px; font-weight: normal;")
        links_layout.addWidget(repo_lbl)

        layout.addWidget(links_group)

        layout.addStretch()

        # Action buttons
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_settings)
        bottom_row.addWidget(save_btn)

        layout.addLayout(bottom_row)

    def _start_service(self) -> None:
        ok = self.profile_mgr.ensure_background_service_running()
        health = self.profile_mgr.get_service_health()
        status_text = "🟢 Active (Running)" if health.is_running else "⚪ Failed to Start"
        self.svc_status_label.setText(f"Status: {status_text} (PID: {health.pid or 'N/A'})")

    def _save_settings(self) -> None:
        upper = self.upper_spin.value()
        lower = self.lower_spin.value()
        if lower >= upper:
            QMessageBox.warning(
                self,
                "Invalid Thresholds",
                "Lower resume threshold must be strictly less than upper stop target.",
            )
            return

        self.state.smart80_upper = upper
        self.state.smart80_lower = lower

        # Persist updated settings
        from lenovo_conservation.service import LenovoConservationService
        svc = LenovoConservationService()
        svc.persistent_state.smart80_upper = upper
        svc.persistent_state.smart80_lower = lower
        svc.save_state()

        self.accept()
