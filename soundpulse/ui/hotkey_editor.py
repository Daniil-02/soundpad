"""Hotkey capture dialog.

Modal dialog that captures a keyboard shortcut from the user
for binding to a sound trigger.
"""

import ctypes
from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget
)

from soundpulse.ui.components import SmoothButton

from soundpulse.models.sound_item import (
    VK_NAMES, MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN
)

# Map Qt keys to Windows virtual key codes
QT_TO_VK = {
    Qt.Key_F1: 0x70, Qt.Key_F2: 0x71, Qt.Key_F3: 0x72, Qt.Key_F4: 0x73,
    Qt.Key_F5: 0x74, Qt.Key_F6: 0x75, Qt.Key_F7: 0x76, Qt.Key_F8: 0x77,
    Qt.Key_F9: 0x78, Qt.Key_F10: 0x79, Qt.Key_F11: 0x7A, Qt.Key_F12: 0x7B,
    Qt.Key_0: 0x30, Qt.Key_1: 0x31, Qt.Key_2: 0x32, Qt.Key_3: 0x33,
    Qt.Key_4: 0x34, Qt.Key_5: 0x35, Qt.Key_6: 0x36, Qt.Key_7: 0x37,
    Qt.Key_8: 0x38, Qt.Key_9: 0x39,
    Qt.Key_A: 0x41, Qt.Key_B: 0x42, Qt.Key_C: 0x43, Qt.Key_D: 0x44,
    Qt.Key_E: 0x45, Qt.Key_F: 0x46, Qt.Key_G: 0x47, Qt.Key_H: 0x48,
    Qt.Key_I: 0x49, Qt.Key_J: 0x4A, Qt.Key_K: 0x4B, Qt.Key_L: 0x4C,
    Qt.Key_M: 0x4D, Qt.Key_N: 0x4E, Qt.Key_O: 0x4F, Qt.Key_P: 0x50,
    Qt.Key_Q: 0x51, Qt.Key_R: 0x52, Qt.Key_S: 0x53, Qt.Key_T: 0x54,
    Qt.Key_U: 0x55, Qt.Key_V: 0x56, Qt.Key_W: 0x57, Qt.Key_X: 0x58,
    Qt.Key_Y: 0x59, Qt.Key_Z: 0x5A,
    Qt.Key_Space: 0x20, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
    Qt.Key_Tab: 0x09, Qt.Key_Escape: 0x1B,
    Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E,
    Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22,
    Qt.Key_Up: 0x26, Qt.Key_Down: 0x28, Qt.Key_Left: 0x25, Qt.Key_Right: 0x27,
}

# Add numpad keys
for i in range(10):
    # Qt numpad keys don't have a simple offset, map them individually
    pass
# Numpad 0-9 in Qt: there's no direct Qt.Key_NumPad0, use custom mapping


class HotkeyEditorDialog(QDialog):
    """Dialog for capturing a hotkey combination.
    
    Shows a prompt and captures the next key + modifiers pressed.
    Returns the Windows VK code and modifier bitmask.
    """
    
    def __init__(self, parent: Optional[QWidget] = None, current_vk: int = 0, current_mod: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Set Hotkey")
        self.setFixedSize(420, 260)
        self.setModal(True)
        
        self._captured_vk: int = current_vk
        self._captured_mod: int = current_mod
        self._is_capturing: bool = True
        
        self._setup_ui()
        self._update_display()
    
    def _setup_ui(self) -> None:
        self.setStyleSheet("QDialog { background-color: #F8F9FA; }")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(32, 24, 32, 24)
        
        # Title
        title = QLabel("Set Hotkey Combination")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #1E1E2E; font-family: 'Segoe UI', sans-serif;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel("Press any key with optional Ctrl, Alt, Shift modifiers")
        subtitle.setStyleSheet("font-size: 13px; color: #6C757D; font-family: 'Segoe UI', sans-serif;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        
        # Display label showing captured key
        self._display_label = QLabel("Waiting...")
        self._display_label.setAlignment(Qt.AlignCenter)
        self._display_label.setMinimumHeight(60)
        layout.addWidget(self._display_label)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        clear_btn = SmoothButton("Clear")
        clear_btn.set_colors("#E9ECEF", "#DEE2E6", "#CED4DA", text_hex="#495057")
        clear_btn.setMinimumWidth(90)
        clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        
        cancel_btn = SmoothButton("Cancel")
        cancel_btn.set_colors("#E9ECEF", "#DEE2E6", "#CED4DA", text_hex="#495057")
        cancel_btn.setMinimumWidth(90)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        self._apply_btn = SmoothButton("Apply")
        self._apply_btn.set_colors("#0D6EFD", "#0B5ED7", "#0A58CA", text_hex="#FFFFFF")
        self._apply_btn.setMinimumWidth(90)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._apply_btn)
        
        layout.addLayout(btn_layout)
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Capture key press events."""
        if not self._is_capturing:
            super().keyPressEvent(event)
            return
        
        key = event.key()
        
        # Ignore pure modifier presses
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
        
        # Map Qt key to Windows VK code
        vk = QT_TO_VK.get(key, 0)
        if vk == 0:
            return  # Unmapped key, ignore
        
        # Build modifier bitmask
        qt_mod = event.modifiers()
        mod = 0
        if qt_mod & Qt.ControlModifier:
            mod |= MOD_CTRL
        if qt_mod & Qt.AltModifier:
            mod |= MOD_ALT
        if qt_mod & Qt.ShiftModifier:
            mod |= MOD_SHIFT
        if qt_mod & Qt.MetaModifier:
            mod |= MOD_WIN
        
        self._captured_vk = vk
        self._captured_mod = mod
        self._update_display()
    
    def _update_display(self) -> None:
        """Update the display label with the current captured key."""
        base_style = (
            "border-radius: 8px; padding: 12px; font-family: 'Segoe UI', sans-serif;"
        )
        
        if self._captured_vk == 0:
            self._display_label.setText("Waiting...")
            self._display_label.setStyleSheet(
                base_style + 
                "background-color: #FFFFFF; color: #ADB5BD; "
                "border: 2px dashed #CED4DA; font-size: 18px; font-weight: normal;"
            )
        else:
            parts = []
            if self._captured_mod & MOD_CTRL: parts.append("Ctrl")
            if self._captured_mod & MOD_ALT: parts.append("Alt")
            if self._captured_mod & MOD_SHIFT: parts.append("Shift")
            if self._captured_mod & MOD_WIN: parts.append("Win")
            
            key_name = VK_NAMES.get(self._captured_vk, f"0x{self._captured_vk:02X}")
            parts.append(key_name)
            display = " + ".join(parts)
            
            self._display_label.setText(display)
            self._display_label.setStyleSheet(
                base_style + 
                "background-color: #E7F1FF; color: #0D6EFD; "
                "border: 2px solid #0D6EFD; font-size: 22px; font-weight: bold;"
            )
    
    def _on_clear(self) -> None:
        """Clear the captured hotkey."""
        self._captured_vk = 0
        self._captured_mod = 0
        self._update_display()
    
    def get_hotkey(self) -> Tuple[int, int]:
        """Return the captured (vk_code, modifiers) tuple."""
        return (self._captured_vk, self._captured_mod)

    def _on_apply(self) -> None:
        """Apply the captured hotkey and close the dialog."""
        self.accept()
