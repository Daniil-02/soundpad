"""
Model defining a single sound item in the library.
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional

# Windows Virtual Key code constants for hotkey display
VK_NAMES = {
    0x70: 'F1', 0x71: 'F2', 0x72: 'F3', 0x73: 'F4', 0x74: 'F5',
    0x75: 'F6', 0x76: 'F7', 0x77: 'F8', 0x78: 'F9', 0x79: 'F10',
    0x7A: 'F11', 0x7B: 'F12',
    0x60: 'Num0', 0x61: 'Num1', 0x62: 'Num2', 0x63: 'Num3',
    0x64: 'Num4', 0x65: 'Num5', 0x66: 'Num6', 0x67: 'Num7',
    0x68: 'Num8', 0x69: 'Num9',
    0x30: '0', 0x31: '1', 0x32: '2', 0x33: '3', 0x34: '4',
    0x35: '5', 0x36: '6', 0x37: '7', 0x38: '8', 0x39: '9',
    0x41: 'A', 0x42: 'B', 0x43: 'C', 0x44: 'D', 0x45: 'E',
    0x46: 'F', 0x47: 'G', 0x48: 'H', 0x49: 'I', 0x4A: 'J',
    0x4B: 'K', 0x4C: 'L', 0x4D: 'M', 0x4E: 'N', 0x4F: 'O',
    0x50: 'P', 0x51: 'Q', 0x52: 'R', 0x53: 'S', 0x54: 'T',
    0x55: 'U', 0x56: 'V', 0x57: 'W', 0x58: 'X', 0x59: 'Y', 0x5A: 'Z',
    0x20: 'Space', 0x0D: 'Enter', 0x09: 'Tab', 0x1B: 'Esc',
    0x2D: 'Insert', 0x2E: 'Delete', 0x24: 'Home', 0x23: 'End',
    0x21: 'PageUp', 0x22: 'PageDown',
    0x26: 'Up', 0x28: 'Down', 0x25: 'Left', 0x27: 'Right',
}

# Modifier flag constants (Windows MOD_ values)
MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


@dataclass
class SoundItem:
    """Represents a single sound entry in the SoundPulse library."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    file_path: str = ""
    hotkey_vk: int = 0          # Virtual key code (0 = no hotkey)
    hotkey_modifiers: int = 0   # Bitmask of MOD_ALT/CTRL/SHIFT/WIN
    volume: float = 1.0         # Per-sound playback volume multiplier (0.0 to 1.0)
    trim_start: float = 0.0     # Trim start in seconds
    trim_end: float = 0.0       # Trim end in seconds (0 = end of file)
    category: str = ""          # User-defined tag/category
    duration: float = 0.0       # Total file duration in seconds (computed)
    
    def hotkey_display(self) -> str:
        """Return human-readable hotkey string like 'Ctrl+Shift+F1' or '' if unbound."""
        if self.hotkey_vk == 0:
            return ""
        parts = []
        if self.hotkey_modifiers & MOD_CTRL:
            parts.append("Ctrl")
        if self.hotkey_modifiers & MOD_ALT:
            parts.append("Alt")
        if self.hotkey_modifiers & MOD_SHIFT:
            parts.append("Shift")
        if self.hotkey_modifiers & MOD_WIN:
            parts.append("Win")
        key_name = VK_NAMES.get(self.hotkey_vk, f"0x{self.hotkey_vk:02X}")
        parts.append(key_name)
        return "+".join(parts)
    
    def has_hotkey(self) -> bool:
        return self.hotkey_vk != 0
    
    def effective_trim_end(self) -> float:
        """Returns trim_end if set, otherwise duration."""
        return self.trim_end if self.trim_end > 0 else self.duration
    
    def trimmed_duration(self) -> float:
        """Duration after trim points applied."""
        return self.effective_trim_end() - self.trim_start
    
    def format_duration(self) -> str:
        """Format duration as MM:SS."""
        d = self.trimmed_duration()
        mins = int(d) // 60
        secs = int(d) % 60
        return f"{mins}:{secs:02d}"
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "id": self.id,
            "title": self.title,
            "file_path": self.file_path,
            "hotkey_vk": self.hotkey_vk,
            "hotkey_modifiers": self.hotkey_modifiers,
            "volume": self.volume,
            "trim_start": self.trim_start,
            "trim_end": self.trim_end,
            "category": self.category,
            "duration": self.duration,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SoundItem':
        """Deserialize from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            title=data.get("title", ""),
            file_path=data.get("file_path", ""),
            hotkey_vk=data.get("hotkey_vk", 0),
            hotkey_modifiers=data.get("hotkey_modifiers", 0),
            volume=data.get("volume", 1.0),
            trim_start=data.get("trim_start", 0.0),
            trim_end=data.get("trim_end", 0.0),
            category=data.get("category", ""),
            duration=data.get("duration", 0.0),
        )
