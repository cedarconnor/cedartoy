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


def build_fixit_prompt(
    *,
    broken_glsl: str,
    gl_log: str,
    original_glsl: str,
    cookbook: str,
) -> str:
    """Build a Claude-ready prompt asking it to fix a broken reactive variant.

    The shape mirrors build_reactivity_prompt: clearly-labeled sections so
    Claude can return a single fenced GLSL block. The directive is explicit
    about preserving the prior reactivity goals so iterations don't regress.
    """
    return (
        "You wrote a reactive variant of a CedarToy GLSL shader, but it "
        "failed to compile in WebGL2. Fix the compile error while preserving "
        "the reactivity goals from the previous prompt.\n\n"
        "## Original shader\n```glsl\n"
        f"{original_glsl}\n```\n\n"
        "## Broken attempt\n```glsl\n"
        f"{broken_glsl}\n```\n\n"
        "## Compile error\n```\n"
        f"{gl_log}\n```\n\n"
        "## Reactivity cookbook\n"
        f"{cookbook}\n\n"
        "## Instructions\n"
        "- Return ONE fenced ```glsl block containing the corrected shader.\n"
        "- Keep the structure of the original; only fix the bug introduced "
        "by the reactive retrofit.\n"
        "- Preserve every reactivity idiom from the broken attempt that "
        "wasn't the actual source of the error.\n"
    )
