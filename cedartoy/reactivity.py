"""Helpers for the reactivity authoring workflow.

* parse_declared_uniforms — find which bundle uniforms a shader already
  declares, so the UI can show "declared X / missing Y".
* build_reactivity_prompt — substitute a shader + the cookbook into the
  prompt template, ready to copy into Claude.
"""
from __future__ import annotations

import re
from pathlib import Path

BUNDLE_UNIFORMS = (
    "iBpm", "iBeat", "iBar", "iSectionEnergy", "iEnergy", "iChannel0",
)

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_UNIFORM_RE = re.compile(r"\buniform\s+\w+\s+(\w+)")

_COOKBOOK_SLOT = "<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>"
_SHADER_SLOT = "<paste the contents of your target shader.glsl here verbatim>"


def _strip_comments(src: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", src))


def parse_declared_uniforms(src: str) -> set[str]:
    return set(_UNIFORM_RE.findall(_strip_comments(src)))


def build_reactivity_prompt(
    *,
    shader_src: str,
    template_path: Path,
    cookbook_path: Path,
) -> str:
    """Substitute cookbook + shader into the template's marked slots."""
    template = template_path.read_text(encoding="utf-8")
    cookbook = cookbook_path.read_text(encoding="utf-8")
    if _COOKBOOK_SLOT not in template:
        raise ValueError(
            f"prompt template missing cookbook slot: {_COOKBOOK_SLOT!r}"
        )
    if _SHADER_SLOT not in template:
        raise ValueError(
            f"prompt template missing shader slot: {_SHADER_SLOT!r}"
        )
    return template.replace(_COOKBOOK_SLOT, cookbook).replace(_SHADER_SLOT, shader_src)
