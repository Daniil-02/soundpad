"""
Settings manager for SoundPulse.
Handles persistence of application configuration and library items.
"""

import json
import os
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any

from soundpulse.models.sound_item import SoundItem

class Settings:
    """Singleton configuration manager that persists all app state to JSON."""
    
    _instance: Optional['Settings'] = None
    _lock: threading.Lock = threading.Lock()
    
    def __init__(self):
        """Initialize settings. Use Settings.instance() instead of direct instantiation."""
        self.sounds: List[SoundItem] = []
        self.microphone_device: Optional[int] = None
        self.monitor_device: Optional[int] = None
        self.broadcast_device: Optional[int] = None
        self.monitor_volume: float = 0.8
        self.broadcast_volume: float = 1.0
        self.panic_hotkey_vk: int = 0x1B
        self.panic_hotkey_modifiers: int = 0
        self.overlap_mode: str = "restart"
        self.categories: List[str] = []
        self.window_geometry: Optional[Dict[str, int]] = None
        
        # Determine config file path
        app_data = os.environ.get('APPDATA')
        if not app_data:
            # Fallback if APPDATA is not set (e.g. testing environments)
            app_data = os.path.expanduser('~')
            
        self.config_dir = Path(app_data) / "SoundPulse"
        self.config_path = self.config_dir / "config.json"
        self._file_lock = threading.Lock()

    @classmethod
    def instance(cls) -> 'Settings':
        """Singleton accessor for Settings."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
        
    def load(self) -> None:
        """Read configuration from disk and populate fields."""
        if not self.config_path.exists():
            # If no config exists, just save the defaults and return
            self.save()
            return
            
        with self._file_lock:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self.microphone_device = data.get('microphone_device', None)
                self.monitor_device = data.get('monitor_device', None)
                self.broadcast_device = data.get('broadcast_device', None)
                self.monitor_volume = float(data.get('monitor_volume', 0.8))
                self.broadcast_volume = float(data.get('broadcast_volume', 1.0))
                self.panic_hotkey_vk = data.get('panic_hotkey_vk', 0x1B)
                self.panic_hotkey_modifiers = data.get('panic_hotkey_modifiers', 0)
                self.overlap_mode = data.get('overlap_mode', "restart")
                self.categories = data.get('categories', [])
                self.window_geometry = data.get('window_geometry', None)
                
                # Load sounds
                sounds_data = data.get('sounds', [])
                self.sounds = [SoundItem.from_dict(s) for s in sounds_data]
                
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error loading settings from {self.config_path}: {e}")
                # Fallback to defaults if there's a problem
                
    def save(self) -> None:
        """Write current configuration to disk safely."""
        with self._file_lock:
            # Ensure directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            data: Dict[str, Any] = {
                "microphone_device": self.microphone_device,
                "monitor_device": self.monitor_device,
                "broadcast_device": self.broadcast_device,
                "monitor_volume": self.monitor_volume,
                "broadcast_volume": self.broadcast_volume,
                "panic_hotkey_vk": self.panic_hotkey_vk,
                "panic_hotkey_modifiers": self.panic_hotkey_modifiers,
                "overlap_mode": self.overlap_mode,
                "categories": self.categories,
                "window_geometry": self.window_geometry,
                "sounds": [s.to_dict() for s in self.sounds]
            }
            
            # Write to a temporary file first for safe saving
            temp_path = self.config_path.with_suffix('.tmp')
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                    
                # Atomic replace
                temp_path.replace(self.config_path)
            except OSError as e:
                print(f"Error saving settings to {self.config_path}: {e}")
                
    def add_sound(self, sound: SoundItem) -> None:
        """Add a new sound item and save."""
        self.sounds.append(sound)
        self.save()
        
    def remove_sound(self, sound_id: str) -> None:
        """Remove a sound item by ID and delete its file if possible."""
        for sound in self.sounds:
            if sound.id == sound_id:
                try:
                    p = Path(sound.file_path)
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    print(f"Failed to delete audio file: {e}")
                    
        self.sounds = [s for s in self.sounds if s.id != sound_id]
        self.save()
        
    def update_sound(self, sound: SoundItem) -> None:
        """Update an existing sound item in-place and save."""
        for i, s in enumerate(self.sounds):
            if s.id == sound.id:
                self.sounds[i] = sound
                self.save()
                return
                
    def get_sound_by_id(self, sound_id: str) -> Optional[SoundItem]:
        """Find and return a sound item by its ID."""
        for sound in self.sounds:
            if sound.id == sound_id:
                return sound
        return None
        
    def get_sound_by_hotkey(self, vk: int, modifiers: int) -> Optional[SoundItem]:
        """Find and return a sound item by its registered hotkey."""
        for sound in self.sounds:
            if sound.hotkey_vk == vk and sound.hotkey_modifiers == modifiers:
                return sound
        return None
        
    def get_categories(self) -> List[str]:
        """Get list of unique categories from stored categories and current sounds."""
        unique_categories = set(self.categories)
        for sound in self.sounds:
            if sound.category:
                unique_categories.add(sound.category)
        return sorted(list(unique_categories))
