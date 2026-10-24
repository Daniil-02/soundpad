"""Custom UI components for SoundPulse."""

from PySide6.QtCore import QVariantAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton

class SmoothButton(QPushButton):
    """QPushButton styled with robust, pure QSS pseudo-states."""
    
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        
        # Light theme default colors
        self.set_colors("#E0E0E0", "#D0D0D0", "#C0C0C0", "#000000")
    
    def set_colors(self, default_hex: str, hover_hex: str, pressed_hex: str, text_hex: str = "#e6edf3") -> None:
        """Customize the button colors."""
        qss = f"""
            QPushButton {{
                background-color: {default_hex};
                color: {text_hex};
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 500;
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {hover_hex};
            }}
            QPushButton:pressed {{
                background-color: {pressed_hex};
            }}
            QPushButton:focus {{
                outline: none;
                border: none;
            }}
            QPushButton:disabled {{
                background-color: #F0F0F0;
                color: #A0A0A0;
            }}
        """
        self.setStyleSheet(qss)
