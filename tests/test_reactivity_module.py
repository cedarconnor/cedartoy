"""Unit tests for cedartoy.reactivity."""
from __future__ import annotations

from pathlib import Path

import pytest

from cedartoy.reactivity import (
    BUNDLE_UNIFORMS,
    build_reactivity_prompt,
    parse_declared_uniforms,
)


def test_parse_finds_declared_uniforms():
    src = """
    uniform float iTime;
    uniform vec3  iResolution;
    uniform sampler2D iChannel0;
    uniform float iBpm;
    uniform float iEnergy;
    """
    declared = parse_declared_uniforms(src)
    assert "iTime" in declared
    assert "iBpm" in declared
    assert "iEnergy" in declared
    assert "iChannel0" in declared


def test_parse_ignores_uniforms_inside_comments():
    src = """
    // uniform float iBpm; commented out
    /* uniform float iBeat; */
    uniform float iEnergy;
    """
    declared = parse_declared_uniforms(src)
    assert "iEnergy" in declared
    assert "iBpm" not in declared
    assert "iBeat" not in declared


def test_bundle_uniforms_set_matches_spec():
    assert set(BUNDLE_UNIFORMS) == {
        "iBpm", "iBeat", "iBar", "iSectionEnergy", "iEnergy", "iChannel0",
    }


def test_build_prompt_substitutes_shader_and_cookbook(tmp_path):
    cookbook = tmp_path / "COOKBOOK.md"
    cookbook.write_text("# COOKBOOK\nentry 1\n")
    template = tmp_path / "PROMPT.md"
    template.write_text(
        "<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>\n"
        "<paste the contents of your target shader.glsl here verbatim>\n"
    )
    shader = "void main() { /* my shader */ }"
    out = build_reactivity_prompt(shader_src=shader,
                                  template_path=template,
                                  cookbook_path=cookbook)
    assert "# COOKBOOK" in out
    assert "/* my shader */" in out
    assert "<paste" not in out


def test_build_prompt_raises_when_template_missing_slot(tmp_path):
    cookbook = tmp_path / "COOKBOOK.md"
    cookbook.write_text("# COOKBOOK\n")
    template = tmp_path / "PROMPT.md"
    template.write_text("no slots here\n")
    with pytest.raises(ValueError, match="cookbook slot"):
        build_reactivity_prompt(shader_src="void main(){}",
                                template_path=template,
                                cookbook_path=cookbook)
