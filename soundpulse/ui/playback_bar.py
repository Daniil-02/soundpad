"""Playback control bar with timeline slider."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSlider
from soundpulse.ui.components import SmoothButton

class PlaybackBar(QWidget):
    pause_requested = Signal()
    stop_requested = Signal()
    seek_requested = Signal(float)  # position in seconds
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet("background-color: #F0F0F0; border-top: 1px solid #CCCCCC;")
        
        self._is_seeking = False
        self._total_sec = 0.0
        
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)
        
        # Play/Pause
        self._play_pause_btn = SmoothButton("▶ Play")
        self._play_pause_btn.set_colors("#6366f1", "#4f46e5", "#4338ca", text_hex="#FFFFFF")
        self._play_pause_btn.setFixedWidth(80)
        self._play_pause_btn.clicked.connect(self.pause_requested.emit)
        layout.addWidget(self._play_pause_btn)
        
        # Stop
        self._stop_btn = SmoothButton("■ Stop")
        self._stop_btn.set_colors("#f43f5e", "#e11d48", "#be123c", text_hex="#FFFFFF")
        self._stop_btn.setFixedWidth(70)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self._stop_btn)
        
        # Time Label
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setStyleSheet("color: #000000; font-size: 13px; font-variant-numeric: tabular-nums; border: none;")
        self._time_label.setFixedWidth(90)
        self._time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._time_label)
        
        # Slider
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setStyleSheet("""
            QSlider { border: none; background: transparent; }
            QSlider::groove:horizontal {
                border-radius: 2px; height: 4px; background: #CCCCCC;
            }
            QSlider::sub-page:horizontal {
                background: #0055CC; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #0055CC; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
            }
        """)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        # Also allow seeking by clicking directly on the slider track
        self._slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self._slider, 1)
        
        self.set_active(False)
        
    def _on_slider_pressed(self):
        self._is_seeking = True
        
    def _on_slider_released(self):
        self._is_seeking = False
        val = self._slider.value()
        pos_sec = (val / 1000.0) * self._total_sec
        self.seek_requested.emit(pos_sec)
        
    def _on_slider_value_changed(self, val):
        """Update label instantly while dragging."""
        if self._is_seeking and self._total_sec > 0:
            current_sec = (val / 1000.0) * self._total_sec
            self._update_time_label(current_sec, self._total_sec)
            
    @property
    def is_seeking(self):
        return self._is_seeking
        
    def set_active(self, active: bool):
        """Enable or disable the slider based on playback state, but keep buttons active."""
        if not active:
            self._slider.blockSignals(True)
            self._slider.setValue(0)
            self._slider.blockSignals(False)
            self._slider.setEnabled(False)
            self._time_label.setText("0:00 / 0:00")
            self._total_sec = 0.0
            self._play_pause_btn.setText("▶ Play")
        else:
            self._slider.setEnabled(True)
            
    def update_progress(self, current_sec: float, total_sec: float, is_paused: bool = False):
        """Update the UI with current playback progress."""
        if not self._slider.isEnabled():
            self._slider.setEnabled(True)
            
        self._total_sec = total_sec
        
        if not self._is_seeking:
            if total_sec > 0:
                val = int((current_sec / total_sec) * 1000)
                self._slider.blockSignals(True)
                self._slider.setValue(val)
                self._slider.blockSignals(False)
            self._update_time_label(current_sec, total_sec)
            
        if is_paused:
            self._play_pause_btn.setText("▶ Play")
        else:
            self._play_pause_btn.setText("⏸ Pause")
            
    def _update_time_label(self, current_sec: float, total_sec: float):
        curr_m = int(current_sec // 60)
        curr_s = int(current_sec % 60)
        tot_m = int(total_sec // 60)
        tot_s = int(total_sec % 60)
        self._time_label.setText(f"{curr_m}:{curr_s:02d} / {tot_m}:{tot_s:02d}")
