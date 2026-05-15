"""Build a Claude-ready reactivity prompt from the current shader."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cedartoy.reactivity import (
    BUNDLE_UNIFORMS,
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
