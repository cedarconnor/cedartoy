"""POST /api/shader/apply — writes Claude's GLSL output to a shader file.

Atomic-rename pattern: write to a temp file in the same directory, then
os.replace() over the target. A failure mid-write leaves no half-baked
shader for the preview to compile against.
"""
from __future__ import annotations

import os
import re
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


_SAFE_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


def _resolve_base(base: str) -> Path:
    """Validate `base` as a relative .glsl path inside SHADERS_DIR.

    Each path component must be a plain name (no '..', no absolute paths or
    drive letters, no backslashes) and the file must end in .glsl. The
    resolved path (after following symlinks) must stay inside SHADERS_DIR.
    Raises HTTP 400 otherwise.
    """
    parts = base.split("/") if base else []
    if not parts or not all(_SAFE_PART.match(p) for p in parts):
        raise HTTPException(status_code=400, detail="invalid shader name")
    if not parts[-1].lower().endswith(".glsl"):
        raise HTTPException(status_code=400, detail="shader must be a .glsl file")
    root = SHADERS_DIR.resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="base outside shaders directory")
    if candidate.suffix.lower() != ".glsl":
        raise HTTPException(status_code=400, detail="shader must be a .glsl file")
    return candidate


@router.post("/apply")
def shader_apply(body: ApplyRequest) -> dict:
    if not body.glsl.strip():
        raise HTTPException(status_code=400, detail="glsl is empty")

    candidate = _resolve_base(body.base)

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"base shader not found: {body.base}")

    if body.mode == "sibling":
        target = candidate.with_name(f"{candidate.stem}_reactive.glsl")
    else:
        target = candidate

    _atomic_write(target, body.glsl)
    rel = target.relative_to(SHADERS_DIR.resolve()).as_posix()
    return {"path": f"shaders/{rel}"}
