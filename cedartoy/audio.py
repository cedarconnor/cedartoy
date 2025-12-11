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
        pass

    def get_shadertoy_texture(self, frame_index: int) -> np.ndarray:
        if self.data is None:
            return np.zeros((2, 512), dtype=np.uint8)
            
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
            
        chunk = self.data.samples[start:end, 0] 
        if self.data.samples.shape[1] > 1:
            chunk = np.mean(self.data.samples[start:end, :], axis=1)
            
        if pad_pre > 0 or pad_post > 0:
            chunk = np.pad(chunk, (pad_pre, pad_post), mode='constant')
            
        # FIX: use 'hann'
        window = np.hanning(len(chunk))
        fft_res = np.fft.rfft(chunk * window)
        fft_mag = np.abs(fft_res)
        
        waveform = chunk 
        waveform = (waveform * 0.5) + 0.5
        
        out = np.zeros((2, 512), dtype=np.float32)
        
        out[0, :] = fft_mag[:512] 
        out[0, :] /= 512.0 
        
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
        hop = int(self.data.sample_rate / self.fps)
        
        for ch in range(channels):
            # FIX: use 'hann'
            f, t, Zxx = spectrogram(
                self.data.samples[:, ch], 
                fs=self.data.sample_rate, 
                window='hann', 
                nperseg=nperseg, 
                noverlap=nperseg-hop, 
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