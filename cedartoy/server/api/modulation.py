"""POST /api/modulation/series — per-frame modulated @param values for the
preview (Python computes via cedartoy.modulation, the browser only binds)."""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cedartoy.modulation import (
    CURVES, MOD_SOURCES, MODES, ModulationEvaluator, Route, SourceTable,
    float_params, resolve_routes,
)
from cedartoy.musicue import discover_bundle_path, load_bundle
from cedartoy.server.api.project import (
    AUDIO_EXTENSIONS, BUNDLE_EXTENSIONS, _checked_file,
)
from cedartoy.server.api.shader_apply import _resolve_base
from cedartoy.shader import parse_params

router = APIRouter()

# Source tables are route-independent and cost ~1-2 s for a long song, so
# keep a few around while the user edits routes.
_TABLE_CACHE: "OrderedDict[Tuple, Tuple[SourceTable, float]]" = OrderedDict()
_TABLE_CACHE_MAX = 4


class SeriesRequest(BaseModel):
    shader: str = Field(..., description="Shader path, e.g. 'shaders/foo.glsl' or 'foo.glsl'.")
    audio: Optional[str] = None
    bundle: Optional[str] = None
    fps: float = Field(24.0, gt=0, le=240)
    routes: Optional[List[Route]] = None      # None = the shader's @mod defaults
    shader_parameters: Dict[str, Any] = Field(default_factory=dict)
    track_settings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    av_offset_ms: float = 0.0


def _shader_path(shader: str) -> Path:
    rel = shader.replace("\\", "/")
    if rel.startswith("shaders/"):
        rel = rel[len("shaders/"):]
    path = _resolve_base(rel)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"shader not found: {shader}")
    return path


def _bundle_path(body: SeriesRequest) -> Optional[Path]:
    if body.bundle:
        return _checked_file(body.bundle, BUNDLE_EXTENSIONS, "bundle")
    if body.audio:
        audio = _checked_file(body.audio, AUDIO_EXTENSIONS, "audio")
        return discover_bundle_path(audio)
    return None


def _source_table(path: Path, body: SeriesRequest) -> Tuple[SourceTable, float]:
    key = (str(path), path.stat().st_mtime_ns, float(body.fps),
           float(body.av_offset_ms or 0.0),
           json.dumps(body.track_settings, sort_keys=True, default=str))
    hit = _TABLE_CACHE.get(key)
    if hit is not None:
        _TABLE_CACHE.move_to_end(key)
        return hit
    try:
        bundle = load_bundle(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    table = SourceTable(bundle, body.fps, body.track_settings, body.av_offset_ms)
    entry = (table, float(bundle.duration_sec))
    _TABLE_CACHE[key] = entry
    while len(_TABLE_CACHE) > _TABLE_CACHE_MAX:
        _TABLE_CACHE.popitem(last=False)
    return entry


@router.post("/series")
def modulation_series(body: SeriesRequest) -> dict:
    src = _shader_path(body.shader).read_text(encoding="utf-8")
    params = parse_params(src)
    routes = resolve_routes(body.routes, src)
    out: Dict[str, Any] = {
        "fps": float(body.fps),
        "frames": 0,
        "duration_sec": 0.0,
        "params": params,
        "routes": [r.model_dump() for r in routes],
        "routes_from": "config" if body.routes is not None else "shader",
        "mod_sources": list(MOD_SOURCES),
        "curves": list(CURVES),
        "modes": list(MODES),
        "bundle_loaded": False,
        "series": {},
    }
    bundle_path = _bundle_path(body)
    if bundle_path is None or not float_params(params):
        return out
    table, duration = _source_table(bundle_path, body)
    ev = ModulationEvaluator(
        None, body.fps, routes, params,
        shader_parameters=body.shader_parameters, source_table=table)
    n_frames = int(round(duration * body.fps))
    out.update(frames=n_frames, duration_sec=duration, bundle_loaded=True,
               series=ev.series(body.fps, n_frames))
    return out
