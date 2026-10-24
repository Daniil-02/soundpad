"""Global hotkey system using the 'keyboard' library.

Captures keyboard hotkeys system-wide, even when full-screen
games have focus, by installing a low-level OS hook.
"""

import logging
import threading
from typing import Dict, Optional, Tuple

import keyboard
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

# Modifier flag constants matching sound_item.py
MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

def vk_to_keyboard_string(vk: int, modifiers: int) -> str:
    """Convert Windows VK code and modifiers to a keyboard module string."""
    from soundpulse.models.sound_item import VK_NAMES
    
    parts = []
    if modifiers & MOD_CTRL: parts.append("ctrl")
    if modifiers & MOD_ALT: parts.append("alt")
    if modifiers & MOD_SHIFT: parts.append("shift")
    if modifiers & MOD_WIN: parts.append("windows")
        
    key_name = VK_NAMES.get(vk, "").lower()
    if not key_name:
        raise ValueError(f"Unknown VK code: 0x{vk:02X}")
        
    # Translate some names for the keyboard module
    if key_name.startswith("num") and len(key_name) == 4:
        key_name = key_name.replace("num", "numpad ")
    elif key_name == "pageup":
        key_name = "page up"
    elif key_name == "pagedown":
        key_name = "page down"
        
    parts.append(key_name)
    return "+".join(parts)


class GlobalHotkeyManager(QObject):
    """Manages system-wide hotkey registration and dispatch using 'keyboard'.
    
    Signals:
        hotkey_triggered(int): Emitted with the hotkey ID when pressed.
    """
    
    hotkey_triggered = Signal(int)
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._registered: Dict[int, Tuple[int, int]] = {}  # id -> (mod, vk)
        self._handlers: Dict[int, object] = {} # id -> hook handle
        self._next_id: int = 1
        self._lock = threading.Lock()
        self._running = False
    
    def register(self, vk_code: int, modifiers: int = 0) -> int:
        """Register a hotkey combination.
        
        Args:
            vk_code: Windows virtual key code.
            modifiers: Bitmask of MOD_ALT/MOD_CTRL/MOD_SHIFT/MOD_WIN.
        
        Returns:
            Unique hotkey ID for later reference.
        """
        if self.is_registered(vk_code, modifiers):
            raise ValueError(f"Hotkey already registered: mod=0x{modifiers:X} vk=0x{vk_code:X}")
            
        with self._lock:
            hk_id = self._next_id
            self._next_id += 1
            self._registered[hk_id] = (modifiers, vk_code)
            
            # If the engine is currently active, bind it immediately
            if self._running:
                self._bind_hotkey(hk_id, modifiers, vk_code)
                
        return hk_id
        
    def _bind_hotkey(self, hk_id: int, modifiers: int, vk_code: int) -> None:
        """Internal method to bind to the keyboard module hook."""
        try:
            hotkey_str = vk_to_keyboard_string(vk_code, modifiers)
            
            # Create a localized closure to emit the signal
            def callback():
                self.hotkey_triggered.emit(hk_id)
                
            handler = keyboard.add_hotkey(hotkey_str, callback, suppress=False)
            self._handlers[hk_id] = handler
            logger.info(f"Registered global hotkey: {hotkey_str} (ID: {hk_id})")
        except Exception as e:
            logger.error(
                f"Failed to bind hotkey {hk_id} (mod=0x{modifiers:X} vk=0x{vk_code:X}). "
                f"If you are playing a game with elevated privileges, try running SoundPulse as Administrator! Error: {e}"
            )
    
    def unregister(self, hotkey_id: int) -> None:
        """Unregister a hotkey by its ID."""
        with self._lock:
            self._registered.pop(hotkey_id, None)
            handler = self._handlers.pop(hotkey_id, None)
            if handler:
                try:
                    keyboard.remove_hotkey(handler)
                except Exception as e:
                    logger.warning(f"Error removing hotkey hook: {e}")
    
    def unregister_all(self) -> None:
        """Unregister all hotkeys."""
        with self._lock:
            self._registered.clear()
            for handler in self._handlers.values():
                try:
                    keyboard.remove_hotkey(handler)
                except Exception:
                    pass
            self._handlers.clear()
    
    def is_registered(self, vk_code: int, modifiers: int = 0) -> bool:
        for mod, vk in self._registered.values():
            if mod == modifiers and vk == vk_code:
                return True
        return False
    
    def get_hotkey_id(self, vk_code: int, modifiers: int = 0) -> Optional[int]:
        for hk_id, (mod, vk) in self._registered.items():
            if mod == modifiers and vk == vk_code:
                return hk_id
        return None
    
    def start(self) -> None:
        """Start binding all registered hotkeys to the global hook."""
        if self._running:
            return
            
        self._running = True
        with self._lock:
            for hk_id, (mod, vk) in self._registered.items():
                if hk_id not in self._handlers:
                    self._bind_hotkey(hk_id, mod, vk)
        
        logger.info(f"Global hotkey listener started using 'keyboard' module.")
    
    def stop(self) -> None:
        """Stop and unbind all hotkeys."""
        if not self._running:
            return
            
        self._running = False
        with self._lock:
            for handler in self._handlers.values():
                try:
                    keyboard.remove_hotkey(handler)
                except Exception:
                    pass
            self._handlers.clear()
            
        logger.info("Global hotkey listener stopped")
    
    def restart(self) -> None:
        """Restart the listener (e.g., after hotkey changes)."""
        self.stop()
        self.start()
    
    @property
    def is_running(self) -> bool:
        """Whether the listener is active."""
        return self._running
    
    @property
    def registered_count(self) -> int:
        """Number of registered hotkeys."""
        return len(self._registered)
