"""Dual volume control panel for Monitor and Broadcast streams."""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QFrame
)

logger = logging.getLogger(__name__)


class VolumeSlider(QWidget):
    """Single volume slider with icon label and percentage display."""
    
    volume_changed = Signal(float)  # 0.0 to 1.0
    
    def __init__(self, label_text: str, icon_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)
        
        # Icon + Label
        icon_label = QLabel(f"{icon_text}  {label_text}")
        icon_label.setFixedWidth(120)
        icon_label.setStyleSheet(
            "color: #8b949e; font-size: 12px; font-family: 'Segoe UI';"
        )
        layout.addWidget(icon_label)
        
        # Slider
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(80)
        self._slider.setStyleSheet("""
            QSlider { background: transparent; border: none; }
            QSlider::groove:horizontal {
                border-radius: 2px; height: 4px; background: #CCCCCC;
            }
            QSlider::sub-page:horizontal {
                background: #0055CC; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #0055CC; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #0044AA;
            }
        """)
        self._slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self._slider, 1)
        
        # Percentage label
        self._pct_label = QLabel("80%")
        self._pct_label.setFixedWidth(40)
        self._pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._pct_label.setStyleSheet(
            "color: #000000; font-size: 16px; font-weight: bold; background: transparent; border: none;"
        )
        layout.addWidget(self._pct_label)
    
    def _on_value_changed(self, value: int) -> None:
        self._pct_label.setText(f"{value}%")
        self.volume_changed.emit(value / 100.0)
    
    def set_volume(self, volume: float) -> None:
        """Set slider value (0.0 to 1.0) without emitting signal."""
        self._slider.blockSignals(True)
        self._slider.setValue(int(volume * 100))
        self._pct_label.setText(f"{int(volume * 100)}%")
        self._slider.blockSignals(False)
    
    def volume(self) -> float:
        return self._slider.value() / 100.0


class VolumeControls(QFrame):
    """Panel containing Monitor and Broadcast volume sliders."""
    
    monitor_volume_changed = Signal(float)
    broadcast_volume_changed = Signal(float)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet("""
            VolumeControls {
                background-color: #F0F0F0;
                border-top: 1px solid #CCCCCC;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        
        # Monitor slider
        self._monitor = VolumeSlider("Monitor", "\U0001F3A7")
        self._monitor.volume_changed.connect(self.monitor_volume_changed.emit)
        layout.addWidget(self._monitor)
        
        # Broadcast slider  
        self._broadcast = VolumeSlider("Broadcast", "\U0001F4E1")
        self._broadcast.volume_changed.connect(self.broadcast_volume_changed.emit)
        layout.addWidget(self._broadcast)
    
    def set_monitor_volume(self, volume: float) -> None:
        self._monitor.set_volume(volume)
    
    def set_broadcast_volume(self, volume: float) -> None:
        self._broadcast.set_volume(volume)
