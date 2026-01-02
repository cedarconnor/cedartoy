import moderngl
import numpy as np
import os
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import math
from dataclasses import asdict
from datetime import datetime

from .types import RenderJob, BufferConfig, MultipassGraphConfig
from .shader import load_shader_from_file
from .audio import AudioProcessor
from .naming import resolve_output_path
from .options_schema import EXR_AVAILABLE

try:
    import imageio.v3 as iio
except ImportError:
    iio = None

try:
    from scipy.ndimage import zoom as nd_zoom
except Exception:
    nd_zoom = None

# --- Progress Logging for UI ---
def log_progress(frame, total, elapsed_sec):
    """Output structured progress for UI"""
    progress = {
        "frame": frame,
        "total": total,
        "elapsed_sec": round(elapsed_sec, 2)
    }
    print(f"[PROGRESS] {json.dumps(progress)}", file=sys.stderr, flush=True)

def log_info(message):
    """Output info log"""
    print(f"[LOG] INFO: {message}", file=sys.stderr, flush=True)

def log_error(message, details=None):
    """Output error log"""
    error_data = {"message": message}
    if details:
        error_data["details"] = details
    print(f"[ERROR] {json.dumps(error_data)}", file=sys.stderr, flush=True)

def log_complete(output_dir, frames):
    """Output completion message"""
    complete_data = {"output_dir": str(output_dir), "frames": frames}
    print(f"[COMPLETE] {json.dumps(complete_data)}", file=sys.stderr, flush=True)

# --- Temporal Sampling ---
def _hash_u32(x: int) -> int:
    x = (x + 0x9E3779B9) & 0xFFFFFFFF
    x = (x ^ (x >> 16)) * 0x7FEB352D & 0xFFFFFFFF
    x = (x ^ (x >> 15)) * 0x846CA68B & 0xFFFFFFFF
    x = x ^ (x >> 16)
    return x & 0xFFFFFFFF

def temporal_offsets(num_samples: int, frame_index: int) -> List[float]:
    offsets = []
    for s in range(num_samples):
        base = (s + 0.5) / num_samples
        h = _hash_u32(frame_index * 73856093 + s * 19349663)
        jitter = ((h / 2**32) - 0.5) / num_samples
        offsets.append(max(0.0, min(1.0, base + jitter)))
    return offsets

# --- Halton Sequence for Subpixel Jitter ---
def halton(index: int, base: int) -> float:
    """Generate element of Halton sequence (low-discrepancy sequence for AA)"""
    result = 0.0
    f = 1.0
    i = index
    while i > 0:
        f = f / base
        result = result + f * (i % base)
        i = i // base
    return result

def halton_2d(index: int) -> Tuple[float, float]:
    """Generate 2D Halton point using bases 2 and 3"""
    return (halton(index + 1, 2), halton(index + 1, 3))

def subpixel_jitter(sample_index: int, frame_index: int, num_samples: int) -> Tuple[float, float]:
    """
    Generate subpixel jitter offset for antialiasing.
    Returns offset in range [-0.5, 0.5] for both x and y.
    Uses Halton sequence for low-discrepancy sampling.
    """
    # Use combined index for deterministic but varied samples per frame
    combined_index = frame_index * num_samples + sample_index
    hx, hy = halton_2d(combined_index)
    # Map from [0,1] to [-0.5, 0.5] for centered jitter
    return (hx - 0.5, hy - 0.5)

def build_basis(forward: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = forward / np.linalg.norm(forward)
    r = np.cross(up, f)
    r = r / np.linalg.norm(r)
    u = np.cross(f, r)
    return np.array([r, u, f])

class Renderer:
    def __init__(self, job: RenderJob):
        self.job = job
        self.output_width = job.width
        self.output_height = job.height

        # Validate dimensions
        if self.output_width <= 0 or self.output_height <= 0:
            raise ValueError(f"Invalid dimensions: {self.output_width}x{self.output_height}")

        scale = float(job.ss_scale) if job.ss_scale else 1.0
        if scale <= 0:
            scale = 1.0
        self.ss_scale = scale
        self.internal_width = max(1, int(round(self.output_width * scale)))
        self.internal_height = max(1, int(round(self.output_height * scale)))

        print(f"[LOG] Renderer init: output={self.output_width}x{self.output_height}, internal={self.internal_width}x{self.internal_height}, ss_scale={scale}")
        print(f"[LOG] Job params: tiles={job.tiles_x}x{job.tiles_y}, temporal_samples={job.temporal_samples}, bit_depth={job.default_bit_depth}")

        self.ctx = moderngl.create_context(standalone=True)

        # Feedback buffers (self-referencing channels) use ping-pong textures.
        self.feedback_pairs: Dict[str, Dict[str, Any]] = {}
        for name, buf in job.multipass_graph.buffers.items():
            if buf.outputs_to_screen:
                continue
            if any(str(src) == name for src in (buf.channels or {}).values()):
                self.feedback_pairs[name] = {"index": 0}

        if self.feedback_pairs and job.camera_stereo != "none":
            raise ValueError("Feedback buffers are not supported with stereo rendering yet.")
        
        # Audio
        self.audio = None
        self.history_tex = None
        if job.audio_path:
            self.audio = AudioProcessor(job.audio_path, job.audio_fps)
            if job.audio_mode in ("history", "both"):
                history_tex_data = self.audio.get_history_texture()
                self.history_tex = self.ctx.texture(
                    (history_tex_data.shape[1], history_tex_data.shape[0]),
                    1,
                    data=history_tex_data.tobytes(),
                    dtype='f4'
                )

        self.programs = {} 
        self.textures = {} 
        self.fbos = {}     
        self.vaos = {}
        self.file_textures: Dict[Path, moderngl.Texture] = {}
        # Store tile FBOs separately
        self.tile_fbos = {} # buf_name -> FBO (if using tiling)
        
        self._init_geometry()
        self._init_buffers()

    def _init_geometry(self):
        vertices = np.array([
            -1.0, -1.0, 0.0, 0.0,
             1.0, -1.0, 1.0, 0.0,
            -1.0,  1.0, 0.0, 1.0,
             1.0,  1.0, 1.0, 1.0,
        ], dtype='f4')
        
        self.vbo = self.ctx.buffer(vertices.tobytes())
    
    def _init_buffers(self):
        # Calculate tile size for final output
        # We only tile the final pass for now.
        tiles_x = self.job.tiles_x
        tiles_y = self.job.tiles_y
        
        self.tile_w = math.ceil(self.internal_width / tiles_x)
        self.tile_h = math.ceil(self.internal_height / tiles_y)
        
        for name, buf in self.job.multipass_graph.buffers.items():
            # 1. Compile Shader
            defines = self.job.defines.copy()
            src = load_shader_from_file(buf.shader, defines)
            try:
                prog = self.ctx.program(
                    vertex_shader="""
                    #version 430
                    in vec2 in_vert;
                    in vec2 in_uv;
                    out vec2 uv;
                    void main() {
                        gl_Position = vec4(in_vert, 0.0, 1.0);
                        uv = in_uv;
                    }
                    """,
                    fragment_shader=src
                )
            except Exception as e:
                print(f"Error compiling shader for buffer {name}:")
                raise e
            
            self.programs[name] = prog

            # Cache a fullscreen quad VAO per program.
            fmt_parts = []
            attrs = []
            if 'in_vert' in prog:
                fmt_parts.append('2f')
                attrs.append('in_vert')
            else:
                fmt_parts.append('8x')
            if 'in_uv' in prog:
                fmt_parts.append('2f')
                attrs.append('in_uv')
            else:
                fmt_parts.append('8x')
            # print(f"DEBUG: Program members: {list(prog)}")
            fmt = ' '.join(fmt_parts)
            # print(f"DEBUG: Buffer {name} - Format: {fmt}, Attrs: {attrs}")
            self.vaos[name] = self.ctx.vertex_array(prog, [(self.vbo, fmt, *attrs)])
            
            
            # 2. Allocate Texture
            # Internal rendering uses float textures (16f or 32f). 8-bit output is converted on disk write.
            internal_bit_depth = buf.bit_depth or self.job.default_bit_depth
            # Use float32 for 32f, float16 for 16f, and float32 for 8-bit (convert on output)
            if internal_bit_depth == "32f":
                dtype = 'f4'
            elif internal_bit_depth == "16f":
                dtype = 'f2'
            else:
                # For 8-bit output, still use float32 internally for quality
                dtype = 'f4'
            
            # If this is the output pass AND we are tiling, we allocate a Small texture for tile rendering
            # BUT we also allocate the Full texture? 
            # If we stitch on CPU, we don't need full GPU texture for the output pass.
            # But what if another pass reads it? (Feedback).
            # If feedback is needed, we need full texture.
            # Assuming output pass is NOT read by others for now (DAG terminal).
            
            # We will always allocate full texture for intermediate buffers.
            # For screen output buffer, if tiling, we allocate TILE size.
            
            width = self.internal_width
            height = self.internal_height
            
            if buf.outputs_to_screen and (tiles_x > 1 or tiles_y > 1):
                width = self.tile_w
                height = self.tile_h
                print(f"Allocating TILE buffer for {name}: {width}x{height}")

            print(f"[LOG] Creating texture for '{name}': {width}x{height}, dtype={dtype}, bit_depth={internal_bit_depth}")

            if name in self.feedback_pairs:
                # Ping-pong pair at full internal res (feedback buffers are never tiled).
                try:
                    tex_a = self.ctx.texture((self.internal_width, self.internal_height), 4, dtype=dtype)
                    tex_b = self.ctx.texture((self.internal_width, self.internal_height), 4, dtype=dtype)
                    fbo_a = self.ctx.framebuffer(color_attachments=[tex_a])
                    fbo_b = self.ctx.framebuffer(color_attachments=[tex_b])
                except Exception as e:
                    print(f"[ERROR] Failed to create feedback buffer for '{name}': {e}")
                    raise
                fbo_a.use(); self.ctx.clear()
                fbo_b.use(); self.ctx.clear()
                self.feedback_pairs[name].update({"textures": [tex_a, tex_b], "fbos": [fbo_a, fbo_b]})
                # Default to A as current write target; will be set per-frame in _begin_frame.
                self.textures[name] = tex_a
                self.fbos[name] = fbo_a
            else:
                try:
                    tex = self.ctx.texture((width, height), 4, dtype=dtype)
                    self.textures[name] = tex
                    fbo = self.ctx.framebuffer(color_attachments=[tex])
                    self.fbos[name] = fbo
                except Exception as e:
                    print(f"[ERROR] Failed to create texture/FBO for '{name}' ({width}x{height}, dtype={dtype}): {e}")
                    raise

    def _begin_frame(self):
        # Establish read/write targets for feedback buffers and expose current write texture.
        for name, pair in self.feedback_pairs.items():
            idx = int(pair["index"])
            prev_tex = pair["textures"][idx]
            write_tex = pair["textures"][1 - idx]
            write_fbo = pair["fbos"][1 - idx]
            pair["prev_tex"] = prev_tex
            pair["write_tex"] = write_tex
            pair["write_fbo"] = write_fbo
            self.textures[name] = write_tex
            self.fbos[name] = write_fbo

    def _end_frame(self):
        for pair in self.feedback_pairs.values():
            pair["index"] = 1 - int(pair["index"])

    def _bind_uniforms(self, prog, uniforms: Dict[str, Any]):
        for k, v in uniforms.items():
            if k in prog:
                try:
                    prog[k].value = v
                except Exception as e:
                    pass

    def _get_file_texture(self, path: Path) -> moderngl.Texture:
        if path in self.file_textures:
            return self.file_textures[path]
        if iio is None:
            raise RuntimeError("imageio is required to load file textures.")
        if not path.exists():
            raise FileNotFoundError(f"Texture file not found: {path}")

        img = iio.imread(path)
        if img.ndim == 2:
            img = np.stack([img] * 3, axis=-1)
        if img.shape[-1] == 3:
            alpha = np.ones((img.shape[0], img.shape[1], 1), dtype=img.dtype)
            img = np.concatenate([img, alpha], axis=-1)
        img = np.flipud(img)

        if img.dtype.kind in ("u", "i"):
            img_f = img.astype(np.float32) / 255.0
        else:
            img_f = img.astype(np.float32)
            img_f = np.clip(img_f, 0.0, 1.0)

        tex = self.ctx.texture((img_f.shape[1], img_f.shape[0]), img_f.shape[-1], data=img_f.tobytes(), dtype="f4")
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x = True
        tex.repeat_y = True
        self.file_textures[path] = tex
        return tex

    def render(self):
        start = self.job.frame_start
        end = self.job.frame_end
        if end <= start and self.job.fps > 0:
            duration = self.job.duration_sec
            if (duration is None or duration <= 0) and self.audio:
                duration = self.audio.meta.duration_sec
            if duration is None or duration <= 0:
                duration = 0.0
            end = start + int(round(duration * self.job.fps))

        out_path = Path(self.job.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        total_frames = end - start
        print(f"Rendering frames {start} to {end}...")
        log_info(f"Starting render: {total_frames} frames at {self.job.fps} fps")

        start_time = time.time()

        try:
            for f in range(start, end):
                self.render_frame(f, out_path)

                # Log progress after each frame
                elapsed = time.time() - start_time
                log_progress(f - start + 1, total_frames, elapsed)

            # Log completion
            log_complete(out_path, total_frames)
            log_info(f"Render complete! Output: {out_path}")

        except Exception as e:
            log_error(f"Render failed: {str(e)}", str(type(e).__name__))
            raise

    def render_frame(self, frame_idx: int, out_dir: Path):
        mode = self.job.camera_stereo

        final_buf_name = next(name for name, b in self.job.multipass_graph.buffers.items() if b.outputs_to_screen)
        final_conf = self.job.multipass_graph.buffers[final_buf_name]
        buf_fmt = final_conf.output_format
        fmt = buf_fmt if buf_fmt else self.job.default_output_format
        buf_bit_depth = final_conf.bit_depth if final_conf.bit_depth else self.job.default_bit_depth

        if iio is None:
            raise RuntimeError("imageio is required to write output frames.")
        if fmt == "exr" and not EXR_AVAILABLE:
            raise RuntimeError("EXR output requested but EXR support is not available in this environment.")

        if self.feedback_pairs:
            self._begin_frame()
        
        # Render Logic
        if mode == 'none':
            img_data = self._render_view(frame_idx, eye='center', out_format=fmt, out_bit_depth=buf_bit_depth)
        else:
            left = self._render_view(frame_idx, eye='left', out_format=fmt, out_bit_depth=buf_bit_depth)
            right = self._render_view(frame_idx, eye='right', out_format=fmt, out_bit_depth=buf_bit_depth)
            if mode == 'sbs':
                img_data = np.concatenate([left, right], axis=1)
            elif mode == 'tb':
                img_data = np.concatenate([left, right], axis=0)
            else:
                img_data = left

        out_file = resolve_output_path(out_dir, self.job.output_pattern, frame_idx, fmt)
        iio.imwrite(out_file, img_data)
        
        print(f"Frame {frame_idx} saved to {out_file.name}")

        if self.feedback_pairs:
            self._end_frame()

    def _render_view(self, frame_idx: int, eye: str, out_format: str, out_bit_depth: str) -> np.ndarray:
        # Accumulation Buffer (CPU, Full Res)
        # We accumulate directly into this.
        acc_buffer = np.zeros((self.internal_height, self.internal_width, 4), dtype=np.float32)
            
        offsets = temporal_offsets(self.job.temporal_samples, frame_idx)
        base_time = frame_idx / self.job.fps
        
        cam_pos = np.array([0.0, 0.0, 0.0])
        cam_dir = np.array([0.0, 0.0, -1.0])
        cam_up  = np.array([0.0, 1.0, 0.0])
        
        ipd = self.job.camera_params.get("ipd", 0.064)
        if eye != 'center':
            f = cam_dir / np.linalg.norm(cam_dir)
            r = np.cross(f, cam_up)
            r = r / np.linalg.norm(r)
            if eye == 'left':
                cam_pos = cam_pos - r * (ipd * 0.5)
            elif eye == 'right':
                cam_pos = cam_pos + r * (ipd * 0.5)

        order = self.job.multipass_graph.execution_order
        final_buf_name = next(name for name, b in self.job.multipass_graph.buffers.items() if b.outputs_to_screen)

        # Tiles
        tiles_x = self.job.tiles_x
        tiles_y = self.job.tiles_y

        for sample_idx, offset in enumerate(offsets):
            time_val = base_time + (offset - 0.5) * self.job.shutter
            
            # 1. Render Dependencies (Full Res, No Tiling support for intermediate yet)
            for buf_name in order:
                if buf_name == final_buf_name: continue
                # Pass 0.0 offset for dependencies
                self._render_pass(buf_name, time_val, frame_idx, sample_idx, cam_pos, cam_dir, cam_up, (0.0, 0.0))
            
            # 2. Render Final Pass (Tiled)
            # Loop tiles
            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    # Calculate Offset (Pixels)
                    off_x = tx * self.tile_w
                    off_y = ty * self.tile_h
                    
                    # Render Tile
                    self._render_pass(final_buf_name, time_val, frame_idx, sample_idx, cam_pos, cam_dir, cam_up, (float(off_x), float(off_y)))
                    
                    # Read Tile
                    tex = self.textures[final_buf_name]
                    raw_bytes = tex.read()
                    
                    buf_conf = self.job.multipass_graph.buffers[final_buf_name]
                    internal_bit_depth = buf_conf.bit_depth or self.job.default_bit_depth
                    # Match the texture dtype we created (8-bit uses f4 internally)
                    if internal_bit_depth == "32f":
                        dtype = 'f4'
                    elif internal_bit_depth == "16f":
                        dtype = 'f2'
                    else:
                        dtype = 'f4'  # 8-bit uses float32 internally
                    numpy_dtype = np.float32 if dtype == 'f4' else np.float16
                    
                    tile_data = np.frombuffer(raw_bytes, dtype=numpy_dtype).reshape((self.tile_h, self.tile_w, 4))
                    tile_data = np.flipud(tile_data) 
                    
                    # Handle edge tiles (cropping if image size not multiple of tile size)
                    # We rendered a full tile (e.g. 512x512).
                    # But the image might end at 1920 (tile 3 might go to 2048).
                    # We write into acc_buffer.
                    
                    # Target coordinates in acc_buffer
                    # Note: moderngl reads flip Y. acc_buffer is (H, W).
                    # off_y is from bottom? No, gl_FragCoord is from bottom-left.
                    # We passed iTileOffset to shader.
                    # Shader: gl_FragCoord.xy + iTileOffset.
                    # If off_y = 0, we render bottom row.
                    # In numpy array, index 0 is TOP row usually, unless we flipped.
                    # We flipped tile_data (`np.flipud`). So tile_data is Top-Down.
                    
                    # We need to calculate where to place this tile in Top-Down `acc_buffer`.
                    # Image Height H.
                    # Tile covers Y range [off_y, off_y + tile_h] in GL coords (Bottom-Up).
                    # In Numpy (Top-Down):
                    # Start Y = H - (off_y + tile_h)
                    # End Y   = H - off_y
                    
                    y_start_gl = off_y
                    y_end_gl = off_y + self.tile_h
                    
                    # Clip to image bounds
                    y_start_gl = max(0, min(self.internal_height, y_start_gl))
                    y_end_gl = max(0, min(self.internal_height, y_end_gl))
                    
                    valid_h = y_end_gl - y_start_gl
                    if valid_h <= 0: continue
                    
                    x_start = off_x
                    x_end = off_x + self.tile_w
                    x_start = max(0, min(self.internal_width, x_start))
                    x_end = max(0, min(self.internal_width, x_end))
                    
                    valid_w = x_end - x_start
                    if valid_w <= 0: continue

                    # Numpy Y indices
                    # GL Y=0 -> Numpy Y=H
                    # GL Y=H -> Numpy Y=0
                    # range [y_start_gl, y_end_gl] -> [H - y_end_gl, H - y_start_gl]
                    ny_start = self.internal_height - y_end_gl
                    ny_end = self.internal_height - y_start_gl
                    
                    # Extract valid region from rendered tile
                    # Tile was rendered full size (self.tile_h, self.tile_w).
                    # If we are at top edge of image, and tile sticks out top:
                    # GL: y_end_gl was clipped to Height.
                    # Tile content: We want the bottom part of the tile (since tile sticks UP out of bounds).
                    # Actually, if we set iTileOffset=off_y, the shader renders rows off_y to off_y+tile_h.
                    # If off_y+tile_h > Height, the top rows of the tile are "garbage" (outside image).
                    # We discard them.
                    # Since tile_data is flipped (Top-Down), the "bottom GL rows" are at the "bottom Numpy rows" of the tile array.
                    # Wait.
                    # GL Row 0 is Tile Bottom. Flipped -> Numpy Row End.
                    # GL Row H is Tile Top. Flipped -> Numpy Row 0.
                    
                    # Let's think:
                    # Tile Data (Numpy): Row 0 is Top of Tile. Row H is Bottom of Tile.
                    # GL Coords: Top of Tile is `off_y + tile_h`. Bottom is `off_y`.
                    
                    # Valid Global Region:
                    # Y from `off_y` to `min(H, off_y + tile_h)`.
                    # Height of valid region: `valid_h`.
                    
                    # We want the pixels corresponding to GL Y range [off_y, off_y + valid_h].
                    # These are the *bottom* `valid_h` rows of the tile in GL sense.
                    # In Top-Down Numpy sense, these are the *bottom* `valid_h` rows of `tile_data`?
                    # No.
                    # Flipped Tile: Row 0 is Top (GL Y max). Row H is Bottom (GL Y min).
                    # We want GL Y range [off_y, off_y + valid_h]. This is the lower part of the covered area.
                    # So it's the *lower* part of the tile in GL space -> *lower* part in Numpy space?
                    # Let's trace.
                    # Pixel P at GL (x, off_y) (Bottom of valid region).
                    # In `tex.read()` (Bottom-Up), it is at index 0.
                    # In `flipud` (Top-Down), it is at index H-1.
                    
                    # Pixel Q at GL (x, off_y + valid_h) (Top of valid region).
                    # In `tex.read()`, index `valid_h`.
                    # In `flipud`, index `H - 1 - valid_h`.
                    
                    # So we take the slice `[-(valid_h):, ...]` from tile_data?
                    # Yes, the bottom rows of the flipped array correspond to the bottom rows of the GL viewport (which are valid).
                    # And `ny_end` (bottom of target slice) corresponds to `off_y` (bottom of GL).
                    
                    tile_slice = tile_data[self.tile_h - valid_h : self.tile_h, 0:valid_w, :]
                    
                    # Add to accumulation
                    # Convert to float32 if not already
                    acc_buffer[ny_start:ny_end, x_start:x_end, :] += tile_slice.astype(np.float32)

        # Average Accumulation
        avg = acc_buffer / self.job.temporal_samples

        # Spatial supersampling downsample to output resolution
        if self.internal_width != self.output_width or self.internal_height != self.output_height:
            if nd_zoom is None:
                avg = avg[:: max(1, int(round(self.internal_height / self.output_height))),
                          :: max(1, int(round(self.internal_width / self.output_width))), :]
            else:
                zoom_y = self.output_height / self.internal_height
                zoom_x = self.output_width / self.internal_width
                avg = nd_zoom(avg, (zoom_y, zoom_x, 1.0), order=1)
            avg = avg[: self.output_height, : self.output_width, :]
        
        # Output conversion
        if out_format == "exr":
            if out_bit_depth == "16f":
                return avg.astype(np.float16)
            return avg.astype(np.float32)
        avg = np.clip(avg, 0.0, 1.0) * 255.0
        return avg.astype(np.uint8)
            
    def _render_pass(self, buf_name: str, time_val: float, frame_idx: int, sample_idx: int, 
                     cam_pos: np.ndarray, cam_dir: np.ndarray, cam_up: np.ndarray,
                     tile_offset: Tuple[float, float]):
        buf_conf = self.job.multipass_graph.buffers[buf_name]
        prog = self.programs[buf_name]
        fbo = self.fbos[buf_name]
        
        fbo.use()
        self.ctx.clear() 
        
        # Compute subpixel jitter for AA (Halton sequence)
        jitter = subpixel_jitter(sample_idx, frame_idx, self.job.temporal_samples)

        # Uniforms
        uni = {
            'iTime': time_val,
            'iTimeDelta': (1.0 / self.job.fps) if self.job.fps > 0 else 0.0,
            'iFrameRate': float(self.job.fps),
            'iFrame': frame_idx,
            'iResolution': (self.internal_width, self.internal_height, 1.0),
            'iPassIndex': self.job.multipass_graph.execution_order.index(buf_name),
            'iTileOffset': tile_offset,
            'iJitter': jitter,
            'iSampleIndex': sample_idx,
            'iMouse': self.job.iMouse,
            # Camera
            'iCameraMode': ['2d', 'equirect', 'll180'].index(self.job.camera_mode),
            'iCameraStereo': ['none', 'sbs', 'tb'].index(self.job.camera_stereo),
            'iCameraFov': math.radians(self.job.camera_fov),
            'iCameraTiltDeg': self.job.camera_params.get("tilt_deg", 65.0),
            'iCameraIPD': self.job.camera_params.get("ipd", 0.064),
            'iCameraPos': tuple(cam_pos),
            'iCameraDir': tuple(cam_dir),
            'iCameraUp': tuple(cam_up),
        }

        # Standard Shadertoy time/date uniforms
        now = datetime.now()
        seconds_of_day = now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6
        uni['iDate'] = (now.year, now.month, now.day, seconds_of_day)

        duration_uniform = self.job.duration_sec
        if (duration_uniform is None or duration_uniform <= 0) and self.audio:
            duration_uniform = self.audio.meta.duration_sec
        uni['iDuration'] = float(duration_uniform or 0.0)

        # iChannelTime / iChannelResolution
        ch_time = [0.0, 0.0, 0.0, 0.0]
        ch_res = [(0.0, 0.0, 0.0)] * 4

        if self.audio:
            uni['iSampleRate'] = float(self.audio.meta.sample_rate)
            if self.job.audio_mode in ("shadertoy", "both"):
                aud_data = self.audio.get_shadertoy_texture(frame_idx)
                if not hasattr(self, 'audio_tex_512'):
                    self.audio_tex_512 = self.ctx.texture((512, 2), 1, dtype='f4')
                self.audio_tex_512.write(aud_data.astype('f4').tobytes())
        else:
            uni['iSampleRate'] = 0.0

        if self.history_tex:
            self.history_tex.use(location=4)
            uni['iAudioHistoryTex'] = 4
            uni['iAudioHistoryResolution'] = (self.history_tex.width, self.history_tex.height, 0)

        # Default audio binding for compatibility if not overridden.
        if self.audio and self.job.audio_mode in ("shadertoy", "both") and 0 not in (buf_conf.channels or {}):
            self.audio_tex_512.use(location=0)
            uni['iChannel0'] = 0
            ch_time[0] = time_val
            ch_res[0] = (512.0, 2.0, 1.0)

        # Bind channels for this buffer.
        for idx, src in (buf_conf.channels or {}).items():
            try:
                unit = int(idx)
            except Exception:
                continue
            if unit < 0 or unit > 3:
                continue
            if src is None:
                continue
            src_str = str(src)
            lower = src_str.lower()
            tex_to_bind: Optional[moderngl.Texture] = None

            if lower in ("audio", "shadertoy_audio"):
                if self.audio and self.job.audio_mode in ("shadertoy", "both"):
                    tex_to_bind = self.audio_tex_512
                    ch_res[unit] = (512.0, 2.0, 1.0)
                    ch_time[unit] = time_val
            elif lower in ("history", "audiohistory", "audio_history"):
                if self.history_tex:
                    tex_to_bind = self.history_tex
                    ch_res[unit] = (float(self.history_tex.width), float(self.history_tex.height), 1.0)
                    ch_time[unit] = time_val
            elif src_str == buf_name and buf_name in self.feedback_pairs:
                tex_to_bind = self.feedback_pairs[buf_name]["prev_tex"]
                ch_res[unit] = (float(tex_to_bind.width), float(tex_to_bind.height), 1.0)
                ch_time[unit] = time_val
            elif src_str.startswith("file:"):
                file_path = Path(src_str[5:]).expanduser()
                tex_to_bind = self._get_file_texture(file_path)
                ch_res[unit] = (float(tex_to_bind.width), float(tex_to_bind.height), 1.0)
                ch_time[unit] = 0.0
            elif src_str in self.textures:
                dep_tex = self.textures[src_str]
                tex_to_bind = dep_tex
                ch_res[unit] = (float(dep_tex.width), float(dep_tex.height), 1.0)
                ch_time[unit] = time_val
            else:
                maybe_path = Path(src_str).expanduser()
                if maybe_path.exists():
                    tex_to_bind = self._get_file_texture(maybe_path)
                    ch_res[unit] = (float(tex_to_bind.width), float(tex_to_bind.height), 1.0)

            if tex_to_bind is not None:
                tex_to_bind.use(location=unit)
                uni[f'iChannel{unit}'] = unit

        uni['iChannelTime'] = tuple(ch_time)
        uni['iChannelResolution'] = tuple(v for triple in ch_res for v in triple)

        self._bind_uniforms(prog, uni)
        
        self.vaos[buf_name].render(moderngl.TRIANGLE_STRIP)
