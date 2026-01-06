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

try:
    import psutil
except ImportError:
    psutil = None

# --- Memory Utilities ---
def get_available_ram_bytes() -> Optional[int]:
    """Get available system RAM in bytes. Returns None if unable to detect."""
    if psutil is not None:
        try:
            return psutil.virtual_memory().available
        except Exception:
            pass
    return None

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

        # Validate tiling and temporal samples (must be at least 1 to avoid division by zero)
        if job.tiles_x < 1:
            raise ValueError(f"tiles_x must be at least 1, got {job.tiles_x}")
        if job.tiles_y < 1:
            raise ValueError(f"tiles_y must be at least 1, got {job.tiles_y}")
        if job.temporal_samples < 1:
            raise ValueError(f"temporal_samples must be at least 1, got {job.temporal_samples}")

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
        print(f"[LOG] render_frame: Starting frame {frame_idx}", file=sys.stderr, flush=True)
        mode = self.job.camera_stereo

        final_buf_name = next(name for name, b in self.job.multipass_graph.buffers.items() if b.outputs_to_screen)
        final_conf = self.job.multipass_graph.buffers[final_buf_name]
        buf_fmt = final_conf.output_format
        fmt = buf_fmt if buf_fmt else self.job.default_output_format
        buf_bit_depth = final_conf.bit_depth if final_conf.bit_depth else self.job.default_bit_depth

        print(f"[LOG] render_frame: format={fmt}, bit_depth={buf_bit_depth}, stereo_mode={mode}", file=sys.stderr, flush=True)

        if iio is None:
            raise RuntimeError("imageio is required to write output frames.")
        if fmt == "exr" and not EXR_AVAILABLE:
            raise RuntimeError("EXR output requested but EXR support is not available in this environment.")

        if self.feedback_pairs:
            print(f"[LOG] render_frame: Beginning frame with {len(self.feedback_pairs)} feedback pairs", file=sys.stderr, flush=True)
            self._begin_frame()

        # Render Logic
        if mode == 'none':
            print(f"[LOG] render_frame: Rendering single view (center)", file=sys.stderr, flush=True)
            img_data = self._render_view(frame_idx, eye='center', out_format=fmt, out_bit_depth=buf_bit_depth)
        else:
            print(f"[LOG] render_frame: Rendering stereo views", file=sys.stderr, flush=True)
            left = self._render_view(frame_idx, eye='left', out_format=fmt, out_bit_depth=buf_bit_depth)
            right = self._render_view(frame_idx, eye='right', out_format=fmt, out_bit_depth=buf_bit_depth)
            if mode == 'sbs':
                img_data = np.concatenate([left, right], axis=1)
            elif mode == 'tb':
                img_data = np.concatenate([left, right], axis=0)
            else:
                img_data = left

        print(f"[LOG] render_frame: Writing output to {out_dir}", file=sys.stderr, flush=True)
        out_file = resolve_output_path(out_dir, self.job.output_pattern, frame_idx, fmt)
        iio.imwrite(out_file, img_data)

        print(f"Frame {frame_idx} saved to {out_file.name}")

        if self.feedback_pairs:
            self._end_frame()

    def _render_view(self, frame_idx: int, eye: str, out_format: str, out_bit_depth: str) -> np.ndarray:
        import time as time_module
        import tempfile
        view_start_time = time_module.time()

        tiles_x = self.job.tiles_x
        tiles_y = self.job.tiles_y
        total_tiles = tiles_x * tiles_y

        print(f"[LOG] _render_view: eye={eye}, internal_size={self.internal_width}x{self.internal_height}, "
              f"tiles={tiles_x}x{tiles_y} ({total_tiles} total), tile_size={self.tile_w}x{self.tile_h}",
              file=sys.stderr, flush=True)

        # Calculate memory for full buffer vs streaming
        full_mem_gb = (self.internal_height * self.internal_width * 4 * 4) / (1024**3)
        tile_mem_mb = (self.tile_h * self.tile_w * 4 * 4) / (1024**2)

        # Use streaming mode if full buffer would be > 4GB or if tiling is enabled
        use_streaming = (full_mem_gb > 4.0) or (total_tiles > 1)

        if use_streaming:
            print(f"[LOG] _render_view: Using STREAMING mode (full buffer would be {full_mem_gb:.1f} GB, tile buffer is {tile_mem_mb:.1f} MB)",
                  file=sys.stderr, flush=True)
            return self._render_view_streaming(frame_idx, eye, out_format, out_bit_depth, view_start_time)
        else:
            print(f"[LOG] _render_view: Using STANDARD mode (buffer is {full_mem_gb:.2f} GB)",
                  file=sys.stderr, flush=True)
            return self._render_view_standard(frame_idx, eye, out_format, out_bit_depth, view_start_time)

    def _stitch_tiles_disk_streaming(self, tile_files: Dict[Tuple[int, int], str],
                                     tiles_x: int, tiles_y: int,
                                     out_format: str, out_bit_depth: str) -> np.ndarray:
        """
        Stitch tiles row-by-row with minimal memory usage.
        Instead of allocating full-size buffer, loads only one row of tiles at a time.
        For ultra-massive images, writes directly to disk during stitching.
        """
        import time as time_module
        
        print(f"[LOG] _stitch_tiles_disk_streaming: Stitching {tiles_x}x{tiles_y} tiles with minimal memory...",
              file=sys.stderr, flush=True)
        
        # Build output row-by-row
        output_rows = []
        
        for row_y in range(tiles_y):
            # Load all tiles in this row
            row_tiles = []
            for tile_x in range(tiles_x):
                tile_path = tile_files[(tile_x, row_y)]
                tile_data = np.load(tile_path)
                row_tiles.append(tile_data)
            
            # Concatenate tiles horizontally for this row
            # Handle edge tiles that might be smaller
            row_height = row_tiles[0].shape[0]
            row_parts = []
            
            for tx, tile in enumerate(row_tiles):
                off_x = tx * self.tile_w
                x_end = min(off_x + self.tile_w, self.internal_width)
                valid_w = x_end - off_x
                
                # Extract valid region from this tile
                if valid_w < tile.shape[1]:
                    row_parts.append(tile[:, :valid_w, :])
                else:
                    row_parts.append(tile)
            
            # Concatenate horizontally
            row_data = np.concatenate(row_parts, axis=1)
            output_rows.append(row_data)
        
        # Stack rows vertically
        # Handle edge rows that might be smaller
        final_parts = []
        for ty, row in enumerate(output_rows):
            off_y = ty * self.tile_h
            y_end_gl = min(off_y + self.tile_h, self.internal_height)
            valid_h = y_end_gl - off_y
            
            if valid_h < row.shape[0]:
                final_parts.append(row[:valid_h, :, :])
            else:
                final_parts.append(row)
        
        final_img = np.concatenate(final_parts, axis=0)
        
        print(f"[LOG] _stitch_tiles_disk_streaming: Stitched to {final_img.shape[0]}x{final_img.shape[1]}",
              file=sys.stderr, flush=True)
        
        return final_img

    def _render_view_streaming(self, frame_idx: int, eye: str, out_format: str, out_bit_depth: str,
                                view_start_time: float) -> np.ndarray:
        """
        Streaming tile-by-tile rendering for large images.
        Processes one tile at a time, accumulates temporal samples per tile,
        writes tiles to temp files, then stitches at the end.
        Memory usage: O(tile_size) instead of O(full_image_size)
        """
        import time as time_module
        import tempfile

        tiles_x = self.job.tiles_x
        tiles_y = self.job.tiles_y
        total_tiles = tiles_x * tiles_y
        num_samples = self.job.temporal_samples

        offsets = temporal_offsets(num_samples, frame_idx)
        base_time = frame_idx / self.job.fps

        cam_pos = np.array([0.0, 0.0, 0.0])
        cam_dir = np.array([0.0, 0.0, -1.0])
        cam_up = np.array([0.0, 1.0, 0.0])

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
        buf_conf = self.job.multipass_graph.buffers[final_buf_name]
        internal_bit_depth = buf_conf.bit_depth or self.job.default_bit_depth

        # Determine numpy dtype for tile data
        if internal_bit_depth == "32f":
            gpu_dtype = 'f4'
        elif internal_bit_depth == "16f":
            gpu_dtype = 'f2'
        else:
            gpu_dtype = 'f4'
        numpy_dtype = np.float32 if gpu_dtype == 'f4' else np.float16

        # Create temp directory for tile files
        temp_dir = tempfile.mkdtemp(prefix="cedartoy_tiles_")
        print(f"[LOG] _render_view_streaming: Temp directory: {temp_dir}", file=sys.stderr, flush=True)

        tile_files = {}  # (tx, ty) -> filepath

        # Process each tile independently
        tile_count = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                tile_count += 1
                off_x = tx * self.tile_w
                off_y = ty * self.tile_h

                print(f"[LOG] Tile {tile_count}/{total_tiles} (tx={tx}, ty={ty}): Processing {num_samples} temporal samples...",
                      file=sys.stderr, flush=True)

                # Allocate accumulation buffer for THIS TILE ONLY
                tile_acc = np.zeros((self.tile_h, self.tile_w, 4), dtype=np.float32)

                # Render all temporal samples for this tile
                for sample_idx, offset in enumerate(offsets):
                    time_val = base_time + (offset - 0.5) * self.job.shutter

                    # Render dependencies (these don't change per tile, but we need them per sample)
                    # TODO: Optimize by caching dependency buffers if they don't use tiling
                    for buf_name in order:
                        if buf_name == final_buf_name:
                            continue
                        self._render_pass(buf_name, time_val, frame_idx, sample_idx, cam_pos, cam_dir, cam_up, (0.0, 0.0))

                    # Render this tile
                    self._render_pass(final_buf_name, time_val, frame_idx, sample_idx,
                                     cam_pos, cam_dir, cam_up, (float(off_x), float(off_y)))

                    # Read tile from GPU
                    tex = self.textures[final_buf_name]
                    raw_bytes = tex.read()
                    tile_data = np.frombuffer(raw_bytes, dtype=numpy_dtype).reshape((self.tile_h, self.tile_w, 4))
                    tile_data = np.flipud(tile_data)

                    # Accumulate
                    tile_acc += tile_data.astype(np.float32)

                # Average this tile
                tile_avg = tile_acc / num_samples

                # Save tile to temp file
                tile_path = os.path.join(temp_dir, f"tile_{tx}_{ty}.npy")
                np.save(tile_path, tile_avg)
                tile_files[(tx, ty)] = tile_path

                print(f"[LOG] Tile {tile_count}/{total_tiles}: Saved to {tile_path}", file=sys.stderr, flush=True)


        # Stitch tiles into final image
        print(f"[LOG] _render_view_streaming: Stitching {total_tiles} tiles into final image...", file=sys.stderr, flush=True)

        # Decide whether to use disk-streaming stitching or memory-based stitching
        stitch_buffer_bytes = self.internal_height * self.internal_width * 4 * 4  # float32 RGBA
        stitch_buffer_gb = stitch_buffer_bytes / (1024**3)
        
        use_disk_streaming = False
        
        if self.job.disk_streaming is True:
            # Always use disk streaming
            use_disk_streaming = True
            print(f"[LOG] Disk streaming: FORCED ON (config)", file=sys.stderr, flush=True)
        elif self.job.disk_streaming is False:
            # Never use disk streaming
            use_disk_streaming = False
            print(f"[LOG] Disk streaming: FORCED OFF (config)", file=sys.stderr, flush=True)
        else:
            # Auto mode: check available RAM
            available_ram = get_available_ram_bytes()
            if available_ram is not None:
                available_ram_gb = available_ram / (1024**3)
                threshold_bytes = available_ram * 0.5  # Use 50% of available RAM as threshold
                
                if stitch_buffer_bytes > threshold_bytes:
                    use_disk_streaming = True
                    print(f"[LOG] Disk streaming: AUTO ON (buffer={stitch_buffer_gb:.2f}GB, "
                          f"available RAM={available_ram_gb:.2f}GB, threshold=50%)", 
                          file=sys.stderr, flush=True)
                else:
                    use_disk_streaming = False
                    print(f"[LOG] Disk streaming: AUTO OFF (buffer={stitch_buffer_gb:.2f}GB fits in "
                          f"available RAM={available_ram_gb:.2f}GB)", 
                          file=sys.stderr, flush=True)
            else:
                # Can't detect RAM, use conservative threshold of 4GB
                if stitch_buffer_gb > 4.0:
                    use_disk_streaming = True
                    print(f"[LOG] Disk streaming: AUTO ON (buffer={stitch_buffer_gb:.2f}GB, "
                          f"RAM detection unavailable, using 4GB fallback threshold)", 
                          file=sys.stderr, flush=True)
                else:
                    use_disk_streaming = False
                    print(f"[LOG] Disk streaming: AUTO OFF (buffer={stitch_buffer_gb:.2f}GB, "
                          f"RAM detection unavailable)", 
                          file=sys.stderr, flush=True)
        
        # Perform stitching
        if use_disk_streaming:
            final_img = self._stitch_tiles_disk_streaming(tile_files, tiles_x, tiles_y, out_format, out_bit_depth)
        else:
            # Original memory-based stitching
            final_img = np.zeros((self.internal_height, self.internal_width, 4), dtype=np.float32)

            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    tile_path = tile_files[(tx, ty)]
                    tile_data = np.load(tile_path)

                    off_x = tx * self.tile_w
                    off_y = ty * self.tile_h

                    # Calculate valid region (handle edge tiles)
                    y_start_gl = off_y
                    y_end_gl = min(off_y + self.tile_h, self.internal_height)
                    x_start = off_x
                    x_end = min(off_x + self.tile_w, self.internal_width)

                    valid_h = y_end_gl - y_start_gl
                    valid_w = x_end - x_start

                    if valid_h <= 0 or valid_w <= 0:
                        continue

                    # Convert GL coords to numpy coords
                    ny_start = self.internal_height - y_end_gl
                    ny_end = self.internal_height - y_start_gl

                    # Extract valid region from tile
                    tile_slice = tile_data[self.tile_h - valid_h:self.tile_h, 0:valid_w, :]

                    # Place in final image
                    final_img[ny_start:ny_end, x_start:x_end, :] = tile_slice

        # Clean up temp files
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[LOG] _render_view_streaming: Cleaned up temp directory", file=sys.stderr, flush=True)

        # Downsample if needed
        if self.internal_width != self.output_width or self.internal_height != self.output_height:
            print(f"[LOG] _render_view_streaming: Downsampling {self.internal_width}x{self.internal_height} -> {self.output_width}x{self.output_height}...",
                  file=sys.stderr, flush=True)
            if nd_zoom is None:
                final_img = final_img[::max(1, int(round(self.internal_height / self.output_height))),
                                      ::max(1, int(round(self.internal_width / self.output_width))), :]
            else:
                zoom_y = self.output_height / self.internal_height
                zoom_x = self.output_width / self.internal_width
                final_img = nd_zoom(final_img, (zoom_y, zoom_x, 1.0), order=1)
            final_img = final_img[:self.output_height, :self.output_width, :]

        view_elapsed = time_module.time() - view_start_time
        print(f"[LOG] _render_view_streaming: Total time: {view_elapsed:.2f}s", file=sys.stderr, flush=True)

        # Convert to output format
        if out_format == "exr":
            if out_bit_depth == "16f":
                return final_img.astype(np.float16)
            return final_img.astype(np.float32)
        final_img = np.clip(final_img, 0.0, 1.0) * 255.0
        return final_img.astype(np.uint8)

    def _render_view_standard(self, frame_idx: int, eye: str, out_format: str, out_bit_depth: str,
                              view_start_time: float) -> np.ndarray:
        """Standard in-memory rendering for smaller images."""
        import time as time_module

        tiles_x = self.job.tiles_x
        tiles_y = self.job.tiles_y
        total_tiles = tiles_x * tiles_y

        # Allocate full accumulation buffer
        acc_buffer = np.zeros((self.internal_height, self.internal_width, 4), dtype=np.float32)
        print(f"[LOG] _render_view_standard: Allocated {acc_buffer.nbytes / (1024*1024):.1f} MB buffer",
              file=sys.stderr, flush=True)

        offsets = temporal_offsets(self.job.temporal_samples, frame_idx)
        base_time = frame_idx / self.job.fps

        cam_pos = np.array([0.0, 0.0, 0.0])
        cam_dir = np.array([0.0, 0.0, -1.0])
        cam_up = np.array([0.0, 1.0, 0.0])

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
        buf_conf = self.job.multipass_graph.buffers[final_buf_name]
        internal_bit_depth = buf_conf.bit_depth or self.job.default_bit_depth

        if internal_bit_depth == "32f":
            gpu_dtype = 'f4'
        elif internal_bit_depth == "16f":
            gpu_dtype = 'f2'
        else:
            gpu_dtype = 'f4'
        numpy_dtype = np.float32 if gpu_dtype == 'f4' else np.float16

        for sample_idx, offset in enumerate(offsets):
            time_val = base_time + (offset - 0.5) * self.job.shutter

            # Render dependencies
            for buf_name in order:
                if buf_name == final_buf_name:
                    continue
                self._render_pass(buf_name, time_val, frame_idx, sample_idx, cam_pos, cam_dir, cam_up, (0.0, 0.0))

            # Render tiles
            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    off_x = tx * self.tile_w
                    off_y = ty * self.tile_h

                    self._render_pass(final_buf_name, time_val, frame_idx, sample_idx,
                                     cam_pos, cam_dir, cam_up, (float(off_x), float(off_y)))

                    tex = self.textures[final_buf_name]
                    raw_bytes = tex.read()
                    tile_data = np.frombuffer(raw_bytes, dtype=numpy_dtype).reshape((self.tile_h, self.tile_w, 4))
                    tile_data = np.flipud(tile_data)

                    # Calculate placement
                    y_start_gl = off_y
                    y_end_gl = min(off_y + self.tile_h, self.internal_height)
                    x_start = off_x
                    x_end = min(off_x + self.tile_w, self.internal_width)

                    valid_h = y_end_gl - y_start_gl
                    valid_w = x_end - x_start

                    if valid_h <= 0 or valid_w <= 0:
                        continue

                    ny_start = self.internal_height - y_end_gl
                    ny_end = self.internal_height - y_start_gl

                    tile_slice = tile_data[self.tile_h - valid_h:self.tile_h, 0:valid_w, :]
                    acc_buffer[ny_start:ny_end, x_start:x_end, :] += tile_slice.astype(np.float32)

        # Average
        avg = acc_buffer / self.job.temporal_samples

        # Downsample
        if self.internal_width != self.output_width or self.internal_height != self.output_height:
            if nd_zoom is None:
                avg = avg[::max(1, int(round(self.internal_height / self.output_height))),
                          ::max(1, int(round(self.internal_width / self.output_width))), :]
            else:
                zoom_y = self.output_height / self.internal_height
                zoom_x = self.output_width / self.internal_width
                avg = nd_zoom(avg, (zoom_y, zoom_x, 1.0), order=1)
            avg = avg[:self.output_height, :self.output_width, :]

        view_elapsed = time_module.time() - view_start_time
        print(f"[LOG] _render_view_standard: Total time: {view_elapsed:.2f}s", file=sys.stderr, flush=True)

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
        
        # Inject custom shader parameters
        for k, v in self.job.shader_parameters.items():
            uni[k] = v

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
