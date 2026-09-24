"""Project-load endpoint: resolves any path inside a project folder."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from cedartoy.project import load_project
from cedartoy.server.api.files import (
    add_allowed_file,
    add_allowed_root,
    is_path_allowed,
    is_too_broad_root,
)

router = APIRouter()

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aiff", ".aif"}
BUNDLE_EXTENSIONS = {".json"}
_AUDIO_MEDIA_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}


def _register_project(proj) -> None:
    """Allow the loaded project's files to be served by the GET endpoints.

    The folder becomes an allowed root unless it is a filesystem root or the
    home directory, in which case only the project's own files are allowed.
    """
    folder = Path(proj.folder)
    if not is_too_broad_root(folder):
        add_allowed_root(folder)
        return
    for f in [proj.audio_path, proj.bundle_path, *proj.stems_paths.values()]:
        if f:
            add_allowed_file(Path(f))


def _checked_file(path: str, extensions: set, what: str) -> Path:
    """Validate a client-supplied path: allowed extension, inside an allowed
    root (a loaded project folder or the CedarToy directory), and existing."""
    p = Path(path)
    if p.suffix.lower() not in extensions:
        raise HTTPException(status_code=400, detail=f"unsupported {what} file type")
    resolved = p.resolve()
    if not is_path_allowed(resolved):
        raise HTTPException(status_code=403, detail=f"{what} path not in a loaded project")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return resolved


class ProjectLoadRequest(BaseModel):
    path: str = Field(..., description="Folder, audio, bundle, or stem path.")


@router.post("/load")
def project_load(body: ProjectLoadRequest) -> dict:
    p = Path(body.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {p}")
    proj = load_project(p)
    _register_project(proj)
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
    p = _checked_file(path, AUDIO_EXTENSIONS, "audio")
    media_type = _AUDIO_MEDIA_TYPES.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(p, media_type=media_type, headers={"Accept-Ranges": "bytes"})


@router.get("/waveform")
def project_waveform(path: str, n: int = 1000) -> dict:
    """Return `n` peak values (range -1.0..1.0) sampled across the audio file.

    Used by cue-scrubber to paint the waveform underlay. The wav is read
    fresh each call (no global state) — cheap for typical 3-5 minute songs.
    """
    p = _checked_file(path, AUDIO_EXTENSIONS, "audio")
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
    p = _checked_file(path, BUNDLE_EXTENSIONS, "bundle")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"bundle parse error: {e}") from e
