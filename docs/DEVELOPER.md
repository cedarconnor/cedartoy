# Developer Guide

## Architecture Overview

CedarToy is organized as a modular Python package:

- **`cedartoy.cli`**: Entry point. Parses args and initializes `Renderer`.
- **`cedartoy.config`**: Handles YAML loading and option merging.
- **`cedartoy.render`**: The core engine.
  - Manages `moderngl` Context.
  - Handles the render loop, temporal sampling (`acc_buffer`), stereo views, and tiling.
- **`cedartoy.shader`**: Responsible for loading GLSL files and injecting the "Header" (uniforms/helpers) and "Footer" (main wrapper).
- **`cedartoy.audio`**: Handles audio file loading, FFT computation, and texture generation.

## Implementation Details

### Tiling Strategy
Tiling is implemented in `Renderer.render_frame`.
- Intermediate passes are rendered fully (un-tiled) to ensure global context is available.
- The **Final Pass** is split into `tiles_x * tiles_y` chunks.
- A smaller FBO is allocated for the tile size.
- `iTileOffset` is passed to the shader to adjust `gl_FragCoord`.
- Results are stitched into a CPU-side numpy array.

### Stereo Rendering
Stereo is handled via `_render_view`.
- The renderer calls `_render_view` twice (Left/Right) if stereo is enabled.
- Camera position is offset by `± IPD/2` along the camera's Right vector.
- Views are stitched (SBS or TB) before saving.


The CLI supports Shadertoy‑style multipass graphs via `multipass.buffers` in YAML/JSON.

- If `multipass.execution_order` is omitted, CedarToy topologically sorts buffers based on `channels` dependencies.
- Exactly one buffer must set `outputs_to_screen: true`, and it must be last in the execution order.
- Feedback/self‑references are not supported yet; adding ping‑pong textures is the next step for true Shadertoy feedback buffers.
- The renderer binds `iChannel0..3` per buffer using `BufferConfig.channels`, supporting buffer‑to‑buffer inputs, `"audio"`, `"history"`, and `"file:<path>"` image textures.

## Adding New Features

### Adding a new Uniform
1. Add the uniform declaration to `shaders/common/header.glsl`.
2. Add the value to the `uni` dictionary in `cedartoy.render.Renderer._render_pass`.

### Supporting New Output Formats
1. Check `imageio` capabilities.
2. Update `cedartoy.options_schema` to allow the format in the wizard.
3. Update `cedartoy.render` to handle specific bit-depth conversions if `imageio` needs hints (e.g. for EXR).
