"""Main application window.

Assembles all UI components, connects them to the audio engine,
hotkey manager, and settings, providing the full SoundPulse experience.
"""

import logging
import os
import shutil
import uuid
import re
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QMimeData, QTimer, QFileSystemWatcher
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar,
    QMenuBar, QMenu, QMessageBox, QApplication
)

from soundpulse.ui.components import SmoothButton
from soundpulse.ui.playback_bar import PlaybackBar

from soundpulse.audio.decoder import AudioDecoder
from soundpulse.audio.device_manager import DeviceManager
from soundpulse.audio.engine import DualStreamEngine
from soundpulse.audio.resampler import Resampler
from soundpulse.config.settings import Settings
from soundpulse.hotkeys.global_hotkey import GlobalHotkeyManager
from soundpulse.models.sound_item import SoundItem
from soundpulse.ui.hotkey_editor import HotkeyEditorDialog
from soundpulse.ui.search_bar import SearchBar
from soundpulse.ui.settings_dialog import SettingsDialog
from soundpulse.ui.sound_list import SoundListWidget
from soundpulse.ui.volume_controls import VolumeControls
from soundpulse.ui.waveform_widget import TrimDialog

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a'}

def get_sounds_dir() -> Path:
    """Return the absolute path to the sounds directory.
    When running as a frozen executable, this points next to the .exe.
    Otherwise, it points to the root of the source tree.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "sounds"
    return Path(__file__).parent.parent.parent.resolve() / "sounds"


class MainWindow(QMainWindow):
    """SoundPulse main application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SoundPulse")
        self.setMinimumSize(800, 550)
        self.setAcceptDrops(True)
        
        # ── Core Components ────────────────────────────────
        self._settings = Settings.instance()
        self._settings.load()
        
        self._decoder = AudioDecoder()
        self._resampler = Resampler()
        self._device_manager = DeviceManager()
        self._engine = DualStreamEngine(
            self._decoder, self._resampler, self._device_manager
        )
        self._hotkey_manager = GlobalHotkeyManager()
        
        # Hotkey ID -> sound_id mapping
        self._hotkey_sound_map: dict[int, str] = {}
        # Panic hotkey ID
        self._panic_hotkey_id: Optional[int] = None
        
        # ── UI Setup ──────────────────────────────────────
        self._active_playbacks: int = 0
        self._active_focus_sound_id: str | None = None
        
        self._setup_ui()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._connect_signals()
        
        # Start progress polling timer
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._on_progress_tick)
        self._progress_timer.start(50)
        
        # ── Apply Settings ────────────────────────────────
        # Audio setup
        self._apply_settings_to_engine()
        self._sync_sounds_folder()
        self._load_sounds()
        self._register_all_hotkeys()
        
        # File System Watcher
        self._watcher = QFileSystemWatcher(self)
        sounds_dir = get_sounds_dir()
        if sounds_dir.exists():
            self._watcher.addPath(str(sounds_dir))
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        
        # ── Start Services ────────────────────────────────
        self._device_manager.start_monitoring()
        self._hotkey_manager.start()
        
        # ── Restore Window Geometry ───────────────────────
        if self._settings.window_geometry:
            geo = self._settings.window_geometry
            self.setGeometry(
                geo.get("x", 100), geo.get("y", 100),
                geo.get("width", 800), geo.get("height", 550)
            )
        
        logger.info("MainWindow initialized")
    
    def _setup_ui(self) -> None:
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)
        
        # ── Top Toolbar ───────────────────────────────────
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(10)
        
        self._search_bar = SearchBar()
        toolbar_layout.addWidget(self._search_bar, 1)
        
        add_btn = SmoothButton("📂 Open Sounds Folder")
        add_btn.set_colors("#0055CC", "#0066EE", "#0044AA", text_hex="#ffffff")
        add_btn.clicked.connect(self._on_open_sounds_folder)
        toolbar_layout.addWidget(add_btn)
        
        stop_btn = SmoothButton("\u25A0 Stop All")
        stop_btn.set_colors("#f43f5e", "#e11d48", "#be123c", text_hex="#ffffff")
        stop_btn.clicked.connect(self._on_stop_all)
        toolbar_layout.addWidget(stop_btn)
        
        main_layout.addLayout(toolbar_layout)
        
        # ── Sound List ────────────────────────────────────
        self._sound_list = SoundListWidget()
        main_layout.addWidget(self._sound_list, 1)
        
        # ── Playback Control Bar ──────────────────────────
        self._playback_bar = PlaybackBar()
        main_layout.addWidget(self._playback_bar)
        
        # ── Volume Controls ───────────────────────────────
        self._volume_controls = VolumeControls()
        self._volume_controls.set_monitor_volume(self._settings.monitor_volume)
        self._volume_controls.set_broadcast_volume(self._settings.broadcast_volume)
        main_layout.addWidget(self._volume_controls)
    
    def _setup_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        
        # File menu
        file_menu = menu_bar.addMenu("File")
        
        add_action = QAction("Open Sounds Folder", self)
        add_action.setShortcut("Ctrl+O")
        add_action.triggered.connect(self._on_open_sounds_folder)
        file_menu.addAction(add_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Settings menu
        settings_action = QAction("Settings", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._on_open_settings)
        menu_bar.addAction(settings_action)
    
    def _setup_status_bar(self) -> None:
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet(
            "QStatusBar { background-color: #F0F0F0; color: #000000; "
            "border-top: 1px solid #CCCCCC; font-size: 12px; "
            "font-family: 'Segoe UI'; padding: 4px 12px; }"
        )
        self.setStatusBar(self._status_bar)
        
        self._status_label = QLabel("")
        self._status_bar.addWidget(self._status_label)
        
        self._active_playbacks = 0
        self._last_status = "Ready"
        
        self._refresh_status_bar()
    
    def _connect_signals(self) -> None:
        """Wire all signals to slots."""
        # Search
        self._search_bar.text_changed.connect(self._sound_list.filter_sounds)
        
        # Volume
        self._volume_controls.monitor_volume_changed.connect(self._on_monitor_volume)
        self._volume_controls.broadcast_volume_changed.connect(self._on_broadcast_volume)
        
        # Sound list
        self._sound_list.sound_play_requested.connect(self._on_play_sound)
        self._sound_list.sound_selected.connect(self._on_sound_selected)
        self._sound_list.sound_rename_requested.connect(self._on_rename_sound)
        self._sound_list.sound_delete_requested.connect(self._on_delete_sound)
        self._sound_list.sound_hotkey_requested.connect(self._on_set_hotkey)
        self._sound_list.sound_trim_requested.connect(self._on_trim_sound)
        self._sound_list.sound_volume_changed.connect(self._on_sound_volume_changed)
        self._sound_list.files_dropped.connect(self._on_files_dropped)
        
        # Engine
        from PySide6.QtCore import Qt
        self._engine.playback_started.connect(self._on_playback_started, Qt.QueuedConnection)
        self._engine.playback_finished.connect(self._on_playback_finished, Qt.QueuedConnection)
        self._engine.error_occurred.connect(self._on_engine_error, Qt.QueuedConnection)
        self._engine.warning_occurred.connect(self._on_engine_warning, Qt.QueuedConnection)
        self._engine.engine_ready.connect(self._on_engine_ready, Qt.QueuedConnection)
        
        # Hotkeys
        self._hotkey_manager.hotkey_triggered.connect(self._on_hotkey_triggered)
        
        # Device changes
        self._device_manager.devices_changed.connect(self._on_devices_changed)
        
        # Playback Controls
        self._playback_bar.pause_requested.connect(self._on_pause_requested)
        self._playback_bar.stop_requested.connect(self._on_stop_requested)
        self._playback_bar.seek_requested.connect(self._on_seek_requested)
    
    # ── Settings ──────────────────────────────────────────────
    
    def _apply_settings_to_engine(self) -> None:
        self._status_label.setText("Initializing audio streams...")
        self._sound_list.setEnabled(False)
        self._playback_bar.setEnabled(False)
        
        self._engine.set_output_devices(
            self._settings.monitor_device, 
            self._settings.broadcast_device,
            self._settings.microphone_device
        )
        self._engine.set_monitor_volume(self._settings.monitor_volume)
        self._engine.set_broadcast_volume(self._settings.broadcast_volume)
        self._engine.set_overlap_mode(self._settings.overlap_mode)
        self._engine.apply_device_config()

    def _on_engine_ready(self, success: bool) -> None:
        if success:
            self._status_label.setText("Audio streams ready")
        else:
            self._status_label.setText("Failed to initialize audio streams")
            
        self._sound_list.setEnabled(True)
        self._playback_bar.setEnabled(True)
        self._refresh_status_bar()
    
    def _load_sounds(self) -> None:
        self._sound_list.set_sounds(self._settings.sounds)
        self._engine.precache_sounds(self._settings.sounds)
        
    def _on_directory_changed(self, path: str) -> None:
        """Handle real-time updates when the sounds directory is modified externally."""
        logger.info(f"Directory changed: {path}. Resyncing sounds...")
        self._sync_sounds_folder()
        self._load_sounds()
        
    def _sync_sounds_folder(self) -> None:
        """Strictly mirror the sounds/ directory by rebuilding the sound list from scratch."""
        sounds_dir = get_sounds_dir()
        if not sounds_dir.exists():
            if self._settings.sounds:
                self._settings.sounds = []
                self._settings.save()
            return
            
        # Create a lookup mapping absolute paths to existing SoundItems
        existing_sounds = {}
        for s in self._settings.sounds:
            try:
                p = Path(s.file_path).resolve()
                existing_sounds[str(p)] = s
            except Exception:
                pass
                
        new_sounds = []
        changed = False
        
        for file_path in sounds_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                abs_path = str(file_path.resolve())
                if abs_path in existing_sounds:
                    # Keep existing sound to preserve hotkeys, volume, and ID
                    new_sounds.append(existing_sounds[abs_path])
                else:
                    # Add new sound
                    logger.info(f"Auto-registering new file: {file_path.name}")
                    title = file_path.stem.replace("_", " ").title()
                    info = self._decoder.get_file_info(abs_path)
                    duration = info["duration"] if info else 0.0
                    
                    new_sound = SoundItem(
                        title=title,
                        file_path=abs_path,
                        duration=duration
                    )
                    new_sounds.append(new_sound)
                    changed = True
                    
        # Check if any existing sounds were deleted
        if len(new_sounds) != len(self._settings.sounds):
            changed = True
            
        self._settings.sounds = new_sounds
        
        if changed:
            self._settings.save()
    
    # ── Hotkey Management ─────────────────────────────────────
    
    def _register_all_hotkeys(self) -> None:
        """Register all sound hotkeys and the panic hotkey."""
        self._hotkey_manager.unregister_all()
        self._hotkey_sound_map.clear()
        self._panic_hotkey_id = None
        
        # Register panic hotkey
        if self._settings.panic_hotkey_vk:
            try:
                self._panic_hotkey_id = self._hotkey_manager.register(
                    self._settings.panic_hotkey_vk,
                    self._settings.panic_hotkey_modifiers
                )
            except ValueError:
                logger.warning("Could not register panic hotkey")
        
        # Register sound hotkeys
        for sound in self._settings.sounds:
            if sound.has_hotkey():
                try:
                    hk_id = self._hotkey_manager.register(
                        sound.hotkey_vk, sound.hotkey_modifiers
                    )
                    self._hotkey_sound_map[hk_id] = sound.id
                except ValueError as e:
                    logger.warning(f"Could not register hotkey for '{sound.title}': {e}")
    
    def _on_hotkey_triggered(self, hotkey_id: int) -> None:
        """Handle a global hotkey press."""
        # Check panic hotkey
        if hotkey_id == self._panic_hotkey_id:
            self._on_stop_all()
            return
        
        # Look up sound
        sound_id = self._hotkey_sound_map.get(hotkey_id)
        if sound_id:
            sound = self._settings.get_sound_by_id(sound_id)
            if sound:
                # If the sound is active (playing or paused), toggle its pause state
                if self._engine.get_playback_progress(sound_id) is not None:
                    self._engine.toggle_pause(sound_id)
                else:
                    # Sound is stopped, start playback
                    self._on_play_sound(sound)
    
    # ── Sound Actions ─────────────────────────────────────────
    
    def _on_open_sounds_folder(self) -> None:
        """Open the sounds directory in the native file explorer."""
        sounds_dir = get_sounds_dir()
        sounds_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(sounds_dir))
            
    def _on_files_dropped(self, files: list[str]) -> None:
        for file_path in files:
            if Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS:
                self._import_sound(file_path)
    
    def _import_sound(self, file_path: str) -> None:
        """Import a single audio file into the library, copy to sounds dir."""
        path = Path(file_path)
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
            
        sounds_dir = get_sounds_dir()
        sounds_dir.mkdir(parents=True, exist_ok=True)
        
        # Strip strictly Russian characters (preserve Ukrainian), replace spaces
        safe_name = re.sub(r'[ъыэёЪЫЭЁ]', '', path.stem)
        safe_name = safe_name.replace(" ", "_")
        
        # Append short UUID to prevent collisions
        short_id = uuid.uuid4().hex[:8]
        new_filename = f"{safe_name}_{short_id}{path.suffix.lower()}"
        new_filepath = sounds_dir / new_filename
        
        try:
            shutil.copy2(path, new_filepath)
        except Exception as e:
            logger.error(f"Failed to copy file to sounds directory: {e}")
            return
        
        # Get file info for duration
        info = self._decoder.get_file_info(str(new_filepath))
        duration = info["duration"] if info else 0.0
        
        sound = SoundItem(
            title=path.stem,
            file_path=str(new_filepath),
            duration=duration
        )
        
        self._settings.add_sound(sound)
        self._settings.save()
        self._sound_list.add_sound(sound)
        self._engine.precache_sounds([sound])
        self._status_label.setText(f"Added: {sound.title}")
    
    def _on_sound_selected(self, sound) -> None:
        """Enable playback controls when a sound is selected."""
        self._playback_bar.setEnabled(True)
        
    def _on_play_sound(self, sound) -> None:
        """Play a sound through the dual-stream engine."""
        if isinstance(sound, SoundItem):
            self._engine.play(sound)
    
    def _on_stop_all(self) -> None:
        """Stop all currently playing sounds."""
        self._engine.stop_all()
        self._sound_list.highlight_playing(None)
        self._status_label.setText("All sounds stopped")
    
    def _on_rename_sound(self, sound) -> None:
        if not isinstance(sound, SoundItem):
            return
            
        from PySide6.QtWidgets import QInputDialog
        new_title, ok = QInputDialog.getText(
            self, "Rename Sound", "Title:",
            text=sound.title
        )
        
        if ok and new_title and new_title.strip() and new_title != sound.title:
            sound.title = new_title.strip()
            self._settings.update_sound(sound)
            self._sound_list.update_sound(sound)
            self._status_label.setText(f"Renamed to: {sound.title}")
    
    def _on_delete_sound(self, sound_id: str) -> None:
        reply = QMessageBox.question(
            self, "Delete Sound",
            "Are you sure you want to remove this sound?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._settings.remove_sound(sound_id)
            self._sound_list.remove_sound(sound_id)
            self._register_all_hotkeys()
            self._hotkey_manager.restart()
            self._status_label.setText("Sound removed")
    
    def _on_set_hotkey(self, sound) -> None:
        if not isinstance(sound, SoundItem):
            return
            
        dialog = HotkeyEditorDialog(self, sound.hotkey_vk, sound.hotkey_modifiers)
        if dialog.exec() == HotkeyEditorDialog.Accepted:
            vk, mod = dialog.get_hotkey()
            
            # Check for conflict
            if vk != 0:
                conflict = next((s for s in self._settings.sounds if s.hotkey_vk == vk and s.hotkey_modifiers == mod and s.id != sound.id), None)
                if conflict:
                    QMessageBox.warning(
                        self, 
                        "Hotkey Conflict", 
                        f"This hotkey is already assigned to:\n'{conflict.title}'\n\nPlease choose a unique hotkey."
                    )
                    return
            
            sound.hotkey_vk = vk
            sound.hotkey_modifiers = mod
            self._settings.update_sound(sound)
            self._sound_list.update_sound(sound)
            self._register_all_hotkeys()
            self._hotkey_manager.restart()
            self._status_label.setText(f"Hotkey set for: {sound.title}")
    
    def _on_trim_sound(self, sound) -> None:
        if not isinstance(sound, SoundItem):
            return
        peaks = self._decoder.get_waveform_data(sound.file_path)
        if peaks is None:
            QMessageBox.warning(self, "Error", "Could not load audio for trimming.")
            return
        dialog = TrimDialog(
            peaks, sound.duration,
            trim_start=sound.trim_start,
            trim_end=sound.trim_end,
            parent=self
        )
        if dialog.exec() == TrimDialog.Accepted:
            start, end = dialog.get_trim_seconds()
            sound.trim_start = start
            sound.trim_end = end
            self._settings.update_sound(sound)
            self._sound_list.update_sound(sound)
            self._engine.precache_sounds([sound])
            self._status_label.setText(f"Trimmed: {sound.title}")
            
    def _on_sound_volume_changed(self, sound: SoundItem) -> None:
        """Handle saving and re-caching when a sound's volume is changed."""
        self._settings.update_sound(sound)
        self._engine.precache_sounds([sound])
        self._status_label.setText(f"Volume saved: {sound.title}")
    
    # ── Volume ────────────────────────────────────────────────
    
    def _on_monitor_volume(self, volume: float) -> None:
        self._engine.set_monitor_volume(volume)
        self._settings.monitor_volume = volume
        self._settings.save()
    
    def _on_broadcast_volume(self, volume: float) -> None:
        self._engine.set_broadcast_volume(volume)
        self._settings.broadcast_volume = volume
        self._settings.save()
    
    # ── Engine Callbacks ──────────────────────────────────────
    
    def _on_playback_started(self, sound_id: str) -> None:
        self._sound_list.highlight_playing(sound_id)
        self._active_playbacks += 1
        self._active_focus_sound_id = sound_id
        self._last_status = "Success"
        self._refresh_status_bar()
    
    def _on_playback_finished(self, sound_id: str) -> None:
        self._sound_list.highlight_playing(None)
        if self._active_playbacks > 0:
            self._active_playbacks -= 1
        if self._active_focus_sound_id == sound_id:
            self._active_focus_sound_id = None
            self._playback_bar.set_active(False)
        self._refresh_status_bar()
    
    def _on_engine_error(self, sound_id: str, message: str) -> None:
        self._last_status = f"Error"
        self._refresh_status_bar()
        logger.error(f"Engine error for {sound_id}: {message}")
        
    def _on_engine_warning(self, message: str) -> None:
        self._last_status = f"Warning: {message}"
        self._refresh_status_bar()
        logger.warning(f"Engine warning: {message}")
        
    def _on_progress_tick(self) -> None:
        if self._active_focus_sound_id:
            progress = self._engine.get_playback_progress(self._active_focus_sound_id)
            if progress is not None:
                current_sec, total_sec, is_paused = progress
                self._playback_bar.update_progress(current_sec, total_sec, is_paused)
            else:
                self._playback_bar.set_active(False)
        else:
            self._playback_bar.set_active(False)
            
    def _on_pause_requested(self) -> None:
        if self._active_focus_sound_id:
            self._engine.toggle_pause(self._active_focus_sound_id)
        else:
            # Nothing playing, but button clicked: load and play selected
            sound = self._sound_list.get_selected_sound()
            if sound:
                self._on_play_sound(sound)
            
    def _on_stop_requested(self) -> None:
        if self._active_focus_sound_id:
            self._engine.stop(self._active_focus_sound_id)
            
    def _on_seek_requested(self, pos_sec: float) -> None:
        if self._active_focus_sound_id:
            self._engine.seek(self._active_focus_sound_id, pos_sec)
    
    # ── Settings Dialog ───────────────────────────────────────
    
    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self._engine, self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()
    
    def _on_settings_changed(self) -> None:
        self._apply_settings_to_engine()
        self._register_all_hotkeys()
        self._update_device_status()
        self._status_label.setText("Settings applied")
    
    # ── Device Status ─────────────────────────────────────────
    
    def _on_devices_changed(self) -> None:
        self._last_status = "Audio devices changed"
        self._refresh_status_bar()
    
    def _refresh_status_bar(self) -> None:
        def get_name(dev_id):
            if dev_id is None:
                return "Not set"
            for d in self._engine.get_available_output_devices():
                if d["id"] == dev_id:
                    return d["name"]
            return f"ID {dev_id}"
            
        mon = get_name(self._settings.monitor_device)
        bcast = get_name(self._settings.broadcast_device)
        mic = get_name(self._settings.microphone_device)
        
        if len(mon) > 15:
            mon = mon[:12] + "..."
        if len(bcast) > 15:
            bcast = bcast[:12] + "..."
        if len(mic) > 15:
            mic = mic[:12] + "..."
            
        status_text = f"{self._active_playbacks} playbacks | Mic: {mic} | Mon: {mon} | Bcast: {bcast} | {self._last_status}"
        self._status_label.setText(status_text)
        
    def _update_device_status(self) -> None:
        self._refresh_status_bar()
    
    # ── Drag & Drop ───────────────────────────────────────────
    
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # Check if any URL is a supported audio file
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()
    
    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
                self._import_sound_file(path)
        event.acceptProposedAction()
    
    # ── Window Events ─────────────────────────────────────────
    
    def closeEvent(self, event) -> None:
        """Save state and clean up on close."""
        # Save window geometry
        geo = self.geometry()
        self._settings.window_geometry = {
            "x": geo.x(), "y": geo.y(),
            "width": geo.width(), "height": geo.height()
        }
        self._settings.save()
        
        # Shut down services
        self._hotkey_manager.stop()
        self._device_manager.stop_monitoring()
        self._engine.shutdown()
        
        # Ensure thread pool finishes tasks to prevent PyInstaller orphan processes
        QThreadPool.globalInstance().waitForDone(1000)
        
        logger.info("Application closing")
        super().closeEvent(event)
