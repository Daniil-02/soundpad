"""Settings dialog with tabbed interface.

Provides device configuration, hotkey management,
and general application settings.
"""

import logging
from typing import List, Optional

import os
import urllib.request
import zipfile
import tempfile
import subprocess

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QComboBox,
    QRadioButton, QButtonGroup, QCheckBox,
    QGroupBox, QPushButton, QFormLayout, QSpacerItem, QSizePolicy
)
from PySide6.QtGui import QKeyEvent

from soundpulse.ui.components import SmoothButton
from soundpulse.audio.engine import DualStreamEngine
from soundpulse.config.settings import Settings
from soundpulse.models.sound_item import VK_NAMES, MOD_CTRL, MOD_ALT, MOD_SHIFT, MOD_WIN
from soundpulse.ui.hotkey_editor import HotkeyEditorDialog, QT_TO_VK

logger = logging.getLogger(__name__)

class KeybindButton(QPushButton):
    keybind_changed = Signal(int, int) # vk, modifiers
    
    def __init__(self, parent=None):
        super().__init__("None", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background-color: #E8EAED;
                color: #202124;
                border: 1px solid #DADCE0;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
                font-size: 13px;
                text-align: center;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #F1F3F4;
                border: 1px solid #D2E3FC;
            }
        """)
        self._is_listening = False
        self._vk = 0
        self._modifiers = 0
        self.clicked.connect(self._start_listening)
        
    def _start_listening(self):
        self._is_listening = True
        self.setText("Listening...")
        self.setStyleSheet("""
            QPushButton {
                background-color: #E8F0FE;
                color: #1967D2;
                border: 2px solid #1A73E8;
                border-radius: 4px;
                padding: 5px 15px;
                font-weight: bold;
                font-size: 13px;
                text-align: center;
                min-height: 24px;
            }
        """)
        self.setFocus()
        
    def set_keybind(self, vk: int, modifiers: int, text: str):
        self._is_listening = False
        self._vk = vk
        self._modifiers = modifiers
        self.setText(text if vk != 0 else "Click to bind...")
        self.setStyleSheet("""
            QPushButton {
                background-color: #E8EAED;
                color: #202124;
                border: 1px solid #DADCE0;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
                font-size: 13px;
                text-align: center;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #F1F3F4;
                border: 1px solid #D2E3FC;
            }
        """)
        self.clearFocus()
        
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._is_listening:
            super().keyPressEvent(event)
            return
            
        key = event.key()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
            
        vk = QT_TO_VK.get(key, 0)
        if vk == 0:
            if key == Qt.Key_Escape:
                self.keybind_changed.emit(self._vk, self._modifiers) # cancel
            return
            
        mods = event.modifiers()
        out_mod = 0
        if mods & Qt.ControlModifier: out_mod |= MOD_CTRL
        if mods & Qt.AltModifier: out_mod |= MOD_ALT
        if mods & Qt.ShiftModifier: out_mod |= MOD_SHIFT
        if mods & Qt.MetaModifier: out_mod |= MOD_WIN
        
        self.keybind_changed.emit(vk, out_mod)
        
    def focusOutEvent(self, event):
        if self._is_listening:
            self.keybind_changed.emit(self._vk, self._modifiers) # cancel
        super().focusOutEvent(event)

class DriverInstallWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str)
    
    def run(self):
        url = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack43.zip"
        try:
            self.progress.emit("Downloading driver...")
            temp_dir = tempfile.mkdtemp()
            zip_path = os.path.join(temp_dir, "vbcable.zip")
            
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
                out_file.write(response.read())
            
            self.progress.emit("Extracting driver...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
                
            self.progress.emit("Installing driver...")
            setup_exe = os.path.join(temp_dir, "VBCABLE_Setup_x64.exe")
            if not os.path.exists(setup_exe):
                self.finished.emit(False, "Setup executable not found in downloaded zip.")
                return
                
            # Run silently as admin if possible, but -i -h works for standard VBCable
            result = subprocess.run([setup_exe, "-i", "-h"], capture_output=True)
            if result.returncode == 0:
                self.finished.emit(True, "Success")
            else:
                self.finished.emit(False, f"Installer failed with code {result.returncode}")
                
        except Exception as e:
            self.finished.emit(False, str(e))


class SettingsDialog(QDialog):
    """Application settings dialog with Devices, General tabs.
    
    Signals:
        settings_changed: Emitted when user clicks Apply/OK.
    """
    
    settings_changed = Signal()
    
    def __init__(
        self,
        engine: DualStreamEngine,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 400)
        self.setModal(True)
        
        self._engine = engine
        self._settings = Settings.instance()
        
        self._setup_ui()
        self._load_current_settings()
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                background-color: #F0F0F0;
                border: 1px solid #CCCCCC;
                border-top: none;
            }
            QTabBar::tab {
                background-color: #E0E0E0;
                color: #333333;
                border: 1px solid #CCCCCC;
                border-bottom: none;
                padding: 10px 24px;
                font-size: 13px;
                font-family: 'Segoe UI';
            }
            QTabBar::tab:selected {
                background-color: #F0F0F0;
                color: #000000;
                border-bottom: 2px solid #0055CC;
            }
            QTabBar::tab:hover:!selected {
                background-color: #E8E8E8;
                color: #000000;
            }
        """)
        
        # Devices tab
        self._tabs.addTab(self._create_devices_tab(), "Audio Devices")
        
        # General tab
        self._tabs.addTab(self._create_general_tab(), "General")
        
        layout.addWidget(self._tabs)
        
        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(16, 12, 16, 12)
        btn_layout.addStretch()
        
        cancel_btn = SmoothButton("Cancel")
        cancel_btn.set_colors("#E0E0E0", "#D0D0D0", "#C0C0C0")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        apply_btn = SmoothButton("Apply")
        apply_btn.set_colors("#0055CC", "#0066EE", "#0044AA", text_hex="#ffffff")
        apply_btn.clicked.connect(self._apply_settings)
        btn_layout.addWidget(apply_btn)
        
        layout.addLayout(btn_layout)
    
    def _create_devices_tab(self) -> QWidget:
        tab = QWidget()
        tab.setStyleSheet("background-color: #F0F0F0; color: #000000;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        
        # Monitor device
        monitor_group = QGroupBox("\U0001F3A7 Monitor Device (Headphones/Speakers)")
        monitor_group.setStyleSheet(
            "QGroupBox { color: #000000; font-size: 13px; font-weight: 600; "
            "border: 1px solid #CCCCCC; border-radius: 8px; margin-top: 12px; padding-top: 20px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        monitor_layout = QVBoxLayout(monitor_group)
        self._monitor_combo = QComboBox()
        self._monitor_combo.setStyleSheet(
            "QComboBox { background-color: #FFFFFF; color: #000000; "
            "border: 1px solid #CCCCCC; border-radius: 6px; padding: 8px; font-size: 13px; }"
            "QComboBox:hover { border-color: #0055CC; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background-color: #FFFFFF; color: #000000; "
            "border: 1px solid #CCCCCC; selection-background-color: #0055CC; selection-color: #FFFFFF; }"
        )
        monitor_layout.addWidget(self._monitor_combo)
        layout.addWidget(monitor_group)
        
        # Broadcast device
        broadcast_group = QGroupBox("\U0001F4E1 Broadcast Device (Virtual Cable)")
        broadcast_group.setStyleSheet(
            "QGroupBox { color: #000000; font-size: 13px; font-weight: 600; "
            "border: 1px solid #CCCCCC; border-radius: 8px; margin-top: 12px; padding-top: 20px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        broadcast_layout = QVBoxLayout(broadcast_group)
        self._broadcast_combo = QComboBox()
        self._broadcast_combo.setStyleSheet(self._monitor_combo.styleSheet())
        broadcast_layout.addWidget(self._broadcast_combo)
        layout.addWidget(broadcast_group)

        # Microphone device
        mic_group = QGroupBox("\U0001F3A4 Microphone Input (Physical Mic)")
        mic_group.setStyleSheet(
            "QGroupBox { color: #000000; font-size: 13px; font-weight: 600; "
            "border: 1px solid #CCCCCC; border-radius: 8px; margin-top: 12px; padding-top: 20px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        mic_layout = QVBoxLayout(mic_group)
        self._mic_combo = QComboBox()
        self._mic_combo.setStyleSheet(self._monitor_combo.styleSheet())
        mic_layout.addWidget(self._mic_combo)
        layout.addWidget(mic_group)
        
        # Install Driver Section
        install_layout = QHBoxLayout()
        self._install_btn = SmoothButton("Install SoundPulse Audio Driver")
        self._install_btn.set_colors("#0055CC", "#0066EE", "#0044AA", text_hex="#ffffff")
        self._install_btn.clicked.connect(self._on_install_driver)
        install_layout.addWidget(self._install_btn)
        
        self._install_status = QLabel("")
        self._install_status.setStyleSheet("color: #666666; font-size: 12px;")
        install_layout.addWidget(self._install_status)
        install_layout.addStretch()
        
        layout.addLayout(install_layout)
        
        # Refresh button
        refresh_btn = SmoothButton("\U0001F504  Refresh Devices")
        refresh_btn.set_colors("#E0E0E0", "#D0D0D0", "#C0C0C0")
        refresh_btn.clicked.connect(self._refresh_devices)
        layout.addWidget(refresh_btn, 0, Qt.AlignLeft)
        
        layout.addStretch()
        return tab
        
    def _on_install_driver(self) -> None:
        """Call engine to install virtual driver. If missing, download and install."""
        from PySide6.QtWidgets import QMessageBox
        
        # Try local first
        ret = self._engine.install_virtual_driver()
        if ret == 0:
            self._install_status.setText("Driver ready")
            self._install_status.setStyleSheet("color: #3fb950; font-size: 12px; font-weight: bold;")
            QMessageBox.information(self, "Success", "Virtual Audio Driver installed/enabled successfully.")
            self._refresh_devices()
            return
        elif ret == 5:
            self._install_status.setText("UAC Denied")
            self._install_status.setStyleSheet("color: #e84f4f; font-size: 12px; font-weight: bold;")
            QMessageBox.warning(self, "Elevation Required", "Driver installation requires Administrator privileges. Please run SoundPulse as Administrator and try again.")
            return

        # Local failed/missing, fallback to download
        self._install_status.setText("Preparing download...")
        self._install_status.setStyleSheet("color: #0055CC; font-size: 12px; font-weight: bold;")
        self._install_status.repaint()
        
        self._worker = DriverInstallWorker(self)
        self._worker.progress.connect(self._on_install_progress)
        self._worker.finished.connect(self._on_install_finished)
        self._worker.start()
        
    def _on_install_progress(self, msg: str) -> None:
        self._install_status.setText(msg)
        self._install_status.repaint()
        
    def _on_install_finished(self, success: bool, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        if success:
            self._install_status.setText("Driver ready")
            self._install_status.setStyleSheet("color: #3fb950; font-size: 12px; font-weight: bold;")
            QMessageBox.information(self, "Success", "Virtual Audio Driver downloaded and installed successfully.\nPlease restart the application if devices don't appear.")
            self._refresh_devices()
        else:
            self._install_status.setText("Install failed")
            self._install_status.setStyleSheet("color: #e84f4f; font-size: 12px; font-weight: bold;")
            QMessageBox.warning(self, "Error", f"Failed to download or install Virtual Audio Driver:\n{msg}")
    
    def _create_general_tab(self) -> QWidget:
        tab = QWidget()
        tab.setStyleSheet("background-color: #F0F0F0; color: #000000;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        
        # Stop Audio Keybind (Modern UI)
        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(16)
        
        keybind_layout = QHBoxLayout()
        keybind_layout.setSpacing(8)
        keybind_layout.setContentsMargins(0, 0, 0, 0)
        
        self._keybind_btn = KeybindButton()
        self._keybind_btn.keybind_changed.connect(self._on_keybind_changed)
        keybind_layout.addWidget(self._keybind_btn)
        
        self._clear_keybind_btn = QPushButton("Clear")
        self._clear_keybind_btn.setCursor(Qt.PointingHandCursor)
        self._clear_keybind_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8EAED;
                color: #202124;
                border: 1px solid #DADCE0;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
                font-size: 13px;
                text-align: center;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #FCE8E6;
                color: #D93025;
                border: 1px solid #FAD2CF;
            }
        """)
        self._clear_keybind_btn.setToolTip("Clear Keybind")
        self._clear_keybind_btn.clicked.connect(self._on_clear_stop_hotkey)
        keybind_layout.addWidget(self._clear_keybind_btn)
        
        keybind_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        
        label = QLabel("Global Stop Keybind:")
        label.setStyleSheet("color: #000000; font-size: 14px; font-weight: 500;")
        form_layout.addRow(label, keybind_layout)
        
        layout.addLayout(form_layout)
        
        # Overlap mode
        overlap_group = QGroupBox("Playback Overlap Mode")
        overlap_group.setStyleSheet(
            "QGroupBox { color: #000000; font-size: 13px; font-weight: 600; "
            "border: 1px solid #CCCCCC; border-radius: 8px; margin-top: 12px; padding-top: 20px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        overlap_layout = QVBoxLayout(overlap_group)
        
        self._overlap_group = QButtonGroup(self)
        
        self._restart_radio = QRadioButton("Restart — Stop previous sound, play new one")
        self._restart_radio.setStyleSheet("color: #000000; font-size: 13px; padding: 4px;")
        self._overlap_group.addButton(self._restart_radio)
        overlap_layout.addWidget(self._restart_radio)
        
        self._mix_radio = QRadioButton("Mix — Layer new sound over currently playing")
        self._mix_radio.setStyleSheet("color: #000000; font-size: 13px; padding: 4px;")
        self._overlap_group.addButton(self._mix_radio)
        overlap_layout.addWidget(self._mix_radio)
        
        layout.addWidget(overlap_group)
        
        layout.addStretch()
        
        return tab
        
    def _format_hotkey(self, vk: int, modifiers: int) -> str:
        if vk == 0:
            return "None"
        parts = []
        if modifiers & MOD_CTRL:
            parts.append("Ctrl")
        if modifiers & MOD_ALT:
            parts.append("Alt")
        if modifiers & MOD_SHIFT:
            parts.append("Shift")
        if modifiers & MOD_WIN:
            parts.append("Win")
        key_name = VK_NAMES.get(vk, f"0x{vk:02X}")
        parts.append(key_name)
        return "+".join(parts)
        
    def _on_keybind_changed(self, vk: int, mod: int) -> None:
        self._temp_panic_vk = vk
        self._temp_panic_mod = mod
        self._update_keybind_ui()
            
    def _on_clear_stop_hotkey(self) -> None:
        self._temp_panic_vk = 0
        self._temp_panic_mod = 0
        self._update_keybind_ui()
        
    def _update_keybind_ui(self) -> None:
        text = self._format_hotkey(self._temp_panic_vk, self._temp_panic_mod)
        self._keybind_btn.set_keybind(self._temp_panic_vk, self._temp_panic_mod, text)
        self._clear_keybind_btn.setVisible(self._temp_panic_vk != 0)
    
    def _load_current_settings(self) -> None:
        """Populate UI with current settings values."""
        # Load devices
        self._refresh_devices()
        
        # Select current devices
        idx = self._monitor_combo.findData(self._settings.monitor_device)
        if idx >= 0:
            self._monitor_combo.setCurrentIndex(idx)
        
        idx = self._broadcast_combo.findData(self._settings.broadcast_device)
        if idx >= 0:
            self._broadcast_combo.setCurrentIndex(idx)

            
        idx = self._mic_combo.findData(self._settings.microphone_device)
        if idx >= 0:
            self._mic_combo.setCurrentIndex(idx)
        
        # Overlap mode
        if self._settings.overlap_mode == "mix":
            self._mix_radio.setChecked(True)
        else:
            self._restart_radio.setChecked(True)
        
        # Stop Hotkey
        self._temp_panic_vk = self._settings.panic_hotkey_vk
        self._temp_panic_mod = self._settings.panic_hotkey_modifiers
        self._update_keybind_ui()
    
    def _refresh_devices(self) -> None:
        """Refresh device combo boxes non-destructively."""
        import sounddevice as sd
            
        self._engine._device_manager.refresh()
        devices = self._engine.get_available_output_devices()
        in_devices = self._engine.get_available_input_devices()
        
        # Check if Virtual Cable driver is already installed
        driver_found = False
        try:
            sd_devices = sd.query_devices()
            for dev in sd_devices:
                name = dev.get('name', '').lower()
                if 'cable' in name or 'vb-audio' in name or 'virtual' in name:
                    driver_found = True
                    break
        except Exception as e:
            logger.error(f"Error querying devices for driver check: {e}")
            
        if driver_found:
            self._install_btn.setEnabled(False)
            self._install_status.setText("Driver already installed")
            self._install_status.setStyleSheet("color: #3fb950; font-size: 12px; font-weight: bold;")
        else:
            self._install_btn.setEnabled(True)
            if self._install_status.text() == "Driver already installed":
                self._install_status.setText("")
        
        # Save current selections
        current_monitor = self._monitor_combo.currentData()
        current_broadcast = self._broadcast_combo.currentData()
        current_mic = self._mic_combo.currentData()
        
        self._monitor_combo.clear()
        self._broadcast_combo.clear()
        self._mic_combo.clear()
        
        # Add "None" option
        self._monitor_combo.addItem("Default System Device", None)
        self._broadcast_combo.addItem("None", None)
        self._mic_combo.addItem("None", None)
        
        for dev in devices:
            label = f"{dev['name']}"
            self._monitor_combo.addItem(label, dev['id'])
            self._broadcast_combo.addItem(label, dev['id'])
            
        for dev in in_devices:
            self._mic_combo.addItem(dev['name'], dev['id'])
        
        # Restore selections
        idx = self._monitor_combo.findData(current_monitor)
        if idx >= 0:
            self._monitor_combo.setCurrentIndex(idx)
        
        idx = self._broadcast_combo.findData(current_broadcast)
        if idx >= 0:
            self._broadcast_combo.setCurrentIndex(idx)

            
        idx = self._mic_combo.findData(current_mic)
        if idx >= 0:
            self._mic_combo.setCurrentIndex(idx)
    
    def _apply_settings(self) -> None:
        """Save settings and emit signal if devices/settings actually changed."""
        new_monitor = self._monitor_combo.currentData()
        new_broadcast = self._broadcast_combo.currentData()
        new_mic = self._mic_combo.currentData()
        new_overlap = "mix" if self._mix_radio.isChecked() else "restart"
        
        changed = False
        if (self._settings.monitor_device != new_monitor or
            self._settings.broadcast_device != new_broadcast or
            self._settings.microphone_device != new_mic or
            self._settings.overlap_mode != new_overlap or
            self._settings.panic_hotkey_vk != self._temp_panic_vk or
            self._settings.panic_hotkey_modifiers != self._temp_panic_mod):
            changed = True
            
        if changed:
            self._settings.monitor_device = new_monitor
            self._settings.broadcast_device = new_broadcast
            self._settings.microphone_device = new_mic
            self._settings.overlap_mode = new_overlap
            self._settings.panic_hotkey_vk = self._temp_panic_vk
            self._settings.panic_hotkey_modifiers = self._temp_panic_mod
            self._settings.save()
            self.settings_changed.emit()
            
        self.accept()
