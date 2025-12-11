import numpy as np
import soundfile as sf

# Generate 5 seconds of audio
sr = 44100
t = np.linspace(0, 5, 5 * sr, endpoint=False)
# Sweep from 200Hz to 1000Hz
freq = np.linspace(200, 1000, len(t))
phase = 2 * np.pi * np.cumsum(freq) / sr
audio = 0.5 * np.sin(phase)

# Stereo: Left = Sweep, Right = Constant 400Hz
right = 0.5 * np.sin(2 * np.pi * 400 * t)
data = np.stack([audio, right], axis=1)

sf.write('audio_data/test_sweep.wav', data, sr)
print("Created audio_data/test_sweep.wav")
