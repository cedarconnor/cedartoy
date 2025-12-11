import moderngl
import numpy as np
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import math
from dataclasses import asdict

from .types import RenderJob, BufferConfig, MultipassGraphConfig
from .shader import load_shader_from_file
from .audio import AudioProcessor
from .naming import resolve_output_path

try:
    import imageio.v3 as iio
except ImportError:
    iio = None

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

def build_basis(forward: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = forward / np.linalg.norm(forward)
    r = np.cross(up, f)
    r = r / np.linalg.norm(r)
    u = np.cross(f, r)
    return np.array([r, u, f])

class Renderer:
    def __init__(self, job: RenderJob):
        self.job = job
        self.ctx = moderngl.create_context(standalone=True)
        
        # Audio
        self.audio = None
        if job.audio_path:
            self.audio = AudioProcessor(job.audio_path, job.audio_fps)
            self.history_tex_data = self.audio.get_history_texture()
            self.history_tex = self.ctx.texture(
                (self.history_tex_data.shape[1], self.history_tex_data.shape[0]),
                1,
                data=self.history_tex_data.tobytes(),
                dtype='f4'
            )
        else:
            self.history_tex = None

        self.programs = {} 
        self.textures = {} 
        self.fbos = {}     
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
        
        self.tile_w = math.ceil(self.job.width / tiles_x)
        self.tile_h = math.ceil(self.job.height / tiles_y)
        
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
            
            # 2. Allocate Texture
            # Standard texture (Full Res) for dependency passes
            dtype = 'f1'
            if buf.bit_depth == "16f": dtype = 'f2'
            elif buf.bit_depth == "32f": dtype = 'f4'
            elif self.job.default_bit_depth == "16f": dtype = 'f2'
            elif self.job.default_bit_depth == "32f": dtype = 'f4'
            
            # If this is the output pass AND we are tiling, we allocate a Small texture for tile rendering
            # BUT we also allocate the Full texture? 
            # If we stitch on CPU, we don't need full GPU texture for the output pass.
            # But what if another pass reads it? (Feedback).
            # If feedback is needed, we need full texture.
            # Assuming output pass is NOT read by others for now (DAG terminal).
            
            # We will always allocate full texture for intermediate buffers.
            # For screen output buffer, if tiling, we allocate TILE size.
            
            width = self.job.width
            height = self.job.height
            
            if buf.outputs_to_screen and (tiles_x > 1 or tiles_y > 1):
                width = self.tile_w
                height = self.tile_h
                print(f"Allocating TILE buffer for {name}: {width}x{height}")
            
            tex = self.ctx.texture((width, height), 4, dtype=dtype)
            self.textures[name] = tex
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            self.fbos[name] = fbo

    def _bind_uniforms(self, prog, uniforms: Dict[str, Any]):
        for k, v in uniforms.items():
            if k in prog:
                try:
                    prog[k].value = v
                except Exception as e:
                    pass

    def render(self):
        start = self.job.frame_start
        end = self.job.frame_end
        if end == 0 and self.job.fps > 0:
            end = int(self.job.audio_meta.duration_sec * self.job.fps) if self.job.audio_meta else int(10.0 * self.job.fps)

        out_path = Path(self.job.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        print(f"Rendering frames {start} to {end}...")
        
        for f in range(start, end):
            self.render_frame(f, out_path)

    def render_frame(self, frame_idx: int, out_dir: Path):
        mode = self.job.camera_stereo
        
        # Render Logic
        if mode == 'none':
            img_data = self._render_view(frame_idx, eye='center')
        else:
            left = self._render_view(frame_idx, eye='left')
            right = self._render_view(frame_idx, eye='right')
            if mode == 'sbs':
                img_data = np.concatenate([left, right], axis=1)
            elif mode == 'tb':
                img_data = np.concatenate([left, right], axis=0)
            else:
                img_data = left
                
        final_buf_name = next(name for name, b in self.job.multipass_graph.buffers.items() if b.outputs_to_screen)
        buf_fmt = self.job.multipass_graph.buffers[final_buf_name].output_format
        fmt = buf_fmt if buf_fmt else self.job.default_output_format

        out_file = resolve_output_path(out_dir, self.job.output_pattern, frame_idx, fmt)
        iio.imwrite(out_file, img_data)
        
        print(f"Frame {frame_idx} saved to {out_file.name}")

    def _render_view(self, frame_idx: int, eye: str) -> np.ndarray:
        # Accumulation Buffer (CPU, Full Res)
        # We accumulate directly into this.
        acc_buffer = np.zeros((self.job.height, self.job.width, 4), dtype=np.float32)
            
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
                    
                    # Determine dtype logic (duped from before)
                    buf_conf = self.job.multipass_graph.buffers[final_buf_name]
                    dtype = 'f1'
                    if buf_conf.bit_depth == "16f": dtype = 'f2'
                    elif buf_conf.bit_depth == "32f": dtype = 'f4'
                    elif self.job.default_bit_depth == "16f": dtype = 'f2'
                    elif self.job.default_bit_depth == "32f": dtype = 'f4'
                    numpy_dtype = np.float32 if dtype == 'f4' else (np.float16 if dtype == 'f2' else np.uint8)
                    
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
                    y_start_gl = max(0, min(self.job.height, y_start_gl))
                    y_end_gl = max(0, min(self.job.height, y_end_gl))
                    
                    valid_h = y_end_gl - y_start_gl
                    if valid_h <= 0: continue
                    
                    x_start = off_x
                    x_end = off_x + self.tile_w
                    x_start = max(0, min(self.job.width, x_start))
                    x_end = max(0, min(self.job.width, x_end))
                    
                    valid_w = x_end - x_start
                    if valid_w <= 0: continue

                    # Numpy Y indices
                    # GL Y=0 -> Numpy Y=H
                    # GL Y=H -> Numpy Y=0
                    # range [y_start_gl, y_end_gl] -> [H - y_end_gl, H - y_start_gl]
                    ny_start = self.job.height - y_end_gl
                    ny_end = self.job.height - y_start_gl
                    
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
        
        # Tone Map / Convert
        if numpy_dtype == np.uint8:
            return avg.astype(np.uint8)
        else:
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
        
        # Uniforms
        uni = {
            'iTime': time_val,
            'iFrame': frame_idx,
            'iResolution': (self.job.width, self.job.height, 1.0),
            'iPassIndex': 0, 
            'iTileOffset': tile_offset,
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
        
        # Bind Audio
        if self.audio:
            aud_data = self.audio.get_shadertoy_texture(frame_idx) 
            if not hasattr(self, 'audio_tex_512'):
                self.audio_tex_512 = self.ctx.texture((512, 2), 1, dtype='f4')
            self.audio_tex_512.write(aud_data.astype('f4').tobytes())
            self.audio_tex_512.use(location=0) 
            uni['iChannel0'] = 0
            if self.history_tex:
                self.history_tex.use(location=4) 
                uni['iAudioHistoryTex'] = 4
                uni['iAudioHistoryResolution'] = (self.history_tex.width, self.history_tex.height, 0)

        self._bind_uniforms(prog, uni)
        
        fmt_parts = []
        attrs = []
        if 'in_vert' in prog:
            fmt_parts.append('2f')
            attrs.append('in_vert')
        else:
            fmt_parts.append('2x')
        if 'in_uv' in prog:
            fmt_parts.append('2f')
            attrs.append('in_uv')
        else:
            fmt_parts.append('2x')
        fmt = ' '.join(fmt_parts)
        
        vao = self.ctx.vertex_array(prog, [(self.vbo, fmt, *attrs)])
        vao.render(moderngl.TRIANGLE_STRIP)
        vao.release()