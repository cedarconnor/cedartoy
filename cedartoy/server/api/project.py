"""Project-load endpoint: resolves any path inside a project folder."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from cedartoy.project import load_project

router = APIRouter()


class ProjectLoadRequest(BaseModel):
    path: str = Field(..., description="Folder, audio, bundle, or stem path.")


@router.post("/load")
def project_load(body: ProjectLoadRequest) -> dict:
    p = Path(body.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {p}")
    proj = load_project(p)
    audio_path_str = str(proj.audio_path) if proj.audio_path else None
    audio_url = f"/api/project/audio?path={audio_path_str}" if audio_path_str else None
    return {
        "folder": str(proj.folder),
        "audio_path": audio_path_str,
        "audio_url": audio_url,
        "bundle_path": str(proj.bundle_path) if proj.bundle_path else None,
        "stems_paths": {k: str(v) for k, v in proj.stems_paths.items()},
        "manifest": proj.manifest,
        "bundle_sha_matches_audio": proj.bundle_sha_matches_audio,
        "warnings": proj.warnings,
    }


@router.get("/audio")
def project_audio(path: str):
    """Stream the project's audio file with Range support.

    The browser's <audio> element uses Range to seek without re-downloading
    the whole song. FileResponse handles Range/206 natively in Starlette.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    media_type = "audio/wav" if p.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(p, media_type=media_type, headers={"Accept-Ranges": "bytes"})


@router.get("/waveform")
def project_waveform(path: str, n: int = 1000) -> dict:
    """Return `n` peak values (range -1.0..1.0) sampled across the audio file.

    Used by cue-scrubber to paint the waveform underlay. The wav is read
    fresh each call (no global state) — cheap for typical 3-5 minute songs.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    import numpy as np
    import soundfile as sf
    data, _ = sf.read(str(p), always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if len(data) == 0:
        return {"peaks": [0.0] * n}
    bucket = max(1, len(data) // n)
    peaks = []
    for i in range(n):
        start = i * bucket
        end = min(start + bucket, len(data))
        chunk = data[start:end]
        peaks.append(float(np.max(np.abs(chunk))) if len(chunk) else 0.0)
    return {"peaks": peaks}


@router.get("/bundle")
def project_bundle(path: str) -> dict:
    """Return the bundle JSON at a server-local path.

    Consumed by the cue-scrubber which needs sections/beats/drums/energy
    arrays to render the timeline.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="bundle not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"bundle parse error: {e}") from e
