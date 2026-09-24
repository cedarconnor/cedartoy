import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple
import soundfile as sf
from scipy.signal import spectrogram

from .types import AudioMeta

# Shadertoy's audio texture comes from a WebAudio AnalyserNode with
# fftSize=2048: 1024 bins of sr/2048 Hz each, of which the texture keeps the
# first 512 (0..~11 kHz at 44.1 kHz). Values are dB mapped from
# [minDecibels, maxDecibels] = [-100, -30] to [0, 1].
FFT_SIZE = 2048
MIN_DB = -100.0
MAX_DB = -30.0
# AnalyserNode.smoothingTimeConstant default. WebAudio applies it once per
# getByteFrequencyData() call, i.e. per ~60 Hz animation frame in Shadertoy.
# We apply it once per *render* frame, so it is rescaled to the render fps:
# tau_eff = 0.8 ** (60 / fps), giving the same decay per second of audio.
SMOOTHING_TIME_CONSTANT = 0.8
SMOOTHING_REFERENCE_FPS = 60.0
SMOOTHING_WARMUP_FRAMES = 32


def smoothing_tau_for_fps(fps: float) -> float:
    if fps <= 0:
        return SMOOTHING_TIME_CONSTANT
    return SMOOTHING_TIME_CONSTANT ** (SMOOTHING_REFERENCE_FPS / fps)


def fft_magnitudes(chunk: np.ndarray) -> np.ndarray:
    """Blackman-windowed |FFT| scaled by 1/fftSize (AnalyserNode step 1-3)."""
    n = len(chunk)
    spec = np.fft.rfft(chunk * np.blackman(n))
    return (np.abs(spec) / n)[: n // 2]


def smooth_magnitudes(mag: np.ndarray, prev: Optional[np.ndarray], tau: float) -> np.ndarray:
    """X_hat[k] = tau * X_hat_prev[k] + (1 - tau) * |X[k]| (linear magnitude)."""
    if prev is None or prev.shape != mag.shape:
        prev = np.zeros_like(mag)
    return tau * prev + (1.0 - tau) * mag


def magnitudes_to_unit(mag: np.ndarray) -> np.ndarray:
    """Linear magnitude -> dB -> [MIN_DB, MAX_DB] mapped to [0, 1]."""
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(mag, 0.0))
    unit = (db - MIN_DB) / (MAX_DB - MIN_DB)
    return np.clip(np.nan_to_num(unit, neginf=0.0), 0.0, 1.0).astype(np.float32)

@dataclass
class AudioData:
    samples: np.ndarray      # shape (N, channels)
    sample_rate: int
    meta: AudioMeta
    fft_data: np.ndarray     # Precomputed FFT or STFT data
    # We might store STFT as (freqs, times, magnitudes)

class AudioProcessor:
    def __init__(self, audio_path: Path, fps: float):
        self.audio_path = audio_path
        self.fps = fps
        self.data: Optional[AudioData] = None
        self.history_texture: Optional[np.ndarray] = None
        
        self._load()
        self._precompute()

    def _load(self):
        if not self.audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {self.audio_path}")
        
        data, samplerate = sf.read(str(self.audio_path), always_2d=True)
        # data is (samples, channels)
        
        duration = len(data) / samplerate
        frame_count = int(duration * self.fps)
        
        # AudioMeta
        # freq_bins: We'll use 512 for Shadertoy compat, but history might use more or same.
        # Shadertoy uses 512 bins.
        self.meta = AudioMeta(
            duration_sec=duration,
            sample_rate=samplerate,
            frame_count=frame_count,
            freq_bins=512,
            channels=data.shape[1],
            audio_fps=self.fps
        )
        
        self.data = AudioData(
            samples=data,
            sample_rate=samplerate,
            meta=self.meta,
            fft_data=None # computed later
        )

    def _precompute(self):
        """Pre-compute all per-frame FFT textures for faster rendering.

        Runs sequentially because the WebAudio-style spectrum smoothing is
        stateful (each frame blends with the previous frame's magnitudes).
        """
        if self.data is None:
            return
        frames = self.meta.frame_count
        if frames <= 0:
            return
        self._precomputed_textures = {}
        smoothed = None
        for f in range(frames):
            tex, smoothed = self._compute_shadertoy_texture(f, smoothed)
            self._precomputed_textures[f] = tex

    def get_shadertoy_texture(self, frame_index: int) -> np.ndarray:
        """Return cached precomputed texture if available, otherwise compute on-the-fly."""
        if self.data is None:
            return np.zeros((2, 512), dtype=np.float32)

        if hasattr(self, '_precomputed_textures') and frame_index in self._precomputed_textures:
            return self._precomputed_textures[frame_index]

        # Not cached (e.g. past the precomputed range): warm the smoothing up
        # over the preceding frames so the result approximates the
        # sequential value. tau_eff**WARMUP is negligible.
        smoothed = None
        for f in range(frame_index - SMOOTHING_WARMUP_FRAMES, frame_index):
            _, smoothed = self._compute_shadertoy_texture(f, smoothed)
        tex, _ = self._compute_shadertoy_texture(frame_index, smoothed)
        return tex

    def _mono_window(self, center_sample: int, size: int) -> np.ndarray:
        """`size` consecutive mono samples centred on `center_sample`, zero-padded."""
        start = center_sample - size // 2
        end = start + size
        n = len(self.data.samples)
        lo, hi = max(0, start), min(n, end)
        chunk = np.zeros(size, dtype=np.float64)
        if hi > lo:
            src = self.data.samples[lo:hi, :]
            chunk[lo - start:hi - start] = np.mean(src, axis=1) if src.shape[1] > 1 else src[:, 0]
        return chunk

    def smoothing_tau(self) -> float:
        return smoothing_tau_for_fps(self.fps)

    def _compute_shadertoy_texture(self, frame_index: int,
                                   prev_smoothed: Optional[np.ndarray] = None
                                   ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute the 2x512 FFT+waveform texture for a single frame.

        Returns (texture, smoothed_magnitudes); pass the latter back in as
        `prev_smoothed` for the next frame.
        """
        center_sample = int(round((frame_index / self.fps) * self.data.sample_rate))

        out = np.zeros((2, 512), dtype=np.float32)

        # Row 0: spectrum (WebAudio AnalyserNode semantics).
        chunk = self._mono_window(center_sample, FFT_SIZE)
        mag = fft_magnitudes(chunk)
        smoothed = smooth_magnitudes(mag, prev_smoothed, self.smoothing_tau())
        out[0, :] = magnitudes_to_unit(smoothed[:512])

        # Row 1: waveform, 512 consecutive samples centred on the frame time.
        wave = self._mono_window(center_sample, 512)
        out[1, :] = np.clip(wave, -1.0, 1.0) * 0.5 + 0.5

        return out, smoothed

    def get_history_texture(self) -> np.ndarray:
        if self.history_texture is not None:
            return self.history_texture
            
        frames = self.meta.frame_count
        bins = self.meta.freq_bins
        channels = self.meta.channels
        
        tex = np.zeros((bins * channels, frames), dtype=np.float32)
        
        nperseg = 1024
        if self.fps > 0:
            hop = max(1, int(self.data.sample_rate / self.fps))
        else:
            hop = nperseg // 2
        hop = min(hop, nperseg - 1)
        noverlap = nperseg - hop
        
        for ch in range(channels):
            # FIX: use 'hann'
            f, t, Zxx = spectrogram(
                self.data.samples[:, ch], 
                fs=self.data.sample_rate, 
                window='hann', 
                nperseg=nperseg, 
                noverlap=noverlap, 
                mode='magnitude'
            )
            
            mags = Zxx[:bins, :]
            
            w = mags.shape[1]
            if w > frames:
                mags = mags[:, :frames]
            elif w < frames:
                mags = np.pad(mags, ((0,0), (0, frames-w)))
                
            row_start = ch * bins
            tex[row_start:row_start+bins, :] = mags
            
        self.history_texture = tex
        return tex
