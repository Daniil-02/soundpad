"""Instant search/filter bar with debouncing."""

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton

logger = logging.getLogger(__name__)

DEBOUNCE_MS = 150  # Debounce delay for search input


class SearchBar(QWidget):
    """Styled search bar with debounced text_changed signal."""
    
    text_changed = Signal(str)  # Emitted after debounce with current text
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._emit_text)
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Search input
        self._input = QLineEdit()
        self._input.setPlaceholderText("  \U0001F50D  Search sounds...")
        self._input.setClearButtonEnabled(True)
        self._input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #CCCCCC;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
                font-family: 'Segoe UI';
            }
            QLineEdit:focus {
                border: 1px solid #0055CC;
            }
        """)
        self._input.textChanged.connect(self._on_text_input)
        layout.addWidget(self._input)
    
    def _on_text_input(self, text: str) -> None:
        """Called on every keystroke — restarts the debounce timer."""
        self._debounce_timer.start()
    
    def _emit_text(self) -> None:
        """Emit the debounced text_changed signal."""
        self.text_changed.emit(self._input.text().strip())
    
    def clear(self) -> None:
        """Clear the search input."""
        self._input.clear()
    
    def text(self) -> str:
        """Get current search text."""
        return self._input.text().strip()
