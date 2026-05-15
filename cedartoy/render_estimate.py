"""Pure render-budget estimation.

Frame time is sourced from a per-(shader, resolution) moving average
stored in ~/.cedartoy/render_history.json. With no history, falls back
to DEFAULT_FRAME_TIME_SEC. Scales the base time by tile_count × ss_scale².

Output size is exact: bytes_per_pixel × pixels × frames.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FRAME_TIME_SEC = 5.0  # conservative default with no prior history

HISTORY_PATH = Path.home() / ".cedartoy" / "render_history.json"

# (format, bit_depth) -> bytes per pixel (RGBA assumed everywhere).
_BPP: dict[tuple[str, int], int] = {
    ("png", 8): 4,
    ("png", 16): 8,
    ("exr", 16): 8,
    ("exr", 32): 16,
}


def bytes_per_frame(fmt: str, bit_depth: int, width: int, height: int) -> int:
    key = (fmt, bit_depth)
    if key not in _BPP:
        raise ValueError(f"unknown format/bit_depth: {key}; "
                         f"known: {sorted(_BPP)}")
    return _BPP[key] * width * height


@dataclass
class RenderEstimate:
    frame_time_sec: float
    total_frames: int
    total_seconds: float
    output_bytes: int
    history_hit: bool

    def exceeds_time_threshold(self, threshold_sec: float) -> bool:
        return self.total_seconds > threshold_sec

    def exceeds_size_threshold(self, threshold_bytes: int) -> bool:
        return self.output_bytes > threshold_bytes


def _history_key(shader_basename: str, width: int, height: int) -> str:
    return f"{shader_basename}::{width}x{height}"


def estimate_render(
    *,
    shader_basename: str,
    width: int,
    height: int,
    fps: float,
    duration_sec: float,
    tile_count: int,
    ss_scale: float,
    format: str,
    bit_depth: int,
    history: dict | None = None,
) -> RenderEstimate:
    history = history if history is not None else {}
    key = _history_key(shader_basename, width, height)
    entry = history.get(key)
    if entry and "mean_frame_time" in entry:
        base_frame_time = float(entry["mean_frame_time"])
        hit = True
    else:
        base_frame_time = DEFAULT_FRAME_TIME_SEC
        hit = False

    frame_time = base_frame_time * tile_count * (ss_scale ** 2)
    total_frames = max(1, math.ceil(duration_sec * fps))
    total_seconds = frame_time * total_frames
    output_bytes = bytes_per_frame(format, bit_depth, width, height) * total_frames

    return RenderEstimate(
        frame_time_sec=frame_time,
        total_frames=total_frames,
        total_seconds=total_seconds,
        output_bytes=output_bytes,
        history_hit=hit,
    )


def load_history(path: Path = HISTORY_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_history(
    *,
    shader_basename: str,
    width: int,
    height: int,
    mean_frame_time: float,
    path: Path = HISTORY_PATH,
) -> None:
    """Update the moving average for (shader, resolution).

    Uses an EMA with alpha=0.3 so a single outlier render doesn't
    dominate the estimate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(path)
    key = _history_key(shader_basename, width, height)
    prev = history.get(key, {}).get("mean_frame_time")
    new = mean_frame_time if prev is None else 0.7 * prev + 0.3 * mean_frame_time
    history[key] = {"mean_frame_time": new}
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
