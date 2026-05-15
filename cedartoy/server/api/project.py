"""Project-load endpoint: resolves any path inside a project folder."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
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
    return {
        "folder": str(proj.folder),
        "audio_path": str(proj.audio_path) if proj.audio_path else None,
        "bundle_path": str(proj.bundle_path) if proj.bundle_path else None,
        "stems_paths": {k: str(v) for k, v in proj.stems_paths.items()},
        "manifest": proj.manifest,
        "bundle_sha_matches_audio": proj.bundle_sha_matches_audio,
        "warnings": proj.warnings,
    }


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
