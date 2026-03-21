import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple
import soundfile as sf
from scipy.signal import spectrogram

from .types import AudioMeta

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
        """Pre-compute all per-frame FFT textures for faster rendering."""
        if self.data is None:
            return
        frames = self.meta.frame_count
        if frames <= 0:
            return
        self._precomputed_textures = {}
        for f in range(frames):
            self._precomputed_textures[f] = self._compute_shadertoy_texture(f)

    def get_shadertoy_texture(self, frame_index: int) -> np.ndarray:
        """Return cached precomputed texture if available, otherwise compute on-the-fly."""
        if self.data is None:
            return np.zeros((2, 512), dtype=np.float32)

        if hasattr(self, '_precomputed_textures') and frame_index in self._precomputed_textures:
            return self._precomputed_textures[frame_index]

        return self._compute_shadertoy_texture(frame_index)

    def _compute_shadertoy_texture(self, frame_index: int) -> np.ndarray:
        """Compute the 2x512 FFT+waveform texture for a single frame."""
        center_sample = int((frame_index / self.fps) * self.data.sample_rate)
        half_window = 1024 // 2

        start = center_sample - half_window
        end = center_sample + half_window

        pad_pre = 0
        pad_post = 0
        if start < 0:
            pad_pre = -start
            start = 0
        if end > len(self.data.samples):
            pad_post = end - len(self.data.samples)
            end = len(self.data.samples)

        if self.data.samples.shape[1] > 1:
            chunk = np.mean(self.data.samples[start:end, :], axis=1)
        else:
            chunk = self.data.samples[start:end, 0]

        if pad_pre > 0 or pad_post > 0:
            chunk = np.pad(chunk, (pad_pre, pad_post), mode='constant')

        window = np.hanning(len(chunk))
        fft_res = np.fft.rfft(chunk * window)
        fft_mag = np.abs(fft_res)

        waveform = np.clip(chunk, -1.0, 1.0)
        waveform = (waveform * 0.5) + 0.5

        out = np.zeros((2, 512), dtype=np.float32)

        fft_bins = fft_mag[:512]
        fft_bins = np.log1p(fft_bins)
        max_val = float(np.max(fft_bins)) if fft_bins.size else 0.0
        if max_val > 0:
            fft_bins = fft_bins / max_val
        out[0, :] = np.clip(fft_bins, 0.0, 1.0)

        out[1, :] = waveform[::2][:512]

        return out

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
