"""Custom waveform display widget with trim handles.

Renders audio waveform peaks using QPainter with cached QPixmap.
Supports draggable start/end trim markers and playback position indicator.
"""

import logging
from typing import Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt, QRect, QRectF, Signal, QPoint
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QPixmap, QPainterPath, QMouseEvent
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QDialog
)
from soundpulse.ui.components import SmoothButton

logger = logging.getLogger(__name__)

# Colors
WAVEFORM_COLOR = QColor(100, 150, 200)           # Muted blue
WAVEFORM_COLOR_DIM = QColor(100, 150, 200, 80)   # Dimmed outside trim
TRIM_HANDLE_COLOR = QColor(0, 85, 204)           # #0055CC
PLAYBACK_COLOR = QColor(63, 185, 80)             # #3fb950
BG_COLOR = QColor(240, 240, 240)                 # #f0f0f0
GRID_COLOR = QColor(204, 204, 204, 150)          # #cccccc with alpha


class WaveformWidget(QWidget):
    """Renders audio waveform with draggable trim handles.
    
    Signals:
        trim_changed(float, float): Emitted when trim handles move (start_pct, end_pct)
    """
    
    trim_changed = Signal(float, float)  # (start_ratio, end_ratio) 0.0-1.0
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMinimumWidth(400)
        
        self._peaks: Optional[np.ndarray] = None  # (N, 2) min/max per bucket
        self._cached_pixmap: Optional[QPixmap] = None
        self._duration: float = 0.0
        
        # Trim positions as ratios (0.0 to 1.0)
        self._trim_start: float = 0.0
        self._trim_end: float = 1.0
        
        # Playback position ratio
        self._playback_pos: float = 0.0
        
        # Drag state
        self._dragging: Optional[str] = None  # "start", "end", or None
        self._handle_width: int = 8
        
        self.setMouseTracking(True)
    
    def set_waveform_data(self, peaks: np.ndarray, duration: float = 0.0) -> None:
        """Set waveform peak data for rendering.
        
        Args:
            peaks: numpy array of shape (N, 2) with [min, max] per bucket.
            duration: Total audio duration in seconds.
        """
        self._peaks = peaks
        self._duration = duration
        self._cached_pixmap = None  # Invalidate cache
        self._trim_start = 0.0
        self._trim_end = 1.0
        self.update()
    
    def set_trim_points(self, start_ratio: float, end_ratio: float) -> None:
        """Set trim positions as ratios (0.0 to 1.0)."""
        self._trim_start = max(0.0, min(1.0, start_ratio))
        self._trim_end = max(self._trim_start, min(1.0, end_ratio))
        self.update()
    
    def get_trim_points(self) -> Tuple[float, float]:
        """Get current trim positions as ratios."""
        return (self._trim_start, self._trim_end)
    
    def set_playback_position(self, ratio: float) -> None:
        """Set playback indicator position (0.0 to 1.0)."""
        self._playback_pos = max(0.0, min(1.0, ratio))
        self.update()
    
    def clear(self) -> None:
        """Clear all waveform data."""
        self._peaks = None
        self._cached_pixmap = None
        self._trim_start = 0.0
        self._trim_end = 1.0
        self._playback_pos = 0.0
        self.update()
    
    def paintEvent(self, event) -> None:
        """Render the waveform, trim handles, and playback indicator."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        # Background
        painter.fillRect(0, 0, w, h, BG_COLOR)
        
        if self._peaks is None or len(self._peaks) == 0:
            # Empty state
            painter.setPen(QPen(QColor("#8b949e")))
            painter.drawText(self.rect(), Qt.AlignCenter, "No audio loaded")
            painter.end()
            return
        
        mid_y = h / 2
        num_points = len(self._peaks)
        
        # Draw center line
        painter.setPen(QPen(GRID_COLOR, 1))
        painter.drawLine(0, int(mid_y), w, int(mid_y))
        
        # Draw waveform bars
        trim_start_px = int(self._trim_start * w)
        trim_end_px = int(self._trim_end * w)
        
        bar_width = max(1, w / num_points)
        
        for i in range(num_points):
            x = int(i * w / num_points)
            min_val = self._peaks[i, 0]
            max_val = self._peaks[i, 1]
            
            y_top = int(mid_y - max_val * mid_y * 0.9)
            y_bot = int(mid_y - min_val * mid_y * 0.9)
            bar_h = max(1, y_bot - y_top)
            
            # Use dim color outside trim region
            if trim_start_px <= x <= trim_end_px:
                painter.fillRect(int(x), y_top, max(1, int(bar_width)), bar_h, WAVEFORM_COLOR)
            else:
                painter.fillRect(int(x), y_top, max(1, int(bar_width)), bar_h, WAVEFORM_COLOR_DIM)
        
        # Draw trim handles
        handle_pen = QPen(TRIM_HANDLE_COLOR, 2)
        painter.setPen(handle_pen)
        
        # Start handle
        sx = int(self._trim_start * w)
        painter.drawLine(sx, 0, sx, h)
        painter.fillRect(sx - 3, 0, 6, h, QColor(124, 58, 237, 60))
        # Handle grip
        painter.fillRect(sx - 4, int(h/2) - 15, 8, 30, TRIM_HANDLE_COLOR)
        
        # End handle
        ex = int(self._trim_end * w)
        painter.drawLine(ex, 0, ex, h)
        painter.fillRect(ex - 3, 0, 6, h, QColor(124, 58, 237, 60))
        painter.fillRect(ex - 4, int(h/2) - 15, 8, 30, TRIM_HANDLE_COLOR)
        
        # Playback position
        if self._playback_pos > 0:
            px = int(self._playback_pos * w)
            painter.setPen(QPen(PLAYBACK_COLOR, 2))
            painter.drawLine(px, 0, px, h)
        
        painter.end()
    
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            w = self.width()
            
            start_px = self._trim_start * w
            end_px = self._trim_end * w
            
            # Check if near a handle (within 10px)
            if abs(x - start_px) < 10:
                self._dragging = "start"
            elif abs(x - end_px) < 10:
                self._dragging = "end"
    
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x = event.position().x()
        w = self.width()
        
        if self._dragging == "start":
            ratio = max(0.0, min(self._trim_end - 0.01, x / w))
            self._trim_start = ratio
            self.trim_changed.emit(self._trim_start, self._trim_end)
            self.update()
        elif self._dragging == "end":
            ratio = max(self._trim_start + 0.01, min(1.0, x / w))
            self._trim_end = ratio
            self.trim_changed.emit(self._trim_start, self._trim_end)
            self.update()
        else:
            # Change cursor near handles
            start_px = self._trim_start * w
            end_px = self._trim_end * w
            if abs(x - start_px) < 10 or abs(x - end_px) < 10:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
    
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = None
    
    def resizeEvent(self, event) -> None:
        self._cached_pixmap = None  # Invalidate on resize
        super().resizeEvent(event)


class TrimDialog(QDialog):
    """Dialog for trimming audio with waveform preview."""
    
    def __init__(
        self, peaks: np.ndarray, duration: float,
        trim_start: float = 0.0, trim_end: float = 0.0,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Trim Audio")
        self.setMinimumSize(600, 280)
        self.setModal(True)
        
        self._duration = duration
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("Drag the handles to set start and end points")
        title.setStyleSheet("color: #666666; font-size: 12px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Waveform widget
        self._waveform = WaveformWidget()
        self._waveform.set_waveform_data(peaks, duration)
        
        # Set initial trim positions
        if trim_end > 0 and duration > 0:
            self._waveform.set_trim_points(
                trim_start / duration,
                trim_end / duration
            )
        
        self._waveform.trim_changed.connect(self._on_trim_changed)
        layout.addWidget(self._waveform)
        
        # Time labels
        time_layout = QHBoxLayout()
        self._start_label = QLabel(self._format_time(trim_start))
        self._start_label.setStyleSheet("color: #0055CC; font-size: 13px; font-weight: 600;")
        self._end_label = QLabel(self._format_time(trim_end if trim_end > 0 else duration))
        self._end_label.setStyleSheet("color: #0055CC; font-size: 13px; font-weight: 600;")
        self._duration_label = QLabel(f"Duration: {self._format_time(duration)}")
        self._duration_label.setStyleSheet("color: #666666; font-size: 12px;")
        self._duration_label.setAlignment(Qt.AlignCenter)
        time_layout.addWidget(self._start_label)
        time_layout.addWidget(self._duration_label, 1)
        time_layout.addWidget(self._end_label)
        layout.addLayout(time_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = SmoothButton("Cancel")
        cancel_btn.set_colors("#E0E0E0", "#D0D0D0", "#C0C0C0")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        apply_btn = SmoothButton("Apply Trim")
        apply_btn.set_colors("#0055CC", "#0066EE", "#0044AA", text_hex="#ffffff")
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(apply_btn)
        
        layout.addLayout(btn_layout)
        
        # Store current trim values in seconds
        self._trim_start_sec = trim_start
        self._trim_end_sec = trim_end if trim_end > 0 else duration
    
    def _on_trim_changed(self, start_ratio: float, end_ratio: float) -> None:
        self._trim_start_sec = start_ratio * self._duration
        self._trim_end_sec = end_ratio * self._duration
        self._start_label.setText(self._format_time(self._trim_start_sec))
        self._end_label.setText(self._format_time(self._trim_end_sec))
    
    def get_trim_seconds(self) -> Tuple[float, float]:
        """Return (start_seconds, end_seconds)."""
        return (self._trim_start_sec, self._trim_end_sec)
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        mins = int(seconds) // 60
        secs = seconds % 60
        return f"{mins}:{secs:05.2f}"
