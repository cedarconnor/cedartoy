from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

@dataclass
class AudioMeta:
    duration_sec: float      # seconds
    sample_rate: int         # Hz
    frame_count: int         # frames at audio_fps
    freq_bins: int           # STFT frequency bins (per channel)
    channels: int            # usually 2
    audio_fps: float         # target fps used during preprocessing

@dataclass
class BufferConfig:
    name: str                        # "Image", "A", "B", ...
    shader: Path                     # GLSL file for this pass
    outputs_to_screen: bool          # True for final image pass
    channels: Dict[int, str]         # iChannel index -> source name ("A", "B", "audio", "file:tex.png", ...)
    output_format: Optional[str] = None  # "png", "exr" or None -> use job default
    bit_depth: Optional[str] = None      # "8", "16f", "32f" or None -> use job default

@dataclass
class MultipassGraphConfig:
    buffers: Dict[str, BufferConfig]     # keyed by buffer name
    execution_order: List[str]           # topologically sorted buffer names

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
    duration_sec: float
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
    audio_mode: str
    audio_fps: float
    audio_meta: Optional[AudioMeta]

    # camera / VR
    camera_mode: str
    camera_stereo: str
    camera_fov: float
    camera_params: Dict[str, Any]      # {"tilt_deg": 65.0, "ipd": 0.064, ...}

    # multipass
    multipass_graph: MultipassGraphConfig
