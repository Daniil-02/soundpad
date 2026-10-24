"""High-quality sample rate conversion using libsoxr.

Handles resampling between common audio rates (44.1kHz, 48kHz, etc.)
without introducing pitch distortion or audible artifacts.
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Quality presets for soxr
QUALITY_QUICK = "QQ"    # Quick quality (lowest latency)
QUALITY_LOW = "LQ"      # Low quality  
QUALITY_MEDIUM = "MQ"   # Medium quality
QUALITY_HIGH = "HQ"     # High quality (recommended for music)
QUALITY_VERY_HIGH = "VHQ"  # Very high quality (highest fidelity)

DEFAULT_QUALITY = QUALITY_HIGH


class Resampler:
    """High-quality audio resampler using libsoxr.
    
    Provides broadcast-quality sample rate conversion for matching
    audio file sample rates to device hardware rates.
    """
    
    def __init__(self, quality: str = DEFAULT_QUALITY):
        self._quality = quality
        self._soxr_available = self._check_soxr()
    
    @staticmethod
    def _check_soxr() -> bool:
        """Check if soxr is available."""
        try:
            import soxr  # noqa: F401
            return True
        except ImportError:
            logger.warning(
                "soxr not installed. Sample rate conversion will use "
                "numpy linear interpolation (lower quality). "
                "Install with: pip install soxr"
            )
            return False
    
    def resample(
        self,
        data: np.ndarray,
        src_rate: int,
        dst_rate: int,
        quality: Optional[str] = None
    ) -> np.ndarray:
        """Resample audio data from src_rate to dst_rate.
        
        Args:
            data: Input audio as float32 numpy array.
                  Shape can be (num_samples,) for mono or
                  (num_samples, channels) for multi-channel.
            src_rate: Source sample rate in Hz (e.g., 44100).
            dst_rate: Target sample rate in Hz (e.g., 48000).
            quality: Override quality preset. Defaults to instance quality.
        
        Returns:
            Resampled audio as float32 numpy array with same shape convention.
        """
        # Passthrough if rates already match
        if src_rate == dst_rate:
            return data
        
        if src_rate <= 0 or dst_rate <= 0:
            logger.error(f"Invalid sample rates: {src_rate} -> {dst_rate}")
            return data
        
        q = quality or self._quality
        
        # Ensure float32
        if data.dtype != np.float32:
            data = data.astype(np.float32)
        
        try:
            if self._soxr_available:
                return self._resample_soxr(data, src_rate, dst_rate, q)
            else:
                return self._resample_fallback(data, src_rate, dst_rate)
        except Exception as e:
            logger.error(f"Resampling failed ({src_rate}->{dst_rate}): {e}")
            return data  # Return original on failure
    
    def _resample_soxr(
        self,
        data: np.ndarray,
        src_rate: int,
        dst_rate: int,
        quality: str
    ) -> np.ndarray:
        """Resample using libsoxr (high quality)."""
        import soxr
        
        resampled = soxr.resample(
            data,
            in_rate=src_rate,
            out_rate=dst_rate,
            quality=quality
        )
        
        logger.debug(
            f"soxr resample: {src_rate}Hz -> {dst_rate}Hz | "
            f"{data.shape[0]} -> {resampled.shape[0]} samples | "
            f"quality={quality}"
        )
        
        return resampled.astype(np.float32)
    
    def _resample_fallback(
        self,
        data: np.ndarray,
        src_rate: int,
        dst_rate: int
    ) -> np.ndarray:
        """Fallback resampler using high-quality scipy/librosa if available."""
        try:
            import scipy.signal
            import math
            gcd = math.gcd(src_rate, dst_rate)
            up = dst_rate // gcd
            down = src_rate // gcd
            
            if data.ndim == 1:
                resampled = scipy.signal.resample_poly(data, up, down)
            else:
                resampled = scipy.signal.resample_poly(data, up, down, axis=0)
            return resampled.astype(np.float32)
            
        except ImportError:
            try:
                import librosa
                if data.ndim == 1:
                    resampled = librosa.resample(data, orig_sr=src_rate, target_sr=dst_rate, res_type='soxr_hq')
                else:
                    data_t = data.T
                    resampled_t = librosa.resample(data_t, orig_sr=src_rate, target_sr=dst_rate, res_type='soxr_hq')
                    resampled = resampled_t.T
                return resampled.astype(np.float32)
                
            except ImportError:
                logger.warning("Scipy and librosa not found. Falling back to linear interpolation.")
                ratio = dst_rate / src_rate
                if data.ndim == 1:
                    old_length = len(data)
                    new_length = int(old_length * ratio)
                    old_indices = np.arange(old_length)
                    new_indices = np.linspace(0, old_length - 1, new_length)
                    resampled = np.interp(new_indices, old_indices, data)
                    return resampled.astype(np.float32)
                else:
                    old_length = data.shape[0]
                    new_length = int(old_length * ratio)
                    channels = data.shape[1]
                    old_indices = np.arange(old_length)
                    new_indices = np.linspace(0, old_length - 1, new_length)
                    
                    resampled = np.zeros((new_length, channels), dtype=np.float32)
                    for ch in range(channels):
                        resampled[:, ch] = np.interp(new_indices, old_indices, data[:, ch])
                    return resampled
    
    @property
    def quality(self) -> str:
        """Current quality preset."""
        return self._quality
    
    @quality.setter
    def quality(self, value: str) -> None:
        """Set quality preset."""
        valid = {QUALITY_QUICK, QUALITY_LOW, QUALITY_MEDIUM, 
                 QUALITY_HIGH, QUALITY_VERY_HIGH}
        if value not in valid:
            raise ValueError(f"Invalid quality '{value}'. Must be one of {valid}")
        self._quality = value
    
    @property
    def is_high_quality(self) -> bool:
        """Whether soxr is available for high-quality resampling."""
        return self._soxr_available
