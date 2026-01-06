# CedarToy

> **Status**: v0.3.1 (Active Development) - Web UI & Generic Parameters Added.

**CedarToy** is a headless, high-quality GLSL shader renderer designed for generative art, video production, and VR/dome content. It is compatible with Shadertoy shader syntax and extends it with advanced features like high-resolution tiling, temporal supersampling (motion blur), and VR180/Equirectangular camera mappings.

Newly added is a **Web UI** for interactive configuration and a **Generic Parameter System** for exposing shader uniforms dynamically.

## Key Features

- **Shadertoy Compatibility**: Runs standard Shadertoy code (`mainImage`, `iTime`, `iResolution`, etc.).
- **Interactive Web UI**:
  - **Real-time Configuration**: Adjust resolution, tiled rendering settings, and camera modes.
  - **Dynamic Shader Parameters**: Automatically parse and expose custom shader uniforms.
  - **Shader Browser**: Browse and select shaders from your library.
- **High-Quality Rendering**: 
  - **Tile-based rendering** for massive resolutions (4K, 8K, 16K+).
  - **Temporal Supersampling** for high-quality motion blur.
  - **Multisampling (MSAA)** support.
- **Audio Reactivity**:
  - Full support for Shadertoy's `iChannel0` (512x2 FFT + Waveform).
  - **Generic Parameters**: usage of `// @param` to tune audio reactivity per shader.
- **VR & Dome Support**:
  - **LL180 (Dome 180)**: Optimized rendering for hemispherical domes.
  - **Equirectangular**: Full 360° spherical rendering.
  - **Stereo**: Side-by-Side (SBS) and Top-Bottom (TB) stereoscopic output.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/cedarconnor/cedartoy.git
   cd cedartoy
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: Requires a working OpenGL 4.3+ context (Windows/Linux/macOS).*

## Quick Start

### 1. Launch the Web UI
The easiest way to use CedarToy is via the new Web UI.

```bash
python -m cedartoy.cli ui
```
Open **http://localhost:8080** in your browser.

- **Select a Shader**: Choose `luminescence.glsl` or others from the sidebar.
- **Configure**: Set resolution, FPS, and Camera Mode.
- **Tweak Parameters**: Adjust "Shader Parameters" (e.g., Audio Strength) directly in the UI.
- **Render**: Click "Start Render" to generate output images.

### 2. Render from CLI
Render a shader source file to a sequence of PNGs directly from the command line.

```bash
python -m cedartoy.cli render shaders/luminescence.glsl --output-dir renders/test --width 1920 --height 1080 --duration-sec 5
```

### 3. Generic Shader Parameters
You can expose custom uniforms to the UI by adding special comments to your GLSL code:

```glsl
// @param audio_strength float 2.0 0.0 5.0 "Audio Strength"
// @param pulse_speed float 2.0 0.0 10.0 "Pulse Speed"

uniform float audio_strength;
uniform float pulse_speed;
```
CedarToy parses these comments and automatically generates sliders in the Web UI.

### 4. Audio-Reactive Render
Provide an audio file to drive the animation.

```bash
python -m cedartoy.cli render shaders/luminescence.glsl --audio-path my_music.mp3 --fps 30
```
In the Web UI, simply upload an audio file in the **Audio** section.

## Documentation

Detailed documentation is available in the `docs/` directory:

- [User Guide](docs/USER_GUIDE.md) - CLI usage, configuration options, and camera modes.
- [Audio System](docs/AUDIO_SYSTEM.md) - Details on FFT, waveforms, and history textures.
