"""POST /api/shader/apply — writes Claude's GLSL output to a shader file.

Atomic-rename pattern: write to a temp file in the same directory, then
os.replace() over the target. A failure mid-write leaves no half-baked
shader for the preview to compile against.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

SHADERS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "shaders"


class ApplyRequest(BaseModel):
    base: str = Field(..., description="Original shader filename (e.g. 'phantom_mode.glsl').")
    glsl: str = Field(..., description="Full GLSL source to write.")
    mode: Literal["sibling", "overwrite"] = "sibling"


def _atomic_write(target: Path, content: str) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".cedartoy-apply-", suffix=".glsl", dir=str(target.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


@router.post("/apply")
def shader_apply(body: ApplyRequest) -> dict:
    if not body.glsl.strip():
        raise HTTPException(status_code=400, detail="glsl is empty")

    candidate = (SHADERS_DIR / body.base).resolve()
    try:
        candidate.relative_to(SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="base outside shaders directory")

    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"base shader not found: {body.base}")

    if body.mode == "sibling":
        target = candidate.with_name(f"{candidate.stem}_reactive.glsl")
    else:
        target = candidate

    _atomic_write(target, body.glsl)
    rel = target.relative_to(SHADERS_DIR.resolve()).as_posix()
    return {"path": f"shaders/{rel}"}
