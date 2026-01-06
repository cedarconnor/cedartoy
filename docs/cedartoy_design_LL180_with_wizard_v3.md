
# Headless Shadertoy Renderer – Design Document  
*(LL180 Tilt-65 Camera, Audio Reactivity, Multipass, Tiling, Wizard UI, v3)*

This version incorporates the compatibility / correctness notes:

- **Audio**: true Shadertoy-compatible `iChannel0` (512×2 FFT+waveform) **plus** a separate extended audio-history texture.
- **LL180**: longitude now covers **front hemisphere only** (±90°) to avoid wasting time on unseen back geometry.
- **Temporal sampling**: jitter is deterministic per frame / sample (repeatable renders).
- **Per-buffer bit depth** instead of one global bit depth.
- **EXR gating**: “exr” is only exposed if `imageio`/EXR is actually available.

---

## 1. Package Layout (unchanged high level)

- `cedartoy/`
  - `render.py` – rendering engine (moderngl, tiling, multipass, cameras).
  - `shader.py` – shader loading, code generation, multipass DAG.
  - `audio.py` – audio preprocessing → FFT, waveform, history textures.
  - `config.py` – YAML/JSON config + CLI argument merging.
  - `naming.py` – Nuke/AE–friendly output naming.
  - `cli.py` – CLI and subcommands.
  - `options_schema.py` – declarative schema for options (+ validation).
  - `ui.py` – terminal wizard built from the schema.
  - `webserver.py` – (optional) tiny HTTP server + REST endpoints.
- `shaders/`
  - `common/header.glsl`
  - `…user shaders…`
- `audio/`, `audio_data/`
- `web/`
  - `index.html`, `preview.js`, etc.

---

## 2. Core Data Model (updated)

### 2.1. AudioMeta

```python
from dataclasses import dataclass

@dataclass
class AudioMeta:
    duration_sec: float      # seconds
    sample_rate: int         # Hz
    frame_count: int         # frames at audio_fps
    freq_bins: int           # STFT frequency bins (per channel)
    channels: int            # usually 2
    audio_fps: float         # target fps used during preprocessing
```

### 2.2. Multipass Graph with per-buffer format

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

@dataclass
class BufferConfig:
    name: str                        # "Image", "A", "B", ...
    shader: Path                     # GLSL file for this pass
    outputs_to_screen: bool          # True for final image pass
    channels: Dict[int, str]         # iChannel index -> source name ("A", "B", "audio", "file:tex.png", ...)
    output_format: Optional[str] = None  # "png", "exr" or None → use job default
    bit_depth: Optional[str] = None      # "8", "16f", "32f" or None → use job default

@dataclass
class MultipassGraphConfig:
    buffers: Dict[str, BufferConfig]     # keyed by buffer name
    execution_order: List[str]           # topologically sorted buffer names
```

Per-buffer precision example:

- Buffer `A` (position/velocity): `bit_depth="32f"`
- Final `Image` pass: `bit_depth="16f"` / `output_format="exr"`

### 2.3. RenderJob (global defaults)

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Optional, Any

@dataclass
class RenderJob:
    # core
    shader_main: Path
    shader_buffers: Dict[str, Path]
    output_dir: Path
    output_pattern: str
    width: int
    height: int
    fps: float
    frame_start: int
    frame_end: int

    # tiling
    tiles_x: int
    tiles_y: int

    # quality
    ss_scale: float
    temporal_samples: int
    shutter: float
    default_output_format: str        # e.g. "exr", used if BufferConfig.output_format is None
    default_bit_depth: str            # e.g. "16f", used if BufferConfig.bit_depth is None

    # Shadertoy compat
    iMouse: Tuple[float, float, float, float]
    iChannel_paths: Dict[int, Path]
    defines: Dict[str, Optional[str]]

    # audio
    audio_path: Optional[Path]
    audio_fps: float
    audio_meta: Optional[AudioMeta]

    # camera / VR
    camera_mode: str
    camera_stereo: str
    camera_fov: float
    camera_params: Dict[str, Any]      # {"tilt_deg": 65.0, "ipd": 0.064, ...}

    # multipass
    multipass_graph: MultipassGraphConfig
```

---

## 3. Options Schema / Wizard (incremental tweaks)

Same as previous version, but:

- `bit_depth` / `output_format` are now **defaults**.  
- Wizard can later grow a “per-buffer advanced settings” mode, but v1 only exposes global defaults.
- We add a **bit-depth help note**: “Per-buffer overrides live in the multipass config; this is a default.”

EXR gating is handled in the wizard (see §10.3).

---

## 4. Shader Interface & LL180 Fix

### 4.1. Uniforms (unchanged overall shape)

User shaders still implement:

```glsl
void mainImage(out vec4 fragColor, in vec2 fragCoord);
```

And see Shadertoy-style + extended uniforms:
- `iResolution`, `iTime`, `iFrame`, `iMouse`
- `iChannel0..3`, `iChannelResolution`
- `iDuration`, `iPassIndex`
- `iCameraMode`, `iCameraStereo`, `iCameraPos`, `iCameraDir`, `iCameraUp`, `iCameraFov`, `iCameraTiltDeg`, `iCameraIPD`
- `sampler2D iAudioHistoryTex`, `vec3 iAudioHistoryResolution` (new; see §5)

### 4.2. LL180: front hemisphere only

**Goal**: LL180 (VR180/dome) should render *only* the front hemisphere, i.e. longitude range `[-90°, +90°]`, not a full 360° sphere.

Updated LL180 mapping:

```glsl
const float PI = 3.141592653589793238;

mat3 buildCameraBasis(vec3 camDir, vec3 camUp) {
    vec3 f = normalize(camDir);
    vec3 r = normalize(cross(camUp, f));
    vec3 u = cross(f, r);
    return mat3(r, u, f);
}

// LL180: uv in [0,1]^2 → front hemisphere
//  uv.x: -90° .. +90°  (lon)
//  uv.y: -90° .. +90°  (lat)
vec3 cameraDirLL180(vec2 uv, float tiltDeg, mat3 camBasis) {
    float lon = (uv.x * 2.0 - 1.0) * (0.5 * PI);  // -π/2 .. π/2
    float lat = (uv.y * 2.0 - 1.0) * (0.5 * PI);  // -π/2 .. π/2

    vec3 dirLocal;
    dirLocal.x = cos(lat) * sin(lon);
    dirLocal.y = sin(lat);
    dirLocal.z = cos(lat) * cos(lon);

    float tiltRad = radians(tiltDeg);
    float c = cos(tiltRad);
    float s = sin(tiltRad);
    mat3 tiltX = mat3(
        1.0, 0.0, 0.0,
        0.0,  c, -s,
        0.0,  s,  c
    );

    dirLocal = tiltX * dirLocal;
    return normalize(camBasis * dirLocal);
}
```

This keeps the entire 2D image dedicated to the front 180×180° dome / VR180 region, without rendering the rear hemisphere.

If you want full-sphere content, use the standard `equirect` mode.

---

## 5. Audio: Shadertoy Compatibility *and* History

### 5.1. Shadertoy-compatible audio (`iChannel0`)

For true Shadertoy compatibility, we provide a **512×2** audio texture bound to one of the standard channels (usually `iChannel0`) with the semantics:

- Resolution: `iChannelResolution[n] = vec3(512.0, 2.0, 1.0)`
- Row 0 (`y≈0.25`): **Frequency domain** (FFT magnitudes).
- Row 1 (`y≈0.75`): **Waveform** (PCM samples).

At runtime for frame `f`:

- We pick a STFT window centered near `time = f / fps` (or use a real-time-style sliding window).
- Compute FFT for that window for each channel, map to 512 frequency bins.
- Fill row 0 with FFT magnitudes, row 1 with normalized PCM sample values for the same window.

This means that existing Shadertoy code like:

```glsl
float spectrum = texture(iChannel0, vec2(x, 0.25)).r;
float waveform = texture(iChannel0, vec2(x, 0.75)).r;
```

behaves as expected.

> **Strict rule:** If `audio_path` is provided and the user wants “Shadertoy audio mode”, we reserve **one** `iChannelN` (configurable) for **exact 512×2 compatibility**.

### 5.2. Extended audio history (`iAudioHistoryTex`)

For more advanced audio-reactive work (e.g., long-term patterns), we use a **separate texture**:

- Uniform: `sampler2D iAudioHistoryTex;`
- Resolution: `vec3 iAudioHistoryResolution` (`W = time frames, H = freq_bins * channels`).

Layout (unchanged from earlier design, just renamed):

- `H = freq_bins * channels` (`channels=2` → `freq_bins * 2`).
- Rows `0 … freq_bins-1`: left-channel FFT history.
- Rows `freq_bins … 2*freq_bins-1`: right-channel FFT history.
- `x` axis: time (0..1 → earliest..latest or vice versa).

GLSL helper (updated names):

```glsl
vec2 sampleAudioHistoryLR(float tNorm, float freqNorm) {
    float frames = iAudioHistoryResolution.x;
    float bins2  = iAudioHistoryResolution.y;
    float bins   = bins2 * 0.5;

    float x = clamp(tNorm, 0.0, 1.0);
    float frameIndex = x * (frames - 1.0);
    x = frameIndex / max(frames - 1.0, 1.0);

    float yL = clamp(freqNorm, 0.0, 1.0) * (bins / bins2);
    float yR = 0.5 + clamp(freqNorm, 0.0, 1.0) * (bins / bins2);

    float L = texture(iAudioHistoryTex, vec2(x, yL)).r;
    float R = texture(iAudioHistoryTex, vec2(x, yR)).r;
    return vec2(L, R);
}
```

Band energy helpers (`getBassEnergy`, etc.) can be defined in terms of either the Shadertoy 512×2 (`iChannel0`) or the history texture; implementation choice is documented so shader authors know which one they’re using.

### 5.3. Modes / configuration

- Config option: `audio_mode: "shadertoy"` or `"history"` or `"both"`.
- `"shadertoy"`: only 512×2 `iChannelN` provided.
- `"history"`: only `iAudioHistoryTex` provided.
- `"both"` (default): both are available; legacy Shadertoy code works, and new code can use the history uniform.

---

## 6. Tiling + Multipass (unchanged conceptually)

Same as previous version, with the reminder that:

- Each buffer pass keeps a **full-res texture**, updated tile-by-tile.
- When sampling another pass (`iChannelN`), shaders use `fragCoord / iResolution.xy` so tiling is invisible.
- Temporal buffer feedback uses **per-frame ping-pong textures** optionally.

Per-buffer bit depth (`BufferConfig.bit_depth`) dictates the precision used when writing that pass to disk (or possibly when allocating its storage, depending on implementation constraints).

---

## 7. Temporal Sampling – Deterministic Jitter

We want motion blur with non-uniform sample times **and** reproducible frames. So:

- Jitter is derived **only** from `(frame_index, sample_index)` via a small integer hash.
- No calls to `np.random` in the render loop.

Example:

```python
def _hash_u32(x: int) -> int:
    # Simple integer hash (splitmix-style)
    x = (x + 0x9E3779B9) & 0xFFFFFFFF
    x = (x ^ (x >> 16)) * 0x7FEB352D & 0xFFFFFFFF
    x = (x ^ (x >> 15)) * 0x846CA68B & 0xFFFFFFFF
    x = x ^ (x >> 16)
    return x & 0xFFFFFFFF

def temporal_offsets(num_samples: int, frame_index: int):
    offsets = []
    for s in range(num_samples):
        base = (s + 0.5) / num_samples   # stratified
        h = _hash_u32(frame_index * 73856093 + s * 19349663)
        # map to [-0.5, 0.5] / num_samples
        jitter = ((h / 2**32) - 0.5) / num_samples
        offsets.append(max(0.0, min(1.0, base + jitter)))
    return offsets
```

Render loop uses:

```python
offsets = temporal_offsets(job.temporal_samples, f)
for o in offsets:
    t = base_time + (o - 0.5) * job.shutter
    ...
```

Re-rendering frame 105 with the same settings yields identical sample times and identical images (assuming deterministic GPU path).

---

## 8. Stereo IPD (unchanged, but clarified)

- `camera_params["ipd"]` → `iCameraIPD` uniform.
- Eye positions for left/right:

```python
cam_basis = build_basis(camDir, camUp)   # same math as GLSL
cam_right = cam_basis[:, 0]
eye_offset = cam_right * (ipd * 0.5)

left_eye_pos  = cam_pos - eye_offset
right_eye_pos = cam_pos + eye_offset
```

Renderer chooses layout (`top_bottom`, `side_by_side`, etc.) and calls the same multipass graph twice (once per eye) with different camera uniforms.

---

## 9. Web Preview & Cache Busting (unchanged)

Shaders are loaded with `?v=<Date.now()>` in the WebGL preview to avoid stale caching. A “Reload Shaders” button simply re-runs the fetch/compile sequence.

For audio, the preview can approximate Shadertoy’s 512×2 behaviour (for compatibility testing) and optionally expose a smaller history texture to mimic the offline pipeline.

---

## 10. Output & EXR Dependencies (clarified)

### 10.1. Dependency policy

- **PNG**: Requires either `Pillow` or `imageio`.  
- **EXR**: Requires **`imageio` with EXR support** (e.g., `imageio[ffmpeg]` or `imageio-exr` depending on platform).

We **do not** assume Pillow can handle EXR.

### 10.2. Gating EXR in code

At import time:

```python
def _check_exr_available() -> bool:
    try:
        import imageio.v3 as iio  # or imageio
        # optional: try a dummy write to an in-memory file
        return True
    except Exception:
        return False

EXR_AVAILABLE = _check_exr_available()
```

- If `EXR_AVAILABLE` is `False`, then:
  - The wizard does **not offer** `"exr"` as an `output_format` choice.
  - If a config file explicitly requests `output_format: exr`, the renderer raises a clear error.

### 10.3. Wizard integration

In `options_schema.py`, `output_format` choices are built at runtime:

```python
available_formats = ["png"]
if EXR_AVAILABLE:
    available_formats.append("exr")

OPTIONS.append(
    Option(
        "default_output_format", "Default output format", "choice", "png",
        choices=available_formats
    )
)
```

This guarantees that users can’t accidentally choose EXR in the wizard if the environment doesn’t support it.

---

This v3 doc resolves the specific issues you flagged:

1. **Shadertoy audio compatibility**: 512×2 `iChannel0` format preserved; custom audio history moved to a separate uniform.
2. **LL180 mapping**: updated to ±90° longitude, so only the front hemisphere is rendered.
3. **Temporal sampling**: jitter is now deterministic per frame via an integer hash.
4. **Bit depth**: moved to `BufferConfig` with global defaults in `RenderJob`.
5. **Dependencies**: EXR support is gated on `imageio` availability; wizard respects this.

You can now treat this as the “spec” for your first implementation pass without running into those incompatibilities later.

