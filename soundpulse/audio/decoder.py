"""Audio file decoder using miniaudio with LRU caching.

Decodes MP3, WAV, FLAC, and OGG files into numpy float32 arrays
for playback through the dual-stream engine.
"""

import logging
import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import miniaudio
import numpy as np
from PySide6.QtCore import QRunnable

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".ogg"}
MAX_CACHE_SIZE_MB = 250  # Maximum MB of RAM to use for audio caching


@dataclass
class DecodedAudio:
    """Container for decoded audio data."""
    samples: np.ndarray      # float32 array, shape (num_samples, channels)
    sample_rate: int          # Original sample rate (e.g., 44100, 48000)
    channels: int             # Number of channels (1=mono, 2=stereo)
    duration: float           # Duration in seconds


class AudioDecoder:
    """Decodes audio files and caches results in an LRU dictionary.
    
    Uses miniaudio for zero-dependency decoding of MP3, WAV, FLAC, OGG.
    Decoded audio is stored as float32 numpy arrays normalized to [-1.0, 1.0].
    """
    
    def __init__(self, max_cache_mb: int = MAX_CACHE_SIZE_MB):
        self._cache: OrderedDict[str, DecodedAudio] = OrderedDict()
        self._max_cache_bytes = max_cache_mb * 1024 * 1024
        self._current_cache_bytes = 0
    
    def is_supported(self, file_path: str) -> bool:
        """Check if the file format is supported."""
        ext = Path(file_path).suffix.lower()
        return ext in SUPPORTED_FORMATS
        
    def is_cached(self, file_path: str) -> bool:
        """Check if the file is already decoded and cached."""
        return os.path.abspath(file_path) in self._cache
    
    def validate_file(self, file_path: str) -> bool:
        """Validate that the file exists and is a supported format."""
        if not os.path.isfile(file_path):
            logger.warning(f"File not found: {file_path}")
            return False
        if not self.is_supported(file_path):
            logger.warning(f"Unsupported format: {file_path}")
            return False
        return True
    
    def decode(self, file_path: str) -> Optional[DecodedAudio]:
        """Decode an audio file and return DecodedAudio, using cache if available.
        
        Returns None if the file is missing, unsupported, or corrupted.
        """
        # Normalize path for cache key
        abs_path = os.path.abspath(file_path)
        
        # Check cache first (move to end for LRU)
        if abs_path in self._cache:
            self._cache.move_to_end(abs_path)
            return self._cache[abs_path]
        
        # Validate before attempting decode
        if not self.validate_file(abs_path):
            return None
        
        try:
            ext = Path(abs_path).suffix.lower()
            if ext in {".ogg", ".wav", ".flac"}:
                try:
                    import soundfile as sf
                    samples, sample_rate = sf.read(abs_path, dtype='float32', always_2d=True)
                    channels = samples.shape[1]
                    duration = samples.shape[0] / sample_rate
                    
                    audio = DecodedAudio(
                        samples=samples,
                        sample_rate=sample_rate,
                        channels=channels,
                        duration=duration
                    )
                    
                    self._evict_if_needed(samples.nbytes)
                    self._cache[abs_path] = audio
                    self._current_cache_bytes += samples.nbytes
                    logger.info(f"Decoded (sf): {Path(abs_path).name} | {duration:.1f}s")
                    return audio
                except Exception as sf_e:
                    logger.warning(f"soundfile failed for {ext}, falling back: {sf_e}")
                    
            # Use miniaudio to decode the entire file into PCM (for MP3 or fallback)
            decoded = miniaudio.decode_file(
                abs_path,
                output_format=miniaudio.SampleFormat.FLOAT32,
                dither=miniaudio.DitherMode.TRIANGLE
            )
            
            # Convert raw bytes to numpy float32 array
            samples = np.frombuffer(decoded.samples, dtype=np.float32).copy()
            
            # Reshape to (num_samples, channels)
            channels = decoded.nchannels
            samples = samples.reshape(-1, channels)
            
            # Calculate duration
            num_frames = samples.shape[0]
            duration = num_frames / decoded.sample_rate
            
            audio = DecodedAudio(
                samples=samples,
                sample_rate=decoded.sample_rate,
                channels=channels,
                duration=duration
            )
            
            # Add to cache, evict oldest if full
            self._evict_if_needed(samples.nbytes)
            self._cache[abs_path] = audio
            self._current_cache_bytes += samples.nbytes
            
            logger.info(
                f"Decoded (ma): {Path(abs_path).name} | "
                f"{channels}ch {decoded.sample_rate}Hz | "
                f"{duration:.1f}s | "
                f"{samples.nbytes / 1024:.0f}KB"
            )
            
            return audio
            
        except Exception as e:
            logger.error(f"Failed to decode {abs_path}: {e}")
            return None
    
    def get_file_info(self, file_path: str) -> Optional[dict]:
        """Get basic file info without full decoding."""
        abs_path = os.path.abspath(file_path)
        if not self.validate_file(abs_path):
            return None
        try:
            ext = Path(abs_path).suffix.lower()
            if ext in {".ogg", ".wav", ".flac"}:
                try:
                    import soundfile as sf
                    info = sf.info(abs_path)
                    return {
                        "duration": info.duration,
                        "sample_rate": info.samplerate,
                        "channels": info.channels,
                        "format_name": info.format
                    }
                except Exception:
                    pass
                    
            info = miniaudio.get_file_info(abs_path)
            return {
                "duration": info.duration,
                "sample_rate": info.sample_rate,
                "channels": info.nchannels,
                "format_name": info.file_format.name if hasattr(info.file_format, 'name') else str(info.file_format),
            }
        except Exception as e:
            logger.error(f"Failed to read file info for {abs_path}: {e}")
            return None
    
    def get_waveform_data(self, file_path: str, num_points: int = 800) -> Optional[np.ndarray]:
        """Get downsampled waveform peaks for visualization.
        
        Returns a numpy array of shape (num_points, 2) with [min, max] per bucket.
        This is designed for efficient QPainter rendering.
        """
        audio = self.decode(file_path)
        if audio is None:
            return None
        
        # Mix to mono for waveform display
        if audio.channels > 1:
            mono = np.mean(audio.samples, axis=1)
        else:
            mono = audio.samples.ravel()
        
        total_samples = len(mono)
        if total_samples == 0:
            return None
        
        # Clamp num_points to not exceed sample count
        num_points = min(num_points, total_samples)
        
        bucket_size = total_samples // num_points
        if bucket_size < 1:
            bucket_size = 1
        
        # Trim to exact multiple of bucket_size
        trimmed = mono[:bucket_size * num_points]
        buckets = trimmed.reshape(num_points, bucket_size)
        
        peaks = np.column_stack([
            buckets.min(axis=1),
            buckets.max(axis=1)
        ])
        
        return peaks
    
    def _evict_if_needed(self, required_bytes: int = 0) -> None:
        """Evict oldest entries if cache exceeds max memory or to make room."""
        while len(self._cache) > 0 and (self._current_cache_bytes + required_bytes) > self._max_cache_bytes:
            evicted_key, evicted = self._cache.popitem(last=False)
            self._current_cache_bytes -= evicted.samples.nbytes
            logger.debug(f"Cache evicted (Memory): {Path(evicted_key).name}")
    
    def remove_from_cache(self, file_path: str) -> None:
        """Remove a specific file from the cache."""
        abs_path = os.path.abspath(file_path)
        if abs_path in self._cache:
            self._current_cache_bytes -= self._cache[abs_path].samples.nbytes
            self._cache.pop(abs_path, None)
    
    def clear_cache(self) -> None:
        """Clear the entire decode cache to free memory."""
        self._cache.clear()
        self._current_cache_bytes = 0
        logger.info("Audio decode cache cleared")
    
    @property
    def cache_size(self) -> int:
        """Number of currently cached decoded audio files."""
        return len(self._cache)
    
    @property
    def cache_memory_bytes(self) -> int:
        """Approximate total memory used by cached audio data in bytes."""
        return self._current_cache_bytes

class PrecacheWorker(QRunnable):
    """Background worker to decode an audio file into the cache."""
    def __init__(self, decoder: AudioDecoder, file_path: str):
        super().__init__()
        self.decoder = decoder
        self.file_path = file_path
        
    def run(self):
        try:
            if not self.decoder.is_cached(self.file_path):
                self.decoder.decode(self.file_path)
        except Exception as e:
            logger.error(f"Failed to precache {self.file_path}: {e}")

