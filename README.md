# CedarToy

> **Status**: v0.3.2 (Active Development) - Production reliability pass added.

**CedarToy** is a headless, high-quality GLSL shader renderer designed for generative art, video production, and VR/dome content. It is compatible with Shadertoy shader syntax and extends it with advanced features like high-resolution tiling, temporal supersampling (motion blur), and VR180/Equirectangular camera mappings.

The Web UI supports interactive configuration, dynamic shader parameters, render job tracking, preflight diagnostics, and output artifact summaries.

## Key Features

- **Shadertoy Compatibility**: Runs standard Shadertoy code (`mainImage`, `iTime`, `iResolution`, etc.).
- **Interactive Web UI**:
  - **Real-time Configuration**: Adjust resolution, tiled rendering settings, and camera modes.
  - **Dynamic Shader Parameters**: Automatically parse and expose custom shader uniforms.
  - **Shader Browser**: Browse and select shaders from your library.
  - **Render Job Tracking**: Each UI render gets a job ID with retained progress, logs, completion state, and output artifacts.
- **Production Reliability**:
  - **Typed Configuration**: YAML/JSON configs are normalized and validated before rendering.
  - **Preflight Diagnostics**: Missing shaders, invalid output paths, and high memory estimates are reported before long renders start.
  - **Artifact Discovery**: Completed UI jobs list generated frames from the configured output directory.
- **High-Quality Rendering**: 
  - **Tile-based rendering** for massive resolutions (4K, 8K, 16K+).
  - **Temporal Supersampling** for high-quality motion blur.
  - **Multisampling (MSAA)** support.
- **Audio Reactivity**:
  - Full support for Shadertoy's `iChannel0` (512x2 FFT + Waveform).
  - **Generic Parameters**: usage of `// @param` to tune audio reactivity per shader.
  - **MusiCue Bundle Integration**: drop a structured `song.musicue.json` next to your audio file and CedarToy drives the shader from musical events (beats, sections, drum hits) instead of raw amplitude. See [§ Music-aware reactivity with MusiCue](#music-aware-reactivity-with-musicue) below.
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
  - The UI queues a render job, streams progress over WebSocket, and shows generated artifacts when the job completes.

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

### 5. Music-aware reactivity with MusiCue

By default CedarToy reads the raw frequency spectrum of your audio. That works for any sound — speech, ambient noise, anything — but it doesn't know what a "beat" or a "chorus" is, so the visuals just track loudness.

If you also use **[MusiCue](https://github.com/cedarconnor/MusiCue)**, you can hand CedarToy a structured *bundle* of the song: when each beat lands, which seconds are the chorus, where the kick drum hits, where the vocals enter. CedarToy then drives the shader from those musical events instead of raw amplitude. The whole hand-off is a single JSON file next to your audio.

**Three steps:**

1. **Generate the bundle in MusiCue** (once per song):

   ```bash
   musicue export-bundle my_music.mp3
   ```

   This writes `my_music.musicue.json` next to `my_music.mp3`. The first run is slow because MusiCue does the full analysis (stem separation, beat detection, MIDI extraction); subsequent runs reuse the cache.

2. **Render in CedarToy as normal** — no extra flags needed. CedarToy automatically looks for `<audio_stem>.musicue.json` next to the audio file and uses it:

   ```bash
   python -m cedartoy.cli render shaders/luminescence.glsl --audio-path my_music.mp3
   ```

3. **Your shader can read five extra uniforms** for more musical control. Declaring any of these in your GLSL opts the shader into bundle-aware reactivity:

   ```glsl
   uniform float iBpm;            // current BPM (e.g. 128.0)
   uniform float iBeat;           // phase 0..1 within the current beat
   uniform int   iBar;            // bar number (counts up from 0)
   uniform float iSectionEnergy;  // 0..1, how energetic the current section is
   uniform float iEnergy;         // 0..1, overall loudness right now
   ```

   Shaders that don't declare them still work — they just see the bundle-driven `iChannel0` texture and behave more musically without any code change.

**Choose how strongly the bundle drives the shader** with `--bundle-mode`:

- `auto` (default) — use the bundle if one exists, otherwise fall back to raw audio
- `raw` — ignore the bundle, use raw FFT amplitude
- `cued` — use the bundle's synthesized texture
- `blend` — mix the two with `--bundle-blend 0..1`

The same controls appear in the web UI under the **Audio & MusiCue Bundle** section.

See [docs/AUDIO_SYSTEM.md](docs/AUDIO_SYSTEM.md) for the technical reference (bin mappings, ADSR envelopes, etc.).

## Documentation

Detailed documentation is available in the `docs/` directory:

- [User Guide](docs/USER_GUIDE.md) - CLI usage, configuration options, and camera modes.
- [Audio System](docs/AUDIO_SYSTEM.md) - Details on FFT, waveforms, and history textures.
- [Developer Guide](docs/DEVELOPER.md) - Architecture notes, render job lifecycle, and reliability extension points.
