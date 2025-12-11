# CedarToy User Guide

## CLI Usage

The primary entry point is `python -m cedartoy.cli`.

### Commands

#### `render`
Renders a shader sequence.

**Arguments:**
- `shader` (positional): Path to the GLSL shader file.
- `--config`: Path to a YAML/JSON configuration file.
- `--output-dir`: Directory to save frames (default: `renders`).
- `--output-pattern`: Naming pattern (default: `frame_{frame:05d}.{ext}`).

**Overrides (can overwrite config values):**
- `--width`, `--height`: Resolution.
- `--fps`: Target framerate.
- `--duration-sec`: Duration in seconds.
- `--frame-start`, `--frame-end`: Specific frame range.
- `--audio-path`: Path to audio file for reactivity.
- `--temporal-samples`: Number of samples per frame (motion blur).
- `--shutter`: Shutter angle (0.0 to 1.0).

#### `wizard`
Runs an interactive terminal wizard to create a `cedartoy.yaml` configuration file.

#### `serve`
Starts a simple HTTP server to view the `web/` directory.
- `--port`: Port to listen on (default: 8000).

---

## Configuration (`cedartoy.yaml`)

You can define render jobs using a YAML file. This is recommended for reproducible renders.

```yaml
# Output
output_dir: "my_render"
output_pattern: "final_{frame:04d}.{ext}"
width: 3840
height: 2160
fps: 60
duration_sec: 10.0

# Quality
ss_scale: 1.0          # Spatial supersampling
temporal_samples: 8    # Motion blur samples (1 = off)
shutter: 0.5           # Shutter open time relative to frame (0.5 = 180 deg)

# Camera
camera_mode: "2d"      # "2d", "equirect", or "ll180"
camera_stereo: "none"  # "none", "sbs" (Side-by-Side), "tb" (Top-Bottom)

# Audio
audio_path: "music.wav"
audio_mode: "both"     # "shadertoy", "history", or "both"
```

---

## Camera Modes

CedarToy exposes special uniforms to handle different projection types. Your shader must utilize `iCameraMode` or the specific logic to handle these, OR rely on CedarToy's pre-calculated ray directions (if you use the provided headers/helpers).

### 1. 2D (`camera_mode: "2d"`)
Standard Shadertoy behavior. `fragCoord` is pixel coordinate.
- Use this for standard flat screens.

### 2. Equirectangular (`camera_mode: "equirect"`)
Outputs a 2:1 aspect ratio spherical map (360° x 180°).
- Ideal for full VR video.
- Requires your shader to interpret UVs as Spherical coordinates.

### 3. LL180 (`camera_mode: "ll180"`)
**"Little Planet" / Dome 180.**
- Optimizes rendering for a 180° hemisphere (front-facing).
- Uses a "Tilt-65" projection standard often used in planetariums or VR180.
- **Longitude range**: -90° to +90° (Front only).
- **Latitude range**: -90° to +90°.

---

## Stereo Rendering (VR)

CedarToy supports stereoscopic rendering for VR headsets.

- **Modes**:
  - `none`: Monoscopic (default).
  - `sbs`: **Side-by-Side**. Left eye on left half, Right eye on right half. Resolution is double the width if you keep aspect ratio? No, usually you set total `width` and `height`, and each eye gets half.
  - `tb`: **Top-Bottom**. Left eye on top, Right eye on bottom.

- **Configuration**:
  ```yaml
  camera_stereo: "sbs"  # or "tb"
  camera_ipd: 0.064     # Inter-pupillary distance in meters (default 6.4cm)
  ```

---

## Tiling

For extremely high resolutions (e.g. 8K, 16K), CedarToy uses **tiling**.
- `tiles_x` / `tiles_y` in config.
- The image is rendered in chunks to fit in GPU memory.
- Tiling is handled automatically by the engine; your shader just sees the `fragCoord` for the current pixel being rendered.
- **Note**: Tiling currently applies only to the **Final Output Pass**. Intermediate buffers (if any) are rendered at their full configured resolution (unless manually tiled, which is not auto-supported yet).

**Example Config for 8K:**
```yaml
width: 7680
height: 4320
tiles_x: 4
tiles_y: 4
```
This splits the render into 16 tiles of 1920x1080 each.

*Note: Temporal supersampling applies to each tile individually before stitching (or saving).*
