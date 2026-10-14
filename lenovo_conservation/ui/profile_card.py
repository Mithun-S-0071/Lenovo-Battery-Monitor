"""Selectable card widget for charging profiles."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lenovo_conservation.hardware_detection import ChargingProfile


class ProfileCard(QFrame):
    """Interactive card widget representing a charging profile."""

    clicked = Signal(str)  # Emits profile value

    def __init__(
        self,
        profile: ChargingProfile,
        title: str,
        subtitle: str,
        badge_text: str = "",
        is_selected: bool = False,
        warning_text: str = "",
        note_text: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.profile = profile
        self.title_text = title
        self.subtitle_text = subtitle
        self.badge_text = badge_text
        self.warning_text = warning_text
        self.note_text = note_text
        self._selected = is_selected

        self.setCursor(Qt.PointingHandCursor)
        self._init_ui()
        self.set_selected(is_selected)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # Top row: Title and Badge
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.title_label = QLabel(self.title_text)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        top_row.addWidget(self.title_label)

        top_row.addStretch()

        if self.badge_text:
            self.badge_label = QLabel(self.badge_text)
            self.badge_label.setStyleSheet(
                "font-size: 11px; font-weight: 600; padding: 2px 8px; "
                "border-radius: 10px; background-color: rgba(61, 174, 233, 0.18); "
                "color: #3daee9;"
            )
            top_row.addWidget(self.badge_label)

        self.check_indicator = QLabel("● Active" if self._selected else "○ Select")
        self.check_indicator.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #3daee9;" if self._selected
            else "font-size: 12px; color: #888888;"
        )
        top_row.addWidget(self.check_indicator)

        layout.addLayout(top_row)

        # Description
        self.desc_label = QLabel(self.subtitle_text)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("font-size: 12px; color: #999999; line-height: 1.3;")
        layout.addWidget(self.desc_label)

        # Warning text (e.g. for Full Charge)
        if self.warning_text:
            self.warning_label = QLabel(f"⚠️ {self.warning_text}")
            self.warning_label.setWordWrap(True)
            self.warning_label.setStyleSheet("font-size: 11px; color: #f39c12; font-style: italic;")
            layout.addWidget(self.warning_label)

        # Informational note text (e.g. for Smart 80%)
        if self.note_text:
            self.note_label = QLabel(f"ℹ️ {self.note_text}")
            self.note_label.setWordWrap(True)
            self.note_label.setStyleSheet("font-size: 11px; color: #3daee9; font-style: italic;")
            layout.addWidget(self.note_label)

    def set_selected(self, selected: bool) -> None:
        """Update visual selection state."""
        self._selected = selected
        if selected:
            self.setObjectName("ProfileCardSelected")
            self.check_indicator.setText("✓ Active")
            self.check_indicator.setStyleSheet("font-size: 12px; font-weight: 700; color: #2ecc71;")
        else:
            self.setObjectName("ProfileCard")
            self.check_indicator.setText("Select")
            self.check_indicator.setStyleSheet("font-size: 12px; color: #888888;")

        # Re-apply stylesheet state
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.profile.value)
        super().mousePressEvent(event)
