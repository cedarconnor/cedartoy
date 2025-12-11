# CedarToy Audio System

CedarToy provides robust audio reactivity features compatible with existing Shadertoy code while offering extended capabilities for advanced visualization.

## 1. Shadertoy Compatibility (`iChannel0`)

When an audio path is provided, CedarToy automatically binds a **512x2** texture to `iChannel0` (or the configured channel).

### Texture Layout
- **Resolution**: 512 x 2 pixels.
- **Row 0 (`y=0.25`)**: **Frequency Domain (FFT)**.
  - Contains normalized FFT magnitudes (0.0 to 1.0).
  - 512 bins covering the frequency spectrum (0 to Nyquist).
- **Row 1 (`y=0.75`)**: **Time Domain (Waveform)**.
  - Contains raw PCM waveform data.
  - Normalized to [0.0, 1.0], where 0.5 is zero amplitude.

### Usage in GLSL
```glsl
// Sample FFT (Bass is at x=0.0, Treble at x=1.0)
float fft = texture(iChannel0, vec2(uv.x, 0.25)).r;

// Sample Waveform
float wave = texture(iChannel0, vec2(uv.x, 0.75)).r;
```

---

## 2. Extended Audio History (`iAudioHistoryTex`)

For visualizations requiring time-history (like spectrograms or waterfalls), CedarToy provides a separate, high-resolution texture.

### Uniforms
- `uniform sampler2D iAudioHistoryTex;`
- `uniform vec3 iAudioHistoryResolution;` (x=Total Frames, y=Total Bins * Channels, z=0)

### Texture Layout
- **Width**: Corresponds to the total number of video frames (Time).
  - `x=0.0` is the start of the audio/video.
  - `x=1.0` is the end.
- **Height**: Stacked frequency bins for stereo channels.
  - `Total Height = 512 * 2 = 1024` pixels.
  - **Rows 0-511**: Left Channel FFT.
  - **Rows 512-1023**: Right Channel FFT.

### Usage in GLSL
You can sample specific moments in time or create scrolling spectrograms.

```glsl
// Helper to sample Left/Right FFT at a specific normalized time and frequency
vec2 sampleAudioHistoryLR(float tNorm, float freqNorm) {
    float frames = iAudioHistoryResolution.x;
    float bins2  = iAudioHistoryResolution.y; // 1024
    float bins   = bins2 * 0.5;               // 512

    // Map normalized time 0..1 to specific frame column
    // (Simple linear sampling, use logic to snap to pixel centers if needed)
    float x = clamp(tNorm, 0.0, 1.0);

    // Calculate Y coords for L and R
    // freqNorm 0..1 maps to 0..512 (L) and 512..1024 (R)
    float yL = clamp(freqNorm, 0.0, 1.0) * (bins / bins2);
    float yR = 0.5 + clamp(freqNorm, 0.0, 1.0) * (bins / bins2);

    float L = texture(iAudioHistoryTex, vec2(x, yL)).r;
    float R = texture(iAudioHistoryTex, vec2(x, yR)).r;
    return vec2(L, R);
}
```

## 3. Pre-Processing Details
- **Engine**: `scipy.signal.spectrogram` and `numpy.fft`.
- **Windowing**: Hann window.
- **Sync**: Audio analysis is strictly synchronized to the video framerate (FPS).
- **Channels**: Automatically mixed to Mono for `iChannel0` (Shadertoy compat), but kept Stereo for `iAudioHistoryTex`.
