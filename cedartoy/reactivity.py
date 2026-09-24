"""Helpers for the reactivity authoring workflow.

* parse_declared_uniforms — find which bundle uniforms a shader already
  declares, so the UI can show "declared X / missing Y".
* build_reactivity_prompt — substitute a shader + the cookbook into the
  prompt template, ready to copy into Claude.
* build_expose_knobs_prompt — "Expose knobs" prompt: turn constants into
  @params and suggest @mod routes for the modulation matrix.
"""
from __future__ import annotations

import re
from pathlib import Path

from .modulation import CURVES, MOD_SOURCES
from .musicue import MUSICAL_UNIFORMS

BUNDLE_UNIFORMS = (
    "iBpm", "iBeat", "iBar", "iSectionEnergy", "iSectionId", "iEnergy", "iChannel0",
) + tuple(MUSICAL_UNIFORMS)

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_UNIFORM_RE = re.compile(r"\buniform\s+\w+\s+(\w+)")

_COOKBOOK_SLOT = "<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>"
_SHADER_SLOT = "<paste the contents of your target shader.glsl here verbatim>"
_SOURCES_SLOT = "<sources>"
_CURVES_SLOT = "<curves>"


def _strip_comments(src: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", src))


def parse_declared_uniforms(src: str) -> set[str]:
    return set(_UNIFORM_RE.findall(_strip_comments(src)))


def build_reactivity_prompt(
    *,
    shader_src: str,
    template_path: Path,
    cookbook_path: Path,
    bundle_summary: str | None = None,
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
    out = template.replace(_COOKBOOK_SLOT, cookbook).replace(_SHADER_SLOT, shader_src)
    if bundle_summary:
        out += ("\n\n## This song's available MusiCue data\n"
                "Map reactivity only to data that exists below; do not react to "
                "empty/absent tracks.\n" + bundle_summary + "\n")
    return out


def build_expose_knobs_prompt(
    *,
    shader_src: str,
    template_path: Path,
    bundle_summary: str | None = None,
) -> str:
    """Fill the Expose-knobs template (shader, MOD_SOURCES, curves) and append
    the song's bundle health so suggested @mod routes use data that exists."""
    template = template_path.read_text(encoding="utf-8")
    for slot in (_SHADER_SLOT, _SOURCES_SLOT, _CURVES_SLOT):
        if slot not in template:
            raise ValueError(f"expose-knobs template missing slot: {slot!r}")
    out = (template
           .replace(_SOURCES_SLOT, ", ".join(f"`{s}`" for s in MOD_SOURCES))
           .replace(_CURVES_SLOT, ", ".join(f"`{c}`" for c in CURVES))
           .replace(_SHADER_SLOT, shader_src))
    if bundle_summary:
        out += ("\n\n## This song's available MusiCue data\n"
                "Suggest @mod routes only from sources backed by data below; "
                "sources for empty/absent tracks read 0.\n" + bundle_summary + "\n")
    return out


def build_fixit_prompt(
    *,
    broken_glsl: str,
    gl_log: str,
    original_glsl: str,
    cookbook: str,
    kind: str = "reactive",
) -> str:
    """Build a Claude-ready prompt asking it to fix a broken reactive variant.

    The shape mirrors build_reactivity_prompt: clearly-labeled sections so
    Claude can return a single fenced GLSL block. The directive is explicit
    about preserving the prior reactivity goals so iterations don't regress.

    ``kind="knobs"`` words it for an Expose-knobs attempt (``cookbook`` is
    then the knobs template, as guidance).
    """
    if kind == "knobs":
        return (
            "You exposed @param knobs on a CedarToy GLSL shader, but it "
            "failed to compile in WebGL2. Fix the compile error while keeping "
            "every exposed @param / @mod line and the original look at "
            "defaults.\n\n"
            "## Original shader\n```glsl\n"
            f"{original_glsl}\n```\n\n"
            "## Broken attempt\n```glsl\n"
            f"{broken_glsl}\n```\n\n"
            "## Compile error\n```\n"
            f"{gl_log}\n```\n\n"
            "## Expose-knobs guidance\n"
            f"{cookbook}\n\n"
            "## Instructions\n"
            "- Return ONE fenced ```glsl block containing the corrected shader.\n"
            "- Every `// @param` needs a matching `uniform float <name>;`.\n"
            "- Only fix the bug; don't add audio-reactive code.\n"
        )
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
