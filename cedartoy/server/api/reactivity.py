"""Build a Claude-ready reactivity prompt from the current shader."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cedartoy.reactivity import (
    BUNDLE_UNIFORMS,
    build_fixit_prompt,
    build_reactivity_prompt,
    parse_declared_uniforms,
)

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHADERS_DIR = _REPO_ROOT / "shaders"
_PROMPT_PATH = _REPO_ROOT / "docs" / "reactivity" / "MUSICUE_REACTIVITY_PROMPT.md"
_COOKBOOK_PATH = _REPO_ROOT / "docs" / "reactivity" / "REACTIVITY_COOKBOOK.md"


@router.get("/prompt")
def reactivity_prompt(shader: str) -> dict:
    """Return the full prompt text + uniform introspection for the named shader."""
    # Accept either 'shaders/foo.glsl' or 'foo.glsl'.
    rel = shader
    for prefix in ("shaders/", "shaders\\"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    src_path = _SHADERS_DIR / rel
    if not src_path.exists() or not src_path.is_file():
        raise HTTPException(status_code=404, detail=f"shader not found: {shader}")

    src = src_path.read_text(encoding="utf-8")
    declared = parse_declared_uniforms(src)
    bundle_declared = sorted(u for u in BUNDLE_UNIFORMS if u in declared)
    missing = sorted(u for u in BUNDLE_UNIFORMS if u not in declared)

    prompt = build_reactivity_prompt(
        shader_src=src,
        template_path=_PROMPT_PATH,
        cookbook_path=_COOKBOOK_PATH,
    )

    return {
        "shader": shader,
        "declared_uniforms": bundle_declared,
        "missing_uniforms": missing,
        "prompt": prompt,
    }


class FixitRequest(BaseModel):
    base: str
    broken_glsl: str
    gl_log: str


@router.post("/fixit-prompt")
def fixit_prompt(body: FixitRequest) -> dict:
    """Build a Claude-ready prompt asking for a fix to a broken reactive variant."""
    candidate = (_SHADERS_DIR / body.base).resolve()
    try:
        candidate.relative_to(_SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="base outside shaders directory")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"base shader not found: {body.base}")

    prompt = build_fixit_prompt(
        broken_glsl=body.broken_glsl,
        gl_log=body.gl_log,
        original_glsl=candidate.read_text(encoding="utf-8"),
        cookbook=_COOKBOOK_PATH.read_text(encoding="utf-8"),
    )
    return {"prompt": prompt}
