from dataclasses import dataclass, field
from typing import Any, List, Optional, Callable

# EXR Gating Check
def _check_exr_available() -> bool:
    try:
        import numpy as _np
        import imageio.v3 as _iio
        import os as _os
        import tempfile as _tempfile
        tmp_path = None
        try:
            with _tempfile.NamedTemporaryFile(suffix=".exr", delete=False) as tmp:
                tmp_path = tmp.name
            _iio.imwrite(tmp_path, _np.zeros((2, 2, 3), dtype=_np.float32))
            return True
        finally:
            if tmp_path:
                try:
                    _os.remove(tmp_path)
                except OSError:
                    pass
    except Exception:
        return False

EXR_AVAILABLE = _check_exr_available()

@dataclass
class Option:
    name: str
    label: str
    type: str  # "str", "int", "float", "bool", "path", "choice", "dict"
    default: Any
    choices: Optional[List[str]] = None
    help_text: Optional[str] = None
    validator: Optional[Callable[[Any], bool]] = None

OPTIONS: List[Option] = []

# --- Core ---
OPTIONS.append(Option("width", "Width", "int", 1920))
OPTIONS.append(Option("height", "Height", "int", 1080))
OPTIONS.append(Option("fps", "FPS", "float", 60.0))
OPTIONS.append(Option("duration_sec", "Duration (sec)", "float", 10.0))
# frame_start/end are derived from duration usually, or explicit. 
# We'll stick to what the design implies or commonly uses. 
# Design mentions frame_start, frame_end in RenderJob.
OPTIONS.append(Option("frame_start", "Start Frame", "int", 0))
# frame_end might be calculated, but we can have an option for it or duration.
# We'll keep duration as the primary for the wizard? 
# The design RenderJob has frame_start/end. Let's add them.
OPTIONS.append(Option("frame_end", "End Frame", "int", 0, help_text="If 0, calculated from duration * fps"))

# --- Tiling ---
OPTIONS.append(Option("tiles_x", "Tiles X", "int", 1))
OPTIONS.append(Option("tiles_y", "Tiles Y", "int", 1))

# --- Quality ---
OPTIONS.append(Option("ss_scale", "SuperSampling Scale", "float", 1.0))
OPTIONS.append(Option("temporal_samples", "Temporal Samples", "int", 1))
OPTIONS.append(Option("shutter", "Shutter Angle (0-1)", "float", 0.5))

available_formats = ["png"]
if EXR_AVAILABLE:
    available_formats.append("exr")

OPTIONS.append(Option(
    "default_output_format", "Default Output Format", "choice", "png",
    choices=available_formats
))

OPTIONS.append(Option(
    "default_bit_depth", "Default Bit Depth", "choice", "8",
    choices=["8", "16f", "32f"],
    help_text="Per-buffer overrides live in the multipass config; this is a default."
))

# --- Audio ---
OPTIONS.append(Option("audio_path", "Audio Path", "path", None))
OPTIONS.append(Option("audio_mode", "Audio Mode", "choice", "both", choices=["shadertoy", "history", "both"]))

# --- Camera ---
OPTIONS.append(Option("camera_mode", "Camera Mode", "choice", "2d", choices=["2d", "equirect", "ll180"]))
OPTIONS.append(Option("camera_stereo", "Stereo Mode", "choice", "none", choices=["none", "sbs", "tb"]))
OPTIONS.append(Option("camera_fov", "FOV", "float", 90.0))
OPTIONS.append(Option("camera_tilt_deg", "Tilt (LL180)", "float", 65.0))
OPTIONS.append(Option("camera_ipd", "IPD", "float", 0.064))

# --- Paths ---
OPTIONS.append(Option(
    "disk_streaming", "Disk Streaming Mode", "choice", None,
    choices=[None, True, False],
    help_text="Auto (None): use disk streaming if buffer exceeds 50% available RAM. True: always use. False: never use."
))
OPTIONS.append(Option("output_dir", "Output Directory", "path", "renders"))
OPTIONS.append(Option("output_pattern", "Output Pattern", "str", "frame_{frame:05d}.{ext}"))
