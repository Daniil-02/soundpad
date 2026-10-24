"""Dual-stream audio playback engine.

Simultaneously plays audio to two output devices:
- Monitor device (user's headphones/speakers for self-monitoring)
- Broadcast device (virtual audio cable for Discord/game voice chat)

Strict Singleton Mode: Maintains exactly one constant-open OutputStream per device.
"""

import logging
import threading
import queue
import subprocess
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal, QThreadPool, QRunnable, QTimer

from soundpulse.audio.decoder import AudioDecoder, DecodedAudio, PrecacheWorker
from soundpulse.audio.device_manager import DeviceManager
from soundpulse.audio.resampler import Resampler
from soundpulse.models.sound_item import SoundItem

logger = logging.getLogger(__name__)


@dataclass
class PlaybackState:
    """Tracks the state of an active playback."""
    sound_id: str
    audio_data: np.ndarray       # The resampled, trimmed, gain-adjusted float32 PCM
    monitor_pos: int = 0         # Current read position in frames for monitor
    broadcast_pos: int = 0       # Current read position in frames for broadcast
    active: bool = True
    paused: bool = False
    monitor_active: bool = True
    broadcast_active: bool = True

class AsyncPlayWorker(QRunnable):
    """Worker to decode and prepare audio off the main thread."""
    def __init__(self, engine: 'DualStreamEngine', sound: SoundItem):
        super().__init__()
        self.engine = engine
        self.sound = sound
        
    def run(self):
        cache_key = f"{self.sound.file_path}_{self.sound.volume}_{self.sound.trim_start}_{self.sound.trim_end}"
        
        try:
            decoded = self.engine._decoder.decode(self.sound.file_path)
            if decoded is None:
                self.engine.error_occurred.emit(self.sound.id, "Failed to decode audio file")
                return
        except FileNotFoundError:
            self.engine.error_occurred.emit(self.sound.id, f"File not found: {self.sound.file_path}")
            return
        except Exception as e:
            self.engine.error_occurred.emit(self.sound.id, f"Error decoding audio: {e}")
            return
            
        audio_data = self.engine._prepare_audio(decoded, self.sound)
        if audio_data is None:
            self.engine.error_occurred.emit(self.sound.id, "Failed to prepare audio")
            return
            
        self.engine._prepared_cache[cache_key] = audio_data
        self.engine._finalize_play(self.sound, audio_data)


class AsyncPrepareWorker(QRunnable):
    """Worker to fully decode, resample, and RAM cache audio ahead of time."""
    def __init__(self, engine: 'DualStreamEngine', sound: SoundItem):
        super().__init__()
        self.engine = engine
        self.sound = sound
        
    def run(self):
        cache_key = f"{self.sound.file_path}_{self.sound.volume}_{self.sound.trim_start}_{self.sound.trim_end}"
        if cache_key in self.engine._prepared_cache:
            return
            
        try:
            decoded = self.engine._decoder.decode(self.sound.file_path)
            if decoded is None:
                return
        except FileNotFoundError:
            logger.warning(f"File not found during pre-caching: {self.sound.file_path}")
            return
        except Exception as e:
            logger.error(f"Error pre-caching audio for {self.sound.file_path}: {e}")
            return
            
        audio_data = self.engine._prepare_audio(decoded, self.sound)
        if audio_data is None:
            return
            
        self.engine._prepared_cache[cache_key] = audio_data
        logger.info(f"Pre-cached into RAM: {self.sound.title if hasattr(self.sound, 'title') else self.sound.id}")

class AsyncConfigWorker(QRunnable):
    """Worker to initialize audio streams off the main UI thread."""
    def __init__(self, engine: 'DualStreamEngine'):
        super().__init__()
        self.engine = engine
        
    def run(self):
        try:
            self.engine._apply_device_config_internal()
            self.engine.engine_ready.emit(True)
        except Exception as e:
            logger.error(f"Async engine init failed: {e}")
            self.engine.engine_ready.emit(False)

class DualStreamEngine(QObject):
    """Core audio engine with strict dual-device singleton playback.
    
    Signals:
        playback_started(sound_id: str) - Emitted when a sound begins playing
        playback_finished(sound_id: str) - Emitted when a sound finishes
        playback_stopped(sound_id: str) - Emitted when a sound is stopped manually
        error_occurred(sound_id: str, str) - Emitted on playback errors
    """
    
    playback_started = Signal(str)
    playback_finished = Signal(str)
    playback_stopped = Signal(str)
    error_occurred = Signal(str, str)
    warning_occurred = Signal(str)
    engine_ready = Signal(bool)
    
    def __init__(
        self,
        decoder: AudioDecoder,
        resampler: Resampler,
        device_manager: DeviceManager,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self._decoder = decoder
        self._resampler = resampler
        self._device_manager = device_manager
        
        # Device configuration (sounddevice indices)
        self._microphone_device_id: Optional[int] = None
        self._monitor_device_id: Optional[int] = None
        self._broadcast_device_id: Optional[int] = None
        
        # Volume (0.0 to 1.0)
        self._monitor_volume: float = 0.8
        self._broadcast_volume: float = 1.0
        
        # Overlap mode: "restart" or "mix"
        self._overlap_mode: str = "restart"
        
        # Active playbacks: {sound_id: PlaybackState}
        self._active: Dict[str, PlaybackState] = {}
        self._active_lock = threading.RLock()
        
        # Cache of fully prepared, resampled, and in-memory NumPy arrays
        self._prepared_cache: Dict[str, np.ndarray] = {}
        
        # Real-time microphone buffer (Mic Passthrough)
        self._mic_queue = queue.Queue(maxsize=10)
        self._mic_leftover = np.zeros((0, 2), dtype=np.float32)
        self._mic_stream: Optional[sd.InputStream] = None
        
        # Streams and Threading
        self._monitor_stream: Optional[sd.OutputStream] = None
        self._broadcast_stream: Optional[sd.OutputStream] = None
        self._stream_lock = threading.Lock()
        
        # Target sample rate
        self._target_sample_rate: int = 48000
        self._target_channels: int = 2  # Always output stereo
        

        # Thread pool for background decoding/precaching
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(4)
        
        # Watchdog for stream stalls
        self._last_restart_time = 0.0
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(3000) # Check every 3 seconds
        self._watchdog_timer.timeout.connect(self._check_stream_health)
        self._watchdog_timer.start()
    
    # ── Device Configuration ────────────────────────────────────
    
    def get_available_output_devices(self) -> List[Dict[str, Any]]:
        """Return available output devices as a list of dicts, filtered for WASAPI and uniqueness."""
        devices = []
        try:
            sd_devices = sd.query_devices()
            
            wasapi_api_idx = None
            for idx, api in enumerate(sd.query_hostapis()):
                if 'WASAPI' in api['name']:
                    wasapi_api_idx = idx
                    break
                    
            seen_names = set()
            for idx, dev in enumerate(sd_devices):
                # Filter out zero-channel output devices
                if dev['max_output_channels'] <= 0:
                    continue
                    
                # Always keep Virtual Cable devices even if they are on MME/DirectSound
                name = dev['name']
                lower_name = name.lower()
                is_virtual = ("cable" in lower_name or "vb-audio" in lower_name or "virtual" in lower_name)
                
                # Filter for WASAPI to eliminate MME/DirectSound duplicates
                if wasapi_api_idx is not None and dev['hostapi'] != wasapi_api_idx:
                    if not is_virtual:
                        continue
                        
                # Filter inactive/unwanted endpoints (S/PDIF, HDMI)
                if not is_virtual and ("s/pdif" in lower_name or "hdmi" in lower_name):
                    continue
                    
                # Keep only unique device names
                if name in seen_names:
                    continue
                    
                seen_names.add(name)
                devices.append({"id": idx, "name": name})
                
        except Exception as e:
            logger.error(f"Error querying audio output devices: {e}")
            
        return devices

    def get_available_input_devices(self) -> List[Dict[str, Any]]:
        """Return available input devices (microphones) as a list of dicts, filtered for WASAPI."""
        devices = []
        try:
            sd_devices = sd.query_devices()
            
            wasapi_api_idx = None
            for idx, api in enumerate(sd.query_hostapis()):
                if 'WASAPI' in api['name']:
                    wasapi_api_idx = idx
                    break
                    
            seen_names = set()
            for idx, dev in enumerate(sd_devices):
                # Filter out zero-channel input devices
                if dev['max_input_channels'] <= 0:
                    continue
                    
                name = dev['name']
                lower_name = name.lower()
                
                # Always keep Virtual Cable devices even if they are on MME/DirectSound
                is_virtual = ("cable" in lower_name or "vb-audio" in lower_name or "virtual" in lower_name)
                
                # Filter for WASAPI to eliminate MME/DirectSound duplicates
                if wasapi_api_idx is not None and dev['hostapi'] != wasapi_api_idx:
                    if not is_virtual:
                        continue
                
                # Keep only unique device names
                if name in seen_names:
                    continue
                    
                seen_names.add(name)
                devices.append({"id": idx, "name": name})
                
        except Exception as e:
            logger.error(f"Error querying audio input devices: {e}")
            
        return devices
        
    def install_virtual_driver(self) -> int:
        """Silently install bundled virtual audio cable using ShellExecuteW for UAC elevation.
        Returns 0 on success, 1 on general failure, 5 if UAC denied.
        """
        import ctypes
        try:
            if hasattr(sys, '_MEIPASS'):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.join(os.path.dirname(__file__), "..", "..")
                
            installer_path = os.path.join(base_path, "resources", "vac_setup.exe")
            installer_path = os.path.abspath(installer_path)
            
            if os.path.exists(installer_path):
                logger.info("Prompting UAC for silent driver installation...")
                # return code > 32 means success, 5 means Access Denied
                ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", installer_path, "/S", None, 5)
                if ret > 32:
                    return 0
                elif ret == 5:
                    logger.warning("UAC Elevation denied by user.")
                    return 5
                else:
                    logger.error(f"ShellExecuteW failed with code {ret}")
                    return 1
            else:
                logger.warning(f"Installer not found at {installer_path}")
                return 1
        except Exception as e:
            logger.error(f"Driver installation failed: {e}")
            return 1
        
    def set_output_devices(self, monitor_device_id: Optional[int], broadcast_device_id: Optional[int], microphone_device_id: Optional[int] = None) -> None:
        """Set monitor, broadcast, and microphone device IDs."""
        self._monitor_device_id = monitor_device_id
        self._broadcast_device_id = broadcast_device_id
        self._microphone_device_id = microphone_device_id
        logger.info(f"Devices set - Mic: {microphone_device_id}, Monitor: {monitor_device_id}, Broadcast: {broadcast_device_id}")

    def apply_device_config(self) -> None:
        """Atomically restart continuous singleton streams asynchronously."""
        worker = AsyncConfigWorker(self)
        self._thread_pool.start(worker)

    def _apply_device_config_internal(self) -> None:
        """Internal synchronous setup of streams."""
        with self._stream_lock:
            # 1. Stop and close existing streams
            if self._monitor_stream is not None:
                try:
                    self._monitor_stream.stop()
                    self._monitor_stream.close()
                except Exception as e:
                    logger.debug(f"Error closing monitor stream: {e}")
                self._monitor_stream = None
                
            if self._broadcast_stream is not None:
                try:
                    self._broadcast_stream.stop()
                    self._broadcast_stream.close()
                except Exception as e:
                    logger.debug(f"Error closing broadcast stream: {e}")
                self._broadcast_stream = None
                
            if self._mic_stream is not None:
                try:
                    self._mic_stream.stop()
                    self._mic_stream.close()
                except Exception as e:
                    logger.debug(f"Error closing mic stream: {e}")
                self._mic_stream = None
                
            # Clear mic queue
            while not self._mic_queue.empty():
                try:
                    self._mic_queue.get_nowait()
                except queue.Empty:
                    break
            self._mic_leftover = np.zeros((0, 2), dtype=np.float32)
            
            # 2. Re-create new streams
            monitor_idx = self._monitor_device_id
            broadcast_idx = self._broadcast_device_id
            mic_idx = self._microphone_device_id
            
            # Dynamic Fallback: if monitor_idx is None or invalid, use default output
            if monitor_idx is None:
                try:
                    monitor_idx = sd.default.device[1]
                except Exception:
                    monitor_idx = None
            
            # Fetch sample rate from the primary (monitor) device to prevent resampling lag
            if monitor_idx is not None:
                try:
                    dev_info = sd.query_devices(monitor_idx)
                    self._target_sample_rate = int(dev_info.get('default_samplerate', 48000))
                except Exception:
                    self._target_sample_rate = 48000
            
            # Start Monitor Stream
            if monitor_idx is not None:
                try:
                    self._monitor_stream = self._create_singleton_stream(
                        monitor_idx, "monitor", lambda: self._monitor_volume
                    )
                    self._monitor_stream.start()
                    logger.info("Monitor singleton stream started.")
                except Exception as e:
                    logger.error(f"Failed to start monitor stream: {e}")
            else:
                logger.error("No valid monitor device found or default device is missing.")
                    
            # Start Broadcast Stream
            if broadcast_idx is not None:
                try:
                    self._broadcast_stream = self._create_singleton_stream(
                        broadcast_idx, "broadcast", lambda: self._broadcast_volume
                    )
                    self._broadcast_stream.start()
                    logger.info("Broadcast singleton stream started.")
                except Exception as e:
                    logger.error(f"Failed to start broadcast stream: {e}")
                    
            # Start Microphone Stream (Input)
            if mic_idx is not None and broadcast_idx is not None:
                try:
                    self._mic_stream = self._create_mic_stream(mic_idx)
                    if self._mic_stream is not None:
                        self._mic_stream.start()
                        logger.info("Microphone passthrough stream started.")
                except Exception as e:
                    logger.error(f"Failed to start microphone stream: {e}")

    def set_monitor_volume(self, volume: float) -> None:
        """Set monitor volume (0.0 to 1.0)."""
        self._monitor_volume = max(0.0, min(1.0, volume))
    
    def set_broadcast_volume(self, volume: float) -> None:
        """Set broadcast volume (0.0 to 1.0)."""
        self._broadcast_volume = max(0.0, min(1.0, volume))
    
    def set_overlap_mode(self, mode: str) -> None:
        """Set overlap mode: 'restart' or 'mix'."""
        if mode in ("restart", "mix"):
            self._overlap_mode = mode
            logger.info(f"Overlap mode set to: {mode}")

    def _check_stream_health(self) -> None:
        """Watchdog to auto-recover stalled streams without blocking the main thread."""
        import time
        now = time.time()
        
        # 30-second cooldown to prevent restart loops
        if now - getattr(self, '_last_restart_time', 0) < 30.0:
            return

        needs_restart = False
        
        with self._stream_lock:
            # Only trigger recovery if the stream is explicitly NOT active
            if self._mic_stream is not None and not self._mic_stream.active:
                logger.warning("Watchdog: Microphone stream is dead (not active).")
                needs_restart = True
                    
            if self._monitor_stream is not None and not self._monitor_stream.active:
                logger.warning("Watchdog: Monitor stream is dead (not active).")
                needs_restart = True
                    
            if self._broadcast_stream is not None and not self._broadcast_stream.active:
                logger.warning("Watchdog: Broadcast stream is dead (not active).")
                needs_restart = True

        if needs_restart:
            logger.info("Watchdog triggering automatic stream recovery...")
            self._last_restart_time = now
            self.apply_device_config()
    
    # ── Volume Properties ──────────────────────────────────────
    
    @property
    def monitor_volume(self) -> float:
        return self._monitor_volume
    
    @property
    def broadcast_volume(self) -> float:
        return self._broadcast_volume
    
    # ── Playback Control ───────────────────────────────────────
    
    def precache_sounds(self, sounds: list[SoundItem]) -> None:
        """Queue sounds to be fully prepared in the background."""
        for sound in sounds:
            cache_key = f"{sound.file_path}_{sound.volume}_{sound.trim_start}_{sound.trim_end}"
            if cache_key not in self._prepared_cache:
                worker = AsyncPrepareWorker(self, sound)
                self._thread_pool.start(worker)
                
    def play(self, sound: SoundItem) -> bool:
        """Play a sound to both monitor and broadcast devices.
        
        In 'restart' mode: stops any existing playback of the same sound first.
        In 'mix' mode: layers the new playback on top of existing ones.
        """
        if not self._decoder.validate_file(sound.file_path):
            self.error_occurred.emit(sound.id, f"File not found: {sound.file_path}")
            return False
        
        if self._overlap_mode == "restart":
            self.stop_all()
        
        cache_key = f"{sound.file_path}_{sound.volume}_{sound.trim_start}_{sound.trim_end}"
        
        # 1. Check if we already have the fully prepared, pre-resampled audio in RAM cache
        if cache_key in self._prepared_cache:
            audio_data = self._prepared_cache[cache_key]
            self._finalize_play(sound, audio_data)
            return True
            
        # 2. If not in cache, we MUST not block the thread. Just queue async worker
        logger.info(f"Audio not fully pre-cached, falling back to async preparation for {sound.id}")
        worker = AsyncPlayWorker(self, sound)
        self._thread_pool.start(worker)
        
        return True
        
    def _finalize_play(self, sound: SoundItem, audio_data: np.ndarray) -> None:
        """Internal method to commit prepared audio into active playback."""
        with self._stream_lock:
            if self._monitor_stream is None and self._broadcast_stream is None:
                self.error_occurred.emit(sound.id, "No audio output devices available. Playback aborted.")
                return
        
        state = PlaybackState(
            sound_id=sound.id,
            audio_data=audio_data,
            monitor_active=(self._monitor_stream is not None),
            broadcast_active=(self._broadcast_stream is not None)
        )
        
        with self._active_lock:
            self._active[sound.id] = state
            
        self.playback_started.emit(sound.id)
    
    def stop(self, sound_id: str) -> None:
        """Stop playback of a specific sound."""
        with self._active_lock:
            if sound_id in self._active:
                self._active[sound_id].active = False
                del self._active[sound_id]
                self.playback_stopped.emit(sound_id)
    
    def stop_all(self) -> None:
        """Stop ALL active playbacks immediately."""
        with self._active_lock:
            if not self._active:
                return
            for s_id, state in self._active.items():
                state.active = False
            self._active.clear()
        logger.info("All playbacks stopped")
    
    def is_playing(self, sound_id: str) -> bool:
        """Check if a specific sound is currently playing (and not paused)."""
        with self._active_lock:
            state = self._active.get(sound_id)
        return state is not None and state.active and not state.paused
        
    def toggle_pause(self, sound_id: str) -> bool:
        """Toggle pause state for a specific sound. Returns the new paused state."""
        with self._active_lock:
            state = self._active.get(sound_id)
            if state is not None and state.active:
                state.paused = not state.paused
                return state.paused
        return False
        
    def seek(self, sound_id: str, position_sec: float) -> None:
        """Seek to a specific position in seconds."""
        with self._active_lock:
            state = self._active.get(sound_id)
            if state is not None and state.active:
                target_frame = int(position_sec * self._target_sample_rate)
                # Clamp to bounds
                max_frame = state.audio_data.shape[0] - 1
                target_frame = max(0, min(target_frame, max_frame))
                
                state.monitor_pos = target_frame
                state.broadcast_pos = target_frame
                
    def get_playback_progress(self, sound_id: str) -> Optional[tuple[float, float, bool]]:
        """Return (current_sec, total_sec, is_paused) for a playing sound."""
        with self._active_lock:
            state = self._active.get(sound_id)
            if state is not None and state.active:
                # Use max of both positions to be safe
                current_frame = max(state.monitor_pos, state.broadcast_pos)
                current_sec = current_frame / self._target_sample_rate
                total_sec = state.audio_data.shape[0] / self._target_sample_rate
                return current_sec, total_sec, state.paused
        return None
    
    @property
    def active_count(self) -> int:
        """Number of currently active playbacks."""
        with self._active_lock:
            return sum(1 for s in self._active.values() if s.active)
    
    def shutdown(self) -> None:
        """Clean shutdown: stop all playbacks and close singleton streams."""
        self.stop_all()
        with self._stream_lock:
            if self._monitor_stream is not None:
                self._monitor_stream.stop()
                self._monitor_stream.close()
                self._monitor_stream = None
            if self._broadcast_stream is not None:
                self._broadcast_stream.stop()
                self._broadcast_stream.close()
                self._broadcast_stream = None
        self._decoder.clear_cache()
        logger.info("DualStreamEngine shut down")
    
    # ── Internal Methods ───────────────────────────────────────
    
    def _prepare_audio(
        self, decoded: DecodedAudio, sound: SoundItem
    ) -> Optional[np.ndarray]:
        """Trim, resample, apply gain, and ensure stereo."""
        try:
            samples = decoded.samples.copy()
            sr = decoded.sample_rate
            
            # Trim
            start_frame = int(sound.trim_start * sr)
            if sound.trim_end > 0:
                end_frame = int(sound.trim_end * sr)
            else:
                end_frame = samples.shape[0]
            
            start_frame = max(0, min(start_frame, samples.shape[0]))
            end_frame = max(start_frame, min(end_frame, samples.shape[0]))
            samples = samples[start_frame:end_frame]
            
            if samples.shape[0] == 0: return None
            
            # Resample
            if sr != self._target_sample_rate:
                samples = self._resampler.resample(samples, sr, self._target_sample_rate)
            
            # Stereo
            if samples.ndim == 1:
                samples = np.column_stack([samples, samples])
            elif samples.shape[1] == 1:
                samples = np.column_stack([samples[:, 0], samples[:, 0]])
            elif samples.shape[1] > 2:
                samples = samples[:, :2]
            
            # 1. Presence Simulation (Speech Band Alignment)
            # Apply a slight mid-range pre-emphasis filter to prevent 
            # Discord's noise suppression (Krisp) from muting the audio
            if samples.shape[0] > 1:
                samples[1:] = samples[1:] - 0.45 * samples[:-1]

            # 2. Soundboard Gain Normalization (Peak to ~85% / -1.4dB)
            peak = np.max(np.abs(samples))
            if peak > 0.0:
                samples = samples * (0.85 / peak)

            # Volume
            if sound.volume != 1.0:
                samples = samples * sound.volume
            
            samples = np.clip(samples, -1.0, 1.0)
            samples = samples.astype(np.float32)
            return np.ascontiguousarray(samples, dtype=np.float32)
            
        except Exception as e:
            logger.error(f"Audio preparation failed: {e}")
            return None

    def _create_mic_stream(self, device_index: int) -> Optional[sd.InputStream]:
        """Create a continuous background input stream to capture microphone."""
        try:
            dev_info = sd.query_devices(device_index)
            mic_channels = min(2, dev_info.get('max_input_channels', 2))
            if mic_channels < 1:
                mic_channels = 1
            mic_sr = int(dev_info.get('default_samplerate', self._target_sample_rate))
        except Exception as e:
            logger.warning(f"Could not query mic info, defaulting: {e}")
            mic_channels = 1
            mic_sr = self._target_sample_rate
            
        log_counter = [0]
        
        def callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            try:
                if status:
                    if status.input_overflow:
                        logger.warning("Microphone stream overflow - discarding frame.")
                        return
                    logger.warning(f"Mic stream status: {status}")
                
                # 1. UNIVERSAL INPUT SANITIZATION
                data = indata.copy()
                
                # Type Conversion (NO SILENT DROP - safely map types)
                if data.dtype == np.int16:
                    data = data.astype(np.float32) / 32768.0
                elif data.dtype == np.int32:
                    data = data.astype(np.float32) / 2147483648.0
                elif data.dtype != np.float32:
                    data = data.astype(np.float32)
                    
                # Channel Normalization
                if data.ndim == 1:
                    data = np.column_stack((data, data))
                elif data.shape[1] == 1:
                    data = np.column_stack((data[:, 0], data[:, 0]))
                elif data.shape[1] > 2:
                    data = data[:, :2]
                
                # Log max amplitude every ~1 second (assuming 2048 frames at 48000Hz = ~23 blocks/sec)
                log_counter[0] += 1
                if log_counter[0] >= 23:
                    amplitude = float(np.max(np.abs(data)))
                    logger.info(f"MIC LEVEL: {amplitude:.4f}")
                    log_counter[0] = 0

                # 2. RESAMPLING GUARD
                if mic_sr != self._target_sample_rate:
                    # Fast linear interpolation for low-latency callback
                    num_frames = data.shape[0]
                    target_frames = int((num_frames * self._target_sample_rate) / mic_sr)
                    old_x = np.linspace(0, 1, num_frames)
                    new_x = np.linspace(0, 1, target_frames)
                    
                    resampled = np.zeros((target_frames, 2), dtype=np.float32)
                    resampled[:, 0] = np.interp(new_x, old_x, data[:, 0])
                    resampled[:, 1] = np.interp(new_x, old_x, data[:, 1])
                    data = resampled
                    
                # Put data into the ring buffer
                if self._mic_queue.full():
                    try:
                        self._mic_queue.get_nowait()
                    except queue.Empty:
                        pass
                try:
                    self._mic_queue.put_nowait(data)
                except queue.Full:
                    pass
            except Exception as e:
                logger.warning(f"Error in mic callback (guard active): {e}")

        try:
            dev_info = sd.query_devices(device_index)
            hostapi_info = sd.query_hostapis(dev_info['hostapi'])
            is_wasapi = ('WASAPI' in hostapi_info['name'])
        except Exception:
            is_wasapi = False

        if is_wasapi:
            try:
                wasapi_settings = sd.WasapiSettings(exclusive=False)
                extra_settings = wasapi_settings
            except Exception:
                extra_settings = None
        else:
            extra_settings = None

        try:
            return sd.InputStream(
                samplerate=mic_sr,
                channels=mic_channels,
                device=device_index,
                dtype='float32',
                blocksize=0,
                latency='low',
                callback=callback,
                extra_settings=extra_settings
            )
        except sd.PortAudioError as e:
            logger.warning(f"Failed to open microphone stream on device {device_index}: {e}. Retrying without WASAPI exclusive settings.")
            try:
                return sd.InputStream(
                    samplerate=mic_sr,
                    channels=mic_channels,
                    device=device_index,
                    dtype='float32',
                    blocksize=0,
                    latency='low',
                    callback=callback
                )
            except Exception as e2:
                logger.error(f"Failed to fallback open microphone stream: {e2}")
                return None
        except Exception as e:
            logger.error(f"Failed to initialize mic InputStream on device {device_index}: {e}")
            return None

    def _create_singleton_stream(
        self, device_index: int, stream_name: str, volume_getter
    ) -> sd.OutputStream:
        """Create a continuous background stream that pulls from active playbacks."""
        
        def callback(outdata: np.ndarray, frames: int, time_info, status) -> None:
            if status:
                logger.debug("Audio stream status flag raised")
            
            is_monitor = (stream_name == "monitor")
            
            if not is_monitor:
                # Add imperceptible dither (white noise at -80dB) to Broadcast stream
                # This ensures a continuous noise floor so Discord's VAD stays open
                dither = np.random.normal(0, 1e-4, outdata.shape).astype(np.float32)
                outdata[:] = dither
            else:
                outdata.fill(0.0) # Default to silence
            
            vol = volume_getter()
            
            # 1. Add Active Soundboard Playbacks to both streams
            with self._active_lock:
                if self._active:
                    finished_sounds = []
                    for s_id, state in self._active.items():
                        if not state.active or state.paused:
                            continue
                            
                        pos = state.monitor_pos if is_monitor else state.broadcast_pos
                        
                        if not is_monitor and not state.broadcast_active:
                            continue
                        if is_monitor and not state.monitor_active:
                            continue
                            
                        rem = state.audio_data.shape[0] - pos
                        if rem <= 0:
                            if is_monitor: state.monitor_active = False
                            else: state.broadcast_active = False
                            continue
                            
                        chunk = min(frames, rem)
                        
                        # Mix audio (add into outdata with volume applied)
                        if vol != 1.0:
                            outdata[:chunk] += (state.audio_data[pos:pos+chunk] * vol)
                        else:
                            outdata[:chunk] += state.audio_data[pos:pos+chunk]
                        
                        if is_monitor:
                            state.monitor_pos += chunk
                        else:
                            state.broadcast_pos += chunk
                            
                        # Check if stream finished
                        if pos + chunk >= state.audio_data.shape[0]:
                            if is_monitor: state.monitor_active = False
                            else: state.broadcast_active = False
                            
                        if not state.monitor_active and not state.broadcast_active:
                            state.active = False
                            finished_sounds.append(s_id)
                    
                    # Cleanup finished
                    for s_id in finished_sounds:
                        self._active.pop(s_id, None)
                        # Safe cross-thread pyqtSignal emit
                        self.playback_finished.emit(s_id)

            # 2. Add Microphone Passthrough ONLY for Broadcast stream
            # Mic is added AFTER soundboard volume scaling so user is always heard.
            if not is_monitor and self._mic_stream is not None:
                mic_written = 0
                
                # First use any leftover mic data
                if self._mic_leftover.shape[0] > 0:
                    chunk = min(frames, self._mic_leftover.shape[0])
                    outdata[:chunk] += self._mic_leftover[:chunk]
                    self._mic_leftover = self._mic_leftover[chunk:]
                    mic_written += chunk
                    
                # Then pull from queue until we fill the needed frames
                while mic_written < frames:
                    try:
                        mic_data = self._mic_queue.get_nowait()
                        chunk = min(frames - mic_written, mic_data.shape[0])
                        outdata[mic_written:mic_written+chunk] += mic_data[:chunk]
                        
                        if chunk < mic_data.shape[0]:
                            self._mic_leftover = mic_data[chunk:]
                            
                        mic_written += chunk
                    except queue.Empty:
                        break
                
            # Hard clip to prevent additive distortion
            np.clip(outdata, -1.0, 1.0, out=outdata)

        try:
            dev_info = sd.query_devices(device_index)
            hostapi_info = sd.query_hostapis(dev_info['hostapi'])
            is_wasapi = ('WASAPI' in hostapi_info['name'])
        except Exception:
            is_wasapi = False

        if is_wasapi:
            try:
                wasapi_settings = sd.WasapiSettings(exclusive=False)
                extra_settings = wasapi_settings
            except Exception:
                extra_settings = None
        else:
            extra_settings = None

        try:
            return sd.OutputStream(
                samplerate=self._target_sample_rate,
                channels=self._target_channels,
                device=device_index,
                dtype='float32',
                blocksize=2048,
                latency='high',
                callback=callback,
                extra_settings=extra_settings
            )
        except sd.PortAudioError as e:
            logger.warning(f"Failed to open {stream_name} stream on device {device_index}: {e}. Attempting default fallback.")
            return sd.OutputStream(
                samplerate=self._target_sample_rate,
                channels=self._target_channels,
                device=None,
                dtype='float32',
                blocksize=2048,
                latency='high',
                callback=callback
            )
