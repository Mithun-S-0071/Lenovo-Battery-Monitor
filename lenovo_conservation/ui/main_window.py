"""Main application window for Lenovo Battery Monitor with Lenovo Vantage aesthetic."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QRect, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lenovo_conservation.battery_monitor import PowerSupplySnapshot
from lenovo_conservation.desktop_integration import get_application_stylesheet
from lenovo_conservation.hardware_detection import (
    CapabilityState,
    ChargingProfile,
    HardwareCapabilities,
)
from lenovo_conservation.lenovo_control import ControlResult
from lenovo_conservation.profile_manager import ProfileManager
from lenovo_conservation.ui.diagnostics_dialog import DiagnosticsDialog
from lenovo_conservation.ui.profile_card import ProfileCard
from lenovo_conservation.ui.settings_dialog import SettingsDialog

logger = logging.getLogger("lenovo_conservation.ui.main_window")


class BatteryHealthBar(QWidget):
    """Custom battery charge/health bar matching Lenovo Vantage."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.ratio = 0.0
        self.color_hex = "#2ecc71"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, ratio: float, color_hex: str = "#2ecc71") -> None:
        self.ratio = max(0.0, min(1.0, ratio))
        self.color_hex = color_hex
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        # Background track
        painter.setBrush(QColor("#2a2e35"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 4, 4)

        # Fill bar
        fill_w = int(rect.width() * self.ratio)
        if fill_w > 0:
            fill_rect = QRect(0, 0, fill_w, rect.height())
            painter.setBrush(QColor(self.color_hex))
            painter.drawRoundedRect(fill_rect, 4, 4)


class TemperatureBar(QWidget):
    """Custom temperature gauge bar matching Lenovo Vantage multi-color gradient."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(12)
        self.temp_c: Optional[float] = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_temperature(self, temp_c: Optional[float]) -> None:
        self.temp_c = temp_c
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        # Background track
        painter.setBrush(QColor("#262a30"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 4, 4)

        if self.temp_c is None:
            painter.setPen(QColor("#6c757d"))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "Hardware sensor not reported by battery")
            return

        min_temp = 0.0
        max_temp = 60.0
        ratio = max(0.0, min(1.0, (self.temp_c - min_temp) / (max_temp - min_temp)))

        fill_width = int(rect.width() * ratio)
        if fill_width > 4:
            grad = QLinearGradient(0, 0, rect.width(), 0)
            grad.setColorAt(0.0, QColor("#3498db"))   # Cold Blue
            grad.setColorAt(0.25, QColor("#2ecc71"))  # Ideal Green
            grad.setColorAt(0.65, QColor("#f1c40f"))  # Warm Yellow
            grad.setColorAt(0.85, QColor("#e67e22"))  # High
            grad.setColorAt(1.0, QColor("#e74c3c"))   # Critical Red

            fill_rect = QRect(0, 0, fill_width, rect.height())
            painter.setBrush(grad)
            painter.drawRoundedRect(fill_rect, 4, 4)

        marker_x = int(rect.width() * ratio)
        marker_x = max(2, min(rect.width() - 4, marker_x))
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QColor("#000000"))
        painter.drawRoundedRect(marker_x - 2, 0, 4, rect.height(), 2, 2)


class ProfileWorker(QObject):
    """Background worker for non-blocking privileged profile switching."""
    finished = Signal(ControlResult, str)

    def __init__(self, profile_mgr: ProfileManager, profile: ChargingProfile):
        super().__init__()
        self.profile_mgr = profile_mgr
        self.profile = profile

    @Slot()
    def run(self) -> None:
        res = self.profile_mgr.apply_profile(self.profile)
        self.finished.emit(res, self.profile.value)


class MainWindow(QMainWindow):
    """Main window for Lenovo Battery Monitor with Lenovo Vantage aesthetic."""

    def __init__(self, profile_mgr: Optional[ProfileManager] = None):
        super().__init__()
        self.profile_mgr = profile_mgr or ProfileManager()
        self.caps: HardwareCapabilities = self.profile_mgr.caps
        self.cards: dict[str, ProfileCard] = {}

        self.setWindowTitle("Lenovo Battery Monitor")
        self.setMinimumSize(850, 680)
        self.resize(1000, 820)

        # Apply base styling
        self.setStyleSheet(get_application_stylesheet())

        self._init_ui()

        # Connect battery monitor updates
        self.profile_mgr.monitor.add_callback(self._on_monitor_update)
        self.profile_mgr.monitor.start()

        # Periodic status refresh timer (every 3 seconds for UI state)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_ui_state)
        self.refresh_timer.start(3000)

        # Initial UI refresh
        self._refresh_ui_state()

    def _init_ui(self) -> None:
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        central_widget.setStyleSheet(
            "#CentralWidget { background-color: #121417; }"
        )
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Left Navigation Sidebar (Vantage Rail)
        sidebar = self._create_vantage_sidebar()
        root_layout.addWidget(sidebar)

        # 2. Main Content Area (Right)
        main_content = self._create_main_content_area()
        root_layout.addWidget(main_content, stretch=1)

    def _create_vantage_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setObjectName("VantageSidebar")
        sidebar.setStyleSheet(
            "#VantageSidebar { background-color: #0d0f11; border-right: 1px solid #1f2328; }"
        )

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(14)

        # Top Vantage Emblem & Title
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        logo_box = QLabel("L")
        logo_box.setFixedSize(34, 34)
        logo_box.setAlignment(Qt.AlignCenter)
        logo_box.setStyleSheet(
            "background-color: #e2231a; color: #ffffff; font-weight: 900; "
            "font-size: 20px; border-radius: 6px; font-family: sans-serif;"
        )
        top_row.addWidget(logo_box)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(1)
        sidebar_title = QLabel("Lenovo")
        sidebar_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
        title_vbox.addWidget(sidebar_title)

        sidebar_sub = QLabel("Battery Monitor")
        sidebar_sub.setStyleSheet("font-size: 11px; font-weight: 600; color: #3daee9;")
        title_vbox.addWidget(sidebar_sub)

        top_row.addLayout(title_vbox)
        layout.addLayout(top_row)

        layout.addSpacing(12)

        # Section label
        sec_lbl = QLabel("DEVICE SETTINGS")
        sec_lbl.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #5c6773; letter-spacing: 1px;"
        )
        layout.addWidget(sec_lbl)

        # Navigation Buttons
        self.nav_power_btn = QPushButton("⚡  Power")
        self.nav_power_btn.setCursor(Qt.PointingHandCursor)
        self.nav_power_btn.setStyleSheet(
            "QPushButton { background-color: #1a2736; color: #3daee9; border: none; "
            "border-left: 3px solid #3daee9; border-radius: 4px; padding: 10px 12px; "
            "font-weight: 700; font-size: 13px; text-align: left; }"
        )
        self.nav_power_btn.clicked.connect(self._scroll_to_top)
        layout.addWidget(self.nav_power_btn)

        self.nav_conserv_btn = QPushButton("🛡️  Conservation")
        self.nav_conserv_btn.setCursor(Qt.PointingHandCursor)
        self.nav_conserv_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #bdc3c7; border: none; "
            "border-left: 3px solid transparent; border-radius: 4px; padding: 10px 12px; "
            "font-weight: 600; font-size: 13px; text-align: left; } "
            "QPushButton:hover { background-color: #181c22; color: #ffffff; }"
        )
        self.nav_conserv_btn.clicked.connect(self._scroll_to_conservation)
        layout.addWidget(self.nav_conserv_btn)

        self.nav_diag_btn = QPushButton("📋  Diagnostics")
        self.nav_diag_btn.setCursor(Qt.PointingHandCursor)
        self.nav_diag_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #bdc3c7; border: none; "
            "border-left: 3px solid transparent; border-radius: 4px; padding: 10px 12px; "
            "font-weight: 600; font-size: 13px; text-align: left; } "
            "QPushButton:hover { background-color: #181c22; color: #ffffff; }"
        )
        self.nav_diag_btn.clicked.connect(self._open_diagnostics)
        layout.addWidget(self.nav_diag_btn)

        self.nav_settings_btn = QPushButton("⚙️  Settings")
        self.nav_settings_btn.setCursor(Qt.PointingHandCursor)
        self.nav_settings_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #bdc3c7; border: none; "
            "border-left: 3px solid transparent; border-radius: 4px; padding: 10px 12px; "
            "font-weight: 600; font-size: 13px; text-align: left; } "
            "QPushButton:hover { background-color: #181c22; color: #ffffff; }"
        )
        self.nav_settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(self.nav_settings_btn)

        layout.addStretch()

        # Sidebar Footer Links
        links_vbox = QVBoxLayout()
        links_vbox.setSpacing(6)

        issue_link = QLabel(
            '<a href="https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor/issues" '
            'style="color: #3daee9; text-decoration: none; font-size: 11px;">🐞 Report an issue</a>'
        )
        issue_link.setOpenExternalLinks(True)
        links_vbox.addWidget(issue_link)

        repo_link = QLabel(
            '<a href="https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor" '
            'style="color: #8fa1b3; text-decoration: none; font-size: 11px;">🌐 GitHub Repository</a>'
        )
        repo_link.setOpenExternalLinks(True)
        links_vbox.addWidget(repo_link)

        ver_lbl = QLabel("Lenovo Battery Monitor v1.0.0")
        ver_lbl.setStyleSheet("font-size: 10px; color: #555b66; margin-top: 4px;")
        links_vbox.addWidget(ver_lbl)

        layout.addLayout(links_vbox)
        return sidebar

    def _create_main_content_area(self) -> QWidget:
        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar
        header_bar = QFrame()
        header_bar.setObjectName("MainHeaderBar")
        header_bar.setStyleSheet(
            "#MainHeaderBar { background-color: #16181d; border-bottom: 1px solid #23272e; "
            "padding: 12px 24px; }"
        )
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(20, 10, 20, 10)
        header_layout.setSpacing(12)

        vbox_titles = QVBoxLayout()
        vbox_titles.setSpacing(2)

        page_title = QLabel("Power")
        page_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #ffffff;")
        vbox_titles.addWidget(page_title)

        model_name = self.caps.product_version or self.caps.product_name or "Lenovo Laptop"
        if not model_name.startswith("Lenovo") and self.caps.is_lenovo:
            model_name = f"Lenovo {model_name}"
        self.device_model_lbl = QLabel(model_name)
        self.device_model_lbl.setStyleSheet("font-size: 12px; color: #8fa1b3;")
        vbox_titles.addWidget(self.device_model_lbl)

        header_layout.addLayout(vbox_titles)
        header_layout.addStretch()

        # Header Status Chips
        self.bat_chip = QFrame()
        self.bat_chip.setObjectName("StatusChip")
        self.bat_chip.setStyleSheet(
            "#StatusChip { background-color: #20242b; border: 1px solid #2d333d; "
            "border-radius: 14px; padding: 4px 12px; }"
        )
        bat_chip_layout = QHBoxLayout(self.bat_chip)
        bat_chip_layout.setContentsMargins(8, 4, 8, 4)
        self.bat_chip_text = QLabel("⚡ --%")
        self.bat_chip_text.setStyleSheet("font-weight: 600; font-size: 12px; color: #ffffff;")
        bat_chip_layout.addWidget(self.bat_chip_text)
        header_layout.addWidget(self.bat_chip)

        self.ac_chip = QFrame()
        self.ac_chip.setObjectName("StatusChip")
        self.ac_chip.setStyleSheet(
            "#StatusChip { background-color: #20242b; border: 1px solid #2d333d; "
            "border-radius: 14px; padding: 4px 12px; }"
        )
        ac_chip_layout = QHBoxLayout(self.ac_chip)
        ac_chip_layout.setContentsMargins(8, 4, 8, 4)
        self.ac_chip_text = QLabel("🔌 AC --")
        self.ac_chip_text.setStyleSheet("font-weight: 600; font-size: 12px; color: #ffffff;")
        ac_chip_layout.addWidget(self.ac_chip_text)
        header_layout.addWidget(self.ac_chip)

        main_layout.addWidget(header_bar)

        # Scrollable View
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: #121417; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("ScrollContent")
        scroll_content.setStyleSheet("#ScrollContent { background-color: #121417; }")
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(20, 16, 20, 24)
        self.content_layout.setSpacing(16)

        # Card 1: Battery health (Lenovo Vantage Card)
        self.health_card = self._create_battery_health_card()
        self.content_layout.addWidget(self.health_card)

        # Card 2: Temperature (Lenovo Vantage Card)
        self.temp_card = self._create_temperature_card()
        self.content_layout.addWidget(self.temp_card)

        # Card 3: At a glance (Lenovo Vantage Card)
        self.glance_card = self._create_at_a_glance_card()
        self.content_layout.addWidget(self.glance_card)

        # Card 4: Battery Conservation Mode (Charging limits)
        self.conservation_card = self._create_conservation_mode_card()
        self.content_layout.addWidget(self.conservation_card)

        # Bottom Actions & Settings Footer
        footer = self._create_footer_frame()
        self.content_layout.addWidget(footer)

        self.scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.scroll_area)
        return main_area

    # --- CARD 1: BATTERY HEALTH ---
    def _create_battery_health_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("VantageCard")
        card.setStyleSheet(
            "#VantageCard { background-color: #1d2127; border: 1px solid #2d333b; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Top row: Title and Health Pill
        top_row = QHBoxLayout()
        header_lbl = QLabel("Battery health")
        header_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(header_lbl)

        top_row.addStretch()

        self.health_badge = QLabel("Good")
        self.health_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; padding: 3px 12px; "
            "border-radius: 12px; background-color: #27ae60; color: #ffffff;"
        )
        top_row.addWidget(self.health_badge)
        layout.addLayout(top_row)

        # Horizontal Battery Health Bar
        self.health_bar = BatteryHealthBar()
        layout.addWidget(self.health_bar)

        # Capacity legend row with bullet indicators
        legend_row = QHBoxLayout()
        legend_row.setSpacing(18)

        self.charge_legend = QLabel("🟢 Current charge: -- Wh")
        self.charge_legend.setStyleSheet("font-size: 12px; color: #bdc3c7;")
        legend_row.addWidget(self.charge_legend)

        self.full_cap_legend = QLabel("🟢 Full charge capacity: -- Wh")
        self.full_cap_legend.setStyleSheet("font-size: 12px; color: #bdc3c7;")
        legend_row.addWidget(self.full_cap_legend)

        self.design_cap_legend = QLabel("⚪ Original design capacity: -- Wh")
        self.design_cap_legend.setStyleSheet("font-size: 12px; color: #bdc3c7;")
        legend_row.addWidget(self.design_cap_legend)

        legend_row.addStretch()
        layout.addLayout(legend_row)

        # Health Alert Callout Box (Only shown if Fair or Critical)
        self.health_alert_frame = QFrame()
        self.health_alert_frame.setVisible(False)
        alert_layout = QHBoxLayout(self.health_alert_frame)
        alert_layout.setContentsMargins(12, 10, 12, 10)
        alert_layout.setSpacing(8)

        self.health_alert_icon = QLabel("⚠️")
        self.health_alert_icon.setStyleSheet("font-size: 16px;")
        alert_layout.addWidget(self.health_alert_icon)

        self.health_alert_text = QLabel("")
        self.health_alert_text.setWordWrap(True)
        self.health_alert_text.setStyleSheet("font-size: 12px; font-weight: 500; line-height: 1.3;")
        alert_layout.addWidget(self.health_alert_text, stretch=1)

        layout.addWidget(self.health_alert_frame)
        return card

    # --- CARD 2: TEMPERATURE ---
    def _create_temperature_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("VantageCard")
        card.setStyleSheet(
            "#VantageCard { background-color: #1d2127; border: 1px solid #2d333b; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Top row: Title and Badge
        top_row = QHBoxLayout()
        self.temp_title_lbl = QLabel("Temperature: --")
        self.temp_title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(self.temp_title_lbl)

        top_row.addStretch()

        self.temp_badge = QLabel("Normal")
        self.temp_badge.setVisible(False)
        self.temp_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; padding: 3px 12px; "
            "border-radius: 12px; background-color: #d35400; color: #ffffff;"
        )
        top_row.addWidget(self.temp_badge)
        layout.addLayout(top_row)

        # Multi-color gradient temperature gauge
        self.temp_bar = TemperatureBar()
        layout.addWidget(self.temp_bar)

        # Temperature Alert Callout Box (Only shown if Cold < 10°C or Hot >= 40°C)
        self.temp_alert_frame = QFrame()
        self.temp_alert_frame.setVisible(False)
        alert_layout = QHBoxLayout(self.temp_alert_frame)
        alert_layout.setContentsMargins(12, 10, 12, 10)
        alert_layout.setSpacing(8)

        self.temp_alert_icon = QLabel("⚠️")
        self.temp_alert_icon.setStyleSheet("font-size: 16px;")
        alert_layout.addWidget(self.temp_alert_icon)

        self.temp_alert_text = QLabel("")
        self.temp_alert_text.setWordWrap(True)
        self.temp_alert_text.setStyleSheet("font-size: 12px; font-weight: 500; line-height: 1.3;")
        alert_layout.addWidget(self.temp_alert_text, stretch=1)

        layout.addWidget(self.temp_alert_frame)
        return card

    # --- CARD 3: AT A GLANCE ---
    def _create_at_a_glance_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("VantageCard")
        card.setStyleSheet(
            "#VantageCard { background-color: #1d2127; border: 1px solid #2d333b; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)

        # Top row: Header and Refresh
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 8)
        header_lbl = QLabel("At a glance")
        header_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(header_lbl)

        top_row.addStretch()

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #3daee9; border: none; "
            "font-size: 12px; font-weight: 600; padding: 4px 8px; } "
            "QPushButton:hover { text-decoration: underline; }"
        )
        refresh_btn.clicked.connect(self._manual_refresh)
        top_row.addWidget(refresh_btn)
        layout.addLayout(top_row)

        # Tabular Rows matching Lenovo Vantage table
        layout.addWidget(self._create_vantage_row("Current charge", "row_current_charge", "--"))
        layout.addWidget(
            self._create_vantage_row(
                "Full charge capacity comparison",
                "row_capacity_comparison",
                "--",
                has_badge=True,
            )
        )
        layout.addWidget(
            self._create_vantage_row(
                "Accumulated charge cycles",
                "row_cycles",
                "--",
                has_badge=True,
            )
        )
        layout.addWidget(self._create_vantage_row("Battery chemistry", "row_chemistry", "--"))
        layout.addWidget(self._create_vantage_row("Power adapter", "row_adapter", "--"))
        layout.addWidget(self._create_vantage_row("Power flow rate", "row_power_rate", "--"))
        layout.addWidget(self._create_vantage_row("Voltage", "row_voltage", "--"))
        layout.addWidget(self._create_vantage_row("Battery hardware model", "row_model", "--"))

        return card

    def _create_vantage_row(
        self,
        label_text: str,
        attr_name: str,
        default_val: str,
        has_badge: bool = False,
    ) -> QWidget:
        row = QWidget()
        row.setStyleSheet("border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding: 7px 0px;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 5, 4, 5)

        t_lbl = QLabel(label_text)
        t_lbl.setStyleSheet("font-size: 13px; color: #a4abb5; font-weight: 500;")
        layout.addWidget(t_lbl)

        layout.addStretch()

        v_lbl = QLabel(default_val)
        v_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        setattr(self, attr_name, v_lbl)
        layout.addWidget(v_lbl)

        if has_badge:
            b_lbl = QLabel("")
            b_lbl.setVisible(False)
            b_lbl.setStyleSheet(
                "font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px;"
            )
            setattr(self, f"{attr_name}_badge", b_lbl)
            layout.addWidget(b_lbl)

        return row

    # --- CARD 4: CONSERVATION MODE ---
    def _create_conservation_mode_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("VantageCard")
        card.setStyleSheet(
            "#VantageCard { background-color: #1d2127; border: 1px solid #2d333b; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_lbl = QLabel("Battery Conservation Mode")
        header_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        layout.addWidget(header_lbl)

        sub_desc = QLabel(
            "Conserve battery lifespan by limiting charge thresholds when plugged in continuously."
        )
        sub_desc.setWordWrap(True)
        sub_desc.setStyleSheet("font-size: 12px; color: #8fa1b3;")
        layout.addWidget(sub_desc)

        # Hardware Capability Banner
        self.cap_banner = self._create_capability_banner()
        layout.addWidget(self.cap_banner)

        # Live status overview box
        self.status_box = self._create_live_status_box()
        layout.addWidget(self.status_box)

        # Profile selection cards
        active_prof = self.profile_mgr.get_active_profile()

        # Case A: Hardware with 60% conservation threshold
        if self.caps.state == CapabilityState.CONSERVATION_60:
            c60 = ProfileCard(
                profile=ChargingProfile.CONSERVATION_60,
                title="Conservation — 60%",
                subtitle="Enables Lenovo's native firmware conservation mode. The battery stops charging at ~60% to maximize lifespan when plugged in continuously.",
                badge_text="Firmware Enforced",
                is_selected=(active_prof == ChargingProfile.CONSERVATION_60),
            )
            c60.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.CONSERVATION_60.value] = c60
            layout.addWidget(c60)

            smart80 = ProfileCard(
                profile=ChargingProfile.SMART_80,
                title="Smart 80%",
                subtitle="Software-managed controller. Holds charge near 80% by activating native conservation mode at 80% and resuming charge when drained to 75%.",
                badge_text="Background Managed",
                note_text="Note: Smart 80% charging works only when the device is on. If the laptop is turned off, firmware default behavior applies.",
                is_selected=(active_prof == ChargingProfile.SMART_80),
            )
            smart80.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.SMART_80.value] = smart80
            layout.addWidget(smart80)

            full = ProfileCard(
                profile=ChargingProfile.FULL_CHARGE,
                title="Full Charge",
                subtitle="Disables conservation mode, allowing normal charging to 100% capacity.",
                warning_text="Charging to 100% may increase long-term battery degradation.",
                is_selected=(active_prof == ChargingProfile.FULL_CHARGE),
            )
            full.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.FULL_CHARGE.value] = full
            layout.addWidget(full)

        # Case B: Hardware with 80% conservation threshold (e.g. Legion / LOQ)
        elif self.caps.state == CapabilityState.CONSERVATION_80:
            c80 = ProfileCard(
                profile=ChargingProfile.CONSERVATION_80,
                title="Conservation — 80%",
                subtitle="Enables native firmware conservation mode. The hardware limits charging to 80% without requiring software background monitoring.",
                badge_text="Firmware Enforced",
                is_selected=(active_prof == ChargingProfile.CONSERVATION_80),
            )
            c80.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.CONSERVATION_80.value] = c80
            layout.addWidget(c80)

            full = ProfileCard(
                profile=ChargingProfile.FULL_CHARGE,
                title="Full Charge",
                subtitle="Disables conservation mode, allowing normal charging to 100% capacity.",
                warning_text="Charging to 100% may increase long-term battery degradation.",
                is_selected=(active_prof == ChargingProfile.FULL_CHARGE),
            )
            full.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.FULL_CHARGE.value] = full
            layout.addWidget(full)

        # Case C: ThinkPad configurable thresholds
        elif self.caps.state == CapabilityState.CONFIGURABLE_THRESHOLDS:
            tp80 = ProfileCard(
                profile=ChargingProfile.CONFIGURABLE_80,
                title="Native 80% Conservation",
                subtitle="Programs native ThinkPad hardware charging thresholds (Start: 75%, Stop: 80%). Maintained directly by the Embedded Controller even when laptop is turned off.",
                badge_text="Firmware Enforced",
                is_selected=(active_prof == ChargingProfile.CONFIGURABLE_80),
            )
            tp80.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.CONFIGURABLE_80.value] = tp80
            layout.addWidget(tp80)

            full = ProfileCard(
                profile=ChargingProfile.FULL_CHARGE,
                title="Full Charge",
                subtitle="Resets charging thresholds to standard values (Start: 96%, Stop: 100%).",
                warning_text="Charging to 100% may increase long-term battery degradation.",
                is_selected=(active_prof == ChargingProfile.FULL_CHARGE),
            )
            full.clicked.connect(self._on_profile_clicked)
            self.cards[ChargingProfile.FULL_CHARGE.value] = full
            layout.addWidget(full)

        else:
            unsupported = QLabel(
                "Battery charging threshold controls are not supported on this device or kernel driver."
            )
            unsupported.setStyleSheet("color: #e74c3c; font-weight: 600;")
            layout.addWidget(unsupported)

        return card

    def _create_capability_banner(self) -> QFrame:
        banner = QFrame()
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        state = self.caps.state
        if state in (
            CapabilityState.CONSERVATION_60,
            CapabilityState.CONSERVATION_80,
            CapabilityState.CONFIGURABLE_THRESHOLDS,
        ):
            bg_color = "rgba(46, 204, 113, 0.12)"
            border_color = "#2ecc71"
            icon_char = "🛡️"
            title_color = "#2ecc71"
        elif state == CapabilityState.THRESHOLD_UNKNOWN:
            bg_color = "rgba(243, 156, 18, 0.12)"
            border_color = "#f39c12"
            icon_char = "⚠️"
            title_color = "#f39c12"
        else:
            bg_color = "rgba(231, 76, 60, 0.12)"
            border_color = "#e74c3c"
            icon_char = "❌"
            title_color = "#e74c3c"

        banner.setObjectName("CapabilityBanner")
        banner.setStyleSheet(
            f"#CapabilityBanner {{ background-color: {bg_color}; border: 1px solid {border_color}; "
            f"border-radius: 8px; }}"
        )

        badge_icon = QLabel(icon_char)
        badge_icon.setStyleSheet("font-size: 18px;")
        layout.addWidget(badge_icon)

        vbox = QVBoxLayout()
        vbox.setSpacing(2)

        self.cap_title = QLabel(f"Hardware Capability: {state.value}")
        self.cap_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {title_color};")
        vbox.addWidget(self.cap_title)

        reason_text = self.caps.reason
        self.cap_desc = QLabel(reason_text)
        self.cap_desc.setWordWrap(True)
        self.cap_desc.setStyleSheet("font-size: 11px; color: #8fa1b3;")
        vbox.addWidget(self.cap_desc)

        layout.addLayout(vbox)
        layout.addStretch()
        return banner

    def _create_live_status_box(self) -> QFrame:
        box = QFrame()
        box.setObjectName("StatusBox")
        box.setStyleSheet(
            "#StatusBox { background-color: rgba(61, 174, 233, 0.08); "
            "border: 1px solid rgba(61, 174, 233, 0.25); "
            "border-radius: 8px; }"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        header_lbl = QLabel("CURRENT CHARGING STATUS")
        header_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #3daee9; letter-spacing: 0.5px;")
        layout.addWidget(header_lbl)

        self.status_detail_lbl = QLabel("Monitoring battery and hardware...")
        self.status_detail_lbl.setWordWrap(True)
        self.status_detail_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        layout.addWidget(self.status_detail_lbl)

        return box

    # --- FOOTER & EMBEDDED LINKS ---
    def _create_footer_frame(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        # Action Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        diag_btn = QPushButton("📋 Diagnostics")
        diag_btn.setCursor(Qt.PointingHandCursor)
        diag_btn.setStyleSheet(
            "QPushButton { background-color: #23272e; border: 1px solid #333a42; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; color: #ffffff; } "
            "QPushButton:hover { background-color: #2a3038; border-color: #3daee9; }"
        )
        diag_btn.clicked.connect(self._open_diagnostics)
        btn_row.addWidget(diag_btn)

        settings_btn = QPushButton("⚙️ Settings")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setStyleSheet(
            "QPushButton { background-color: #23272e; border: 1px solid #333a42; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; color: #ffffff; } "
            "QPushButton:hover { background-color: #2a3038; border-color: #3daee9; }"
        )
        settings_btn.clicked.connect(self._open_settings)
        btn_row.addWidget(settings_btn)

        btn_row.addStretch()

        refresh_btn = QPushButton("🔄 Refresh Hardware")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(
            "QPushButton { background-color: #23272e; border: 1px solid #333a42; "
            "border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: 600; color: #ffffff; } "
            "QPushButton:hover { background-color: #2a3038; border-color: #3daee9; }"
        )
        refresh_btn.clicked.connect(self._manual_refresh)
        btn_row.addWidget(refresh_btn)

        layout.addLayout(btn_row)

        # Embedded Links Row
        links_box = QFrame()
        links_box.setStyleSheet(
            "background-color: rgba(28, 32, 38, 0.4); border: 1px solid #23272e; "
            "border-radius: 8px; padding: 10px 14px;"
        )
        links_layout = QHBoxLayout(links_box)
        links_layout.setContentsMargins(10, 8, 10, 8)

        issue_lbl = QLabel(
            '🐞 <a href="https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor/issues" '
            'style="color: #3daee9; text-decoration: underline; font-weight: 600;">'
            'Report an issue on GitHub</a>'
        )
        issue_lbl.setOpenExternalLinks(True)
        issue_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        issue_lbl.setStyleSheet("font-size: 12px;")
        links_layout.addWidget(issue_lbl)

        links_layout.addStretch()

        repo_lbl = QLabel(
            '🌐 <a href="https://github.com/Mithun-S-0071/Lenovo-Battery-Monitor" '
            'style="color: #3daee9; text-decoration: underline; font-weight: 600;">'
            'GitHub Repository</a>'
        )
        repo_lbl.setOpenExternalLinks(True)
        repo_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        repo_lbl.setStyleSheet("font-size: 12px;")
        links_layout.addWidget(repo_lbl)

        layout.addWidget(links_box)
        return container

    # --- UI SCROLL HELPERS ---
    def _scroll_to_top(self) -> None:
        self.scroll_area.verticalScrollBar().setValue(0)

    def _scroll_to_conservation(self) -> None:
        pos = self.conservation_card.pos().y()
        self.scroll_area.verticalScrollBar().setValue(pos)

    # --- PROFILE SWITCHING ---
    def _on_profile_clicked(self, profile_val: str) -> None:
        target_profile = ChargingProfile(profile_val)

        for val, card in self.cards.items():
            card.set_selected(val == profile_val)

        self.thread = QThread()
        self.worker = ProfileWorker(self.profile_mgr, target_profile)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_profile_applied)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.status_detail_lbl.setText(f"Applying profile '{target_profile.value}'...")
        self.thread.start()

    @Slot(ControlResult, str)
    def _on_profile_applied(self, result: ControlResult, profile_val: str) -> None:
        if not result.success:
            QMessageBox.warning(
                self,
                "Profile Change Failed",
                f"Failed to activate profile '{profile_val}':\n\n{result.message}",
            )
            active = self.profile_mgr.get_active_profile().value
            for val, card in self.cards.items():
                card.set_selected(val == active)
        else:
            self.status_detail_lbl.setText(result.message)

        self._refresh_ui_state()

    def _on_monitor_update(self, snapshot: PowerSupplySnapshot) -> None:
        QTimer.singleShot(0, lambda: self._update_power_ui(snapshot))

    # --- LIVE DATA UPDATE ---
    def _update_power_ui(self, snapshot: PowerSupplySnapshot) -> None:
        cap = snapshot.capacity
        status = snapshot.status
        ac_online = snapshot.ac_online

        glyph = "⚡" if ac_online else "🔋"
        self.bat_chip_text.setText(f"{glyph} {cap}% ({status})")
        self.ac_chip_text.setText("🔌 Plugged in" if ac_online else "🔋 Battery Power")

        bat = snapshot.primary_battery
        if not bat:
            return

        # 1. Update Battery Health Card
        health_pct = bat.health_percent
        health_grade = bat.health_grade

        if health_pct is not None and health_grade != "Unknown":
            self.health_badge.setText(f"✓ {health_grade}" if health_grade == "Good" else f"⚠️ {health_grade}")
            if health_grade == "Good":
                self.health_badge.setStyleSheet(
                    "font-size: 11px; font-weight: 700; padding: 3px 12px; "
                    "border-radius: 12px; background-color: #27ae60; color: #ffffff;"
                )
                bar_color = "#2ecc71"
                self.health_alert_frame.setVisible(False)
            elif health_grade == "Fair":
                self.health_badge.setStyleSheet(
                    "font-size: 11px; font-weight: 700; padding: 3px 12px; "
                    "border-radius: 12px; background-color: #d35400; color: #ffffff;"
                )
                bar_color = "#f39c12"
                self.health_alert_frame.setStyleSheet(
                    "background-color: rgba(243, 156, 18, 0.12); border: 1px solid #f39c12; "
                    "border-radius: 6px;"
                )
                self.health_alert_icon.setText("⚠️")
                self.health_alert_text.setStyleSheet("color: #f39c12;")
                self.health_alert_text.setText(
                    "The battery is functioning correctly, but due to normal aging of the battery, "
                    "the battery life beween charges is now significantly shorter than when it was new"
                )
                self.health_alert_frame.setVisible(True)
            else:  # Critical
                self.health_badge.setStyleSheet(
                    "font-size: 11px; font-weight: 700; padding: 3px 12px; "
                    "border-radius: 12px; background-color: #c0392b; color: #ffffff;"
                )
                bar_color = "#e74c3c"
                self.health_alert_frame.setStyleSheet(
                    "background-color: rgba(231, 76, 60, 0.12); border: 1px solid #e74c3c; "
                    "border-radius: 6px;"
                )
                self.health_alert_icon.setText("❌")
                self.health_alert_text.setStyleSheet("color: #e74c3c;")
                self.health_alert_text.setText(
                    "The battery reports a failure and needs to be replaced as soon as possible"
                )
                self.health_alert_frame.setVisible(True)

            if bat.remaining_capacity_wh and bat.design_capacity_wh and bat.design_capacity_wh > 0:
                charge_ratio = bat.remaining_capacity_wh / bat.design_capacity_wh
            else:
                charge_ratio = cap / 100.0
            self.health_bar.set_value(charge_ratio, bar_color)
        else:
            self.health_badge.setText("N/A")
            self.health_bar.set_value(cap / 100.0, "#2ecc71")
            self.health_alert_frame.setVisible(False)

        # Legend Wh dots
        rem_str = f"{bat.remaining_capacity_wh:.2f} Wh" if bat.remaining_capacity_wh else f"{bat.capacity}%"
        self.charge_legend.setText(f"🟢 Current charge: {rem_str}")

        full_str = f"{bat.full_charge_capacity_wh:.2f} Wh" if bat.full_charge_capacity_wh else "N/A"
        self.full_cap_legend.setText(f"🟢 Full charge capacity: {full_str}")

        design_str = f"{bat.design_capacity_wh:.2f} Wh" if bat.design_capacity_wh else "N/A"
        self.design_cap_legend.setText(f"⚪ Original design capacity: {design_str}")

        # 2. Update Temperature Card (STRICTLY BATTERY ONLY)
        if bat.temperature_c is not None:
            temp_c = bat.temperature_c
            temp_f = bat.temperature_f or ((temp_c * 9.0 / 5.0) + 32.0)
            self.temp_title_lbl.setText(f"Temperature: {temp_c:.0f}°C / {temp_f:.1f}°F")
            self.temp_bar.set_temperature(temp_c)

            if temp_c < 10.0:
                self.temp_badge.setText("⚠️ Cold")
                self.temp_badge.setStyleSheet(
                    "font-size: 11px; font-weight: 700; padding: 3px 12px; "
                    "border-radius: 12px; background-color: #d35400; color: #ffffff;"
                )
                self.temp_badge.setVisible(True)

                self.temp_alert_frame.setStyleSheet(
                    "background-color: rgba(243, 156, 18, 0.12); border: 1px solid #f39c12; "
                    "border-radius: 6px;"
                )
                self.temp_alert_icon.setText("⚠️")
                self.temp_alert_text.setStyleSheet("color: #f39c12;")
                self.temp_alert_text.setText(
                    "Your device's operating temperature is low, which may compromise your batery's performance, "
                    "your device may unable to charge if temperature is lower than 0°C"
                )
                self.temp_alert_frame.setVisible(True)

            elif temp_c >= 40.0:
                self.temp_badge.setText("⚠️ Hot")
                self.temp_badge.setStyleSheet(
                    "font-size: 11px; font-weight: 700; padding: 3px 12px; "
                    "border-radius: 12px; background-color: #c0392b; color: #ffffff;"
                )
                self.temp_badge.setVisible(True)

                self.temp_alert_frame.setStyleSheet(
                    "background-color: rgba(231, 76, 60, 0.12); border: 1px solid #e74c3c; "
                    "border-radius: 6px;"
                )
                self.temp_alert_icon.setText("⚠️")
                self.temp_alert_text.setStyleSheet("color: #e74c3c;")
                self.temp_alert_text.setText(
                    "The battery temperature is high. Charging may be suspended to protect the battery "
                    "and prolong its lifespan. Please let the battery cool down before charging it again."
                )
                self.temp_alert_frame.setVisible(True)
            else:
                self.temp_badge.setVisible(False)
                self.temp_alert_frame.setVisible(False)
        else:
            self.temp_title_lbl.setText("Temperature: N/A")
            self.temp_bar.set_temperature(None)
            self.temp_badge.setVisible(False)
            self.temp_alert_frame.setVisible(False)

        # 3. Update At a Glance Card Rows
        if status == "Not charging":
            act_text = f"No activity ({cap}%)"
        elif status == "Charging":
            act_text = f"Charging ({cap}%)"
        else:
            act_text = f"Discharging ({cap}%)"
        self.row_current_charge.setText(act_text)

        # Full charge capacity comparison
        if health_pct is not None:
            self.row_capacity_comparison.setText(
                f"{health_pct:.1f}% Capacity (100% Original Capacity)"
            )
            badge_lbl = getattr(self, "row_capacity_comparison_badge", None)
            if badge_lbl:
                badge_lbl.setText(f"✓ {health_grade}" if health_grade == "Good" else f"⚠️ {health_grade}")
                b_color = "#27ae60" if health_grade == "Good" else ("#d35400" if health_grade == "Fair" else "#c0392b")
                badge_lbl.setStyleSheet(
                    f"font-size: 11px; font-weight: 700; padding: 2px 8px; "
                    f"border-radius: 10px; background-color: {b_color}; color: #ffffff;"
                )
                badge_lbl.setVisible(True)
        else:
            self.row_capacity_comparison.setText("N/A")

        # Charge cycles with High (>1000) and Very High (>2000) rules
        cycles_badge = getattr(self, "row_cycles_badge", None)
        if bat.cycle_count is not None and bat.cycle_count > 0:
            c_count = bat.cycle_count
            self.row_cycles.setText(str(c_count))
            if cycles_badge:
                if c_count > 2000:
                    cycles_badge.setText("Very high")
                    cycles_badge.setStyleSheet(
                        "font-size: 11px; font-weight: 700; padding: 2px 8px; "
                        "border-radius: 10px; background-color: #d35400; color: #ffffff;"
                    )
                    cycles_badge.setVisible(True)
                elif c_count > 1000:
                    cycles_badge.setText("High")
                    cycles_badge.setStyleSheet(
                        "font-size: 11px; font-weight: 700; padding: 2px 8px; "
                        "border-radius: 10px; background-color: #f39c12; color: #ffffff;"
                    )
                    cycles_badge.setVisible(True)
                else:
                    cycles_badge.setVisible(False)
        elif bat.cycle_count == 0:
            self.row_cycles.setText("0 (EC unmetered)")
            if cycles_badge:
                cycles_badge.setVisible(False)
        else:
            self.row_cycles.setText("N/A")
            if cycles_badge:
                cycles_badge.setVisible(False)

        chem = bat.technology if bat.technology != "Unknown" else "Li-Polymer"
        self.row_chemistry.setText(chem)

        self.row_adapter.setText("Plugged in" if ac_online else "Disconnected")

        if bat.power_rate_w is not None:
            self.row_power_rate.setText(f"{bat.power_rate_w:.2f} W")
        else:
            self.row_power_rate.setText("N/A")

        if bat.voltage_v is not None:
            min_str = f" (Min: {bat.voltage_min_design_v:.2f} V)" if bat.voltage_min_design_v else ""
            self.row_voltage.setText(f"{bat.voltage_v:.2f} V{min_str}")
        else:
            self.row_voltage.setText("N/A")

        model_parts = []
        if bat.manufacturer and bat.manufacturer != "Unknown":
            model_parts.append(bat.manufacturer)
        if bat.model_name and bat.model_name != "Unknown":
            model_parts.append(bat.model_name)
        self.row_model.setText(" ".join(model_parts) if model_parts else bat.name)

    def _refresh_ui_state(self) -> None:
        snap = self.profile_mgr.monitor.get_snapshot()
        self._update_power_ui(snap)

        active = self.profile_mgr.get_active_profile()
        for val, card in self.cards.items():
            card.set_selected(val == active.value)

        # Update status description
        if self.caps.state == CapabilityState.CONSERVATION_60:
            if active == ChargingProfile.CONSERVATION_60:
                self.status_detail_lbl.setText(
                    f"Conservation Mode active (firmware-capped at ~60%). "
                    f"Current battery: {snap.capacity}%."
                )
            elif active == ChargingProfile.SMART_80:
                state = self.profile_mgr.get_persistent_state()
                self.status_detail_lbl.setText(
                    f"Smart 80% active ({state.last_action}). "
                    f"Current battery: {snap.capacity}%."
                )
            else:
                self.status_detail_lbl.setText(
                    f"Full Charge active. Charging allowed to 100% capacity ({snap.capacity}%)."
                )

        elif self.caps.state == CapabilityState.CONSERVATION_80:
            if active == ChargingProfile.CONSERVATION_80:
                self.status_detail_lbl.setText(
                    f"Conservation Mode active (firmware-capped at 80%). "
                    f"Current battery: {snap.capacity}%."
                )
            else:
                self.status_detail_lbl.setText(
                    f"Full Charge active. Charging allowed to 100% capacity ({snap.capacity}%)."
                )

        elif self.caps.state == CapabilityState.CONFIGURABLE_THRESHOLDS:
            if active == ChargingProfile.CONFIGURABLE_80:
                self.status_detail_lbl.setText(
                    f"Native ThinkPad 80% threshold active (75-80%). "
                    f"Current battery: {snap.capacity}%."
                )
            else:
                self.status_detail_lbl.setText(
                    f"Full Charge active (96-100%). Current battery: {snap.capacity}%."
                )

    def _manual_refresh(self) -> None:
        self.caps = self.profile_mgr.refresh_hardware()
        self._refresh_ui_state()

    def _open_diagnostics(self) -> None:
        dialog = DiagnosticsDialog(self.profile_mgr, self)
        dialog.exec()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.profile_mgr, self)
        dialog.exec()
        self._refresh_ui_state()

    def closeEvent(self, event) -> None:
        self.profile_mgr.monitor.stop()
        super().closeEvent(event)
