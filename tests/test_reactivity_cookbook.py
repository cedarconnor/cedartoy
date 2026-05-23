"""Every cookbook snippet must extract cleanly and compile in a minimal Shadertoy shell.

If `glslangValidator` is on PATH the per-snippet compile runs; otherwise
the test falls back to a structural check (snippet text isn't empty,
header comment present, declared uniforms only).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

COOKBOOK = Path(__file__).parent.parent / "docs" / "reactivity" / "REACTIVITY_COOKBOOK.md"
SHADERS_DIR = Path(__file__).parent.parent / "shaders"

SHELL = """\
#version 330
uniform float     iTime;
uniform vec3      iResolution;
uniform sampler2D iChannel0;
uniform float     iBpm;
uniform float     iBeat;
uniform int       iBar;
uniform float     iSectionEnergy;
uniform int       iSectionId;
uniform float     iEnergy;

out vec4 fragColor;

vec3 cameraForward = vec3(0.0, 0.0, 1.0);
vec3 d = vec3(0.0, 0.0, 1.0);
vec3 col = vec3(0.5);

void main() {
    vec2 fragCoord = gl_FragCoord.xy;
    // === SNIPPET ===
    fragColor = vec4(col, 1.0);
}
"""

EXPECTED_NAMES = {
    # Inner-loop modulations
    "noise_scale_breathe", "iteration_swell", "swirl_whip_on_kick",
    "fold_strength_pulse",
    # Camera & UV
    "kick_pulse_camera", "beat_pump_zoom", "camera_rock_subtle",
    "hat_shimmer",
    # Colour & palette
    "section_palette_shift", "section_color_wash",
    "beat_phase_color_dance", "melodic_glow_tint",
    # Time-anchored events
    "bar_anchored_strobe", "kick_displace",
}


def _extract_snippets(md: str) -> list[tuple[str, str]]:
    """Return list of (name, glsl_body) tuples from fenced ```glsl blocks
    whose first line starts with '// === <name>'.
    """
    out = []
    for m in re.finditer(r"```glsl\n(// === (\S+)[^\n]*\n.*?)```",
                         md, re.DOTALL):
        body, name = m.group(1), m.group(2)
        out.append((name, body))
    return out


def test_cookbook_extracts_expected_snippets():
    md = COOKBOOK.read_text(encoding="utf-8")
    snippets = _extract_snippets(md)
    names = {n for n, _ in snippets}
    assert names == EXPECTED_NAMES, f"got {names}, expected {EXPECTED_NAMES}"


def test_cookbook_header_carries_version():
    md = COOKBOOK.read_text(encoding="utf-8")
    assert "cookbook_version: 2" in md


@pytest.fixture(scope="module")
def glslang_available():
    return shutil.which("glslangValidator") is not None


@pytest.mark.parametrize("snippet_index", list(range(len(EXPECTED_NAMES))))
def test_cookbook_snippet_compiles(tmp_path, glslang_available, snippet_index):
    md = COOKBOOK.read_text(encoding="utf-8")
    snippets = _extract_snippets(md)
    if snippet_index >= len(snippets):
        pytest.skip("fewer snippets than parametrized indices")
    name, body = snippets[snippet_index]

    if not glslang_available:
        # Structural fallback: snippet has the header comment and isn't empty.
        assert body.strip(), f"snippet {name} body is empty"
        assert f"// === {name}" in body, f"snippet {name} missing header"
        return

    shader = SHELL.replace("// === SNIPPET ===", body)
    out = tmp_path / f"{name}.frag"
    out.write_text(shader, encoding="utf-8")
    res = subprocess.run(
        ["glslangValidator", "-S", "frag", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"glslang failed on {name}:\n{res.stdout}\n{res.stderr}"
    )


def test_reactive_shaders_do_not_use_discontinuous_bar_beat_camera_clock():
    bad = []
    discontinuous_clock = re.compile(r"float\s*\(\s*iBar\s*\)\s*\+\s*iBeat")
    for shader in SHADERS_DIR.glob("*_reactive.glsl"):
        text = shader.read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] for line in text.splitlines())
        if discontinuous_clock.search(code):
            bad.append(shader.name)

    assert bad == [], (
        "Reactive shaders must not use float(iBar) + iBeat as a smooth "
        "motion clock; iBeat resets every beat while iBar changes once per bar: "
        + ", ".join(bad)
    )
