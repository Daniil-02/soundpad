"""Audio device enumeration and hot-plug detection.

Monitors connected audio output devices and emits signals
when devices are added or removed.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import sounddevice as sd
from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

DEVICE_POLL_INTERVAL_MS = 2000  # Poll for device changes every 2 seconds


@dataclass
class DeviceInfo:
    """Information about an audio output device."""
    index: int                    # sounddevice device index
    name: str                     # Human-readable device name
    max_output_channels: int      # Maximum output channels
    default_samplerate: float     # Default sample rate (e.g., 48000.0)
    is_default: bool              # Whether this is the system default output
    host_api_name: str            # Host API name (e.g., 'Windows WASAPI')


class DeviceManager(QObject):
    """Manages audio output device enumeration and monitoring.
    
    Emits devices_changed signal when the available device list changes,
    allowing the UI and engine to react to hot-plug/unplug events.
    """
    
    devices_changed = Signal()  # Emitted when device list changes
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_devices)
        self._last_device_names: set[str] = set()
        self._cached_devices: List[DeviceInfo] = []
        
        # Initial enumeration
        self._refresh_devices()
    
    def start_monitoring(self) -> None:
        """Start polling for device changes."""
        if not self._poll_timer.isActive():
            self._poll_timer.start(DEVICE_POLL_INTERVAL_MS)
            logger.info("Device monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop polling for device changes."""
        self._poll_timer.stop()
        logger.info("Device monitoring stopped")
    
    def get_output_devices(self) -> List[DeviceInfo]:
        """Return the current list of output-capable audio devices."""
        return list(self._cached_devices)
    
    def get_device_index(self, device_name: str) -> Optional[int]:
        """Look up a device's sounddevice index by its name.
        
        Returns None if the device is not found (e.g., it was unplugged).
        """
        for dev in self._cached_devices:
            if dev.name == device_name:
                return dev.index
        return None
    
    def get_device_info(self, device_name: str) -> Optional[DeviceInfo]:
        """Get full DeviceInfo by device name."""
        for dev in self._cached_devices:
            if dev.name == device_name:
                return dev
        return None
    
    def get_default_output(self) -> Optional[DeviceInfo]:
        """Get the system default output device."""
        for dev in self._cached_devices:
            if dev.is_default:
                return dev
        # Fallback: return first device if any
        return self._cached_devices[0] if self._cached_devices else None
    
    def refresh(self) -> None:
        """Force a manual refresh of the device list."""
        self._refresh_devices()
    
    def _refresh_devices(self) -> None:
        """Query sounddevice for all output-capable devices."""
        try:
            devices = sd.query_devices()
            host_apis = sd.query_hostapis()
            default_output_idx = sd.default.device[1]  # (input_default, output_default)
            
            
            # API Ranking for deduplication
            API_RANK = {'Windows WASAPI': 4, 'Windows WDM-KS': 3, 'Windows DirectSound': 2, 'MME': 1}
            
            # Dictionary to deduplicate by name, keeping highest API rank
            unique_devices: dict[str, DeviceInfo] = {}
            
            for i, dev in enumerate(devices):
                max_out = dev.get('max_output_channels', 0)
                if max_out > 0:
                    api_idx = dev.get('hostapi', 0)
                    api_name = ""
                    if isinstance(host_apis, list) and api_idx < len(host_apis):
                        api_name = host_apis[api_idx].get('name', '')
                    elif isinstance(host_apis, dict):
                        api_name = host_apis.get('name', '')
                    
                    info = DeviceInfo(
                        index=i,
                        name=dev['name'],
                        max_output_channels=max_out,
                        default_samplerate=dev.get('default_samplerate', 48000.0),
                        is_default=(i == default_output_idx),
                        host_api_name=api_name
                    )
                    
                    # Deduplication logic
                    base_name = dev['name']
                    # Strip prefixes sometimes added by MME/DirectSound
                    clean_name = base_name.replace("Primary Sound Driver", "").strip()
                    if not clean_name:
                        clean_name = base_name
                        
                    current_rank = API_RANK.get(api_name, 0)
                    if clean_name in unique_devices:
                        existing_rank = API_RANK.get(unique_devices[clean_name].host_api_name, 0)
                        if current_rank > existing_rank:
                            unique_devices[clean_name] = info
                    else:
                        unique_devices[clean_name] = info
            
            output_devices = list(unique_devices.values())
            self._cached_devices = output_devices
            self._last_device_names = {d.name for d in output_devices}
            
            logger.debug(f"Found {len(output_devices)} unique output devices")
            
        except Exception as e:
            logger.error(f"Failed to enumerate audio devices: {e}")
    
    def _poll_devices(self) -> None:
        """Poll for device list changes and emit signal if changed."""
        try:
            devices = sd.query_devices()
            
            if isinstance(devices, dict):
                devices = [devices]
            
            current_names = set()
            for dev in devices:
                if dev.get('max_output_channels', 0) > 0:
                    current_names.add(dev['name'])
            
            if current_names != self._last_device_names:
                logger.info("Audio device list changed, refreshing...")
                self._refresh_devices()
                self.devices_changed.emit()
                
        except Exception as e:
            logger.error(f"Device poll error: {e}")
