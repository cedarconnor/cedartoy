# CedarToy

> **Status**: v0.3.0 (Active Development) - Features Verified.

**CedarToy** is a headless, high-quality GLSL shader renderer designed for generative art, video production, and VR/dome content. It is compatible with Shadertoy shader syntax and extends it with advanced features like high-resolution tiling, temporal supersampling (motion blur), and VR180/Equirectangular camera mappings.

## Key Features

- **Shadertoy Compatibility**: Runs standard Shadertoy code (mainImage, iTime, iResolution, etc.).
- **High-Quality Rendering**: 
  - **Tile-based rendering** for huge resolutions (4K, 8K, 16K+).
  - **Temporal Supersampling** for high-quality motion blur (Verified).
  - **Multisampling (MSAA)** support.
- **Audio Reactivity**:
  - Full support for Shadertoy's `iChannel0` (512x2 FFT + Waveform).
  - **Extended Audio History**: A bespoke `iAudioHistoryTex` for long-term spectrograms/waterfalls.
- **VR & Dome Support**:
  - **LL180 (Tilt-65)**: Optimized VR180 rendering for dome/hemisphere content.
  - **Equirectangular**: Full 360° spherical rendering.
  - **Stereo**: Side-by-Side (SBS) and Top-Bottom (TB) stereoscopic output (Verified).
- **Python CLI**: Scriptable, config-driven workflow.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/cedartoy.git
   cd cedartoy
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: Requires a working OpenGL 4.3+ context (Windows/Linux/macOS).*

## Quick Start

### 1. Render a single shader
Render a shader source file to a sequence of PNGs.

```bash
python -m cedartoy.cli render shaders/myshader.glsl --output-dir renders/test --width 1920 --height 1080 --duration-sec 5
```

### 2. Audio-Reactive Render
Provide an audio file to drive the animation.

```bash
python -m cedartoy.cli render shaders/audio_viz.glsl --audio-path my_music.wav --fps 60
```

### 3. Use the Configuration Wizard
Interactively generate a configuration file (`cedartoy.yaml`).

```bash
python -m cedartoy.cli wizard
```

Then run with the config:
```bash
python -m cedartoy.cli render --config cedartoy.yaml
```

### 4. Web Preview (Experimental)
Start a local web server to preview the current build/shader (note: this is a static preview server for now).

```bash
python -m cedartoy.cli serve --port 8080
```

## Documentation

Detailed documentation is available in the `docs/` directory:

- [User Guide](docs/USER_GUIDE.md) - CLI usage, configuration options, and camera modes.
- [Audio System](docs/AUDIO_SYSTEM.md) - Details on FFT, waveforms, and history textures.
