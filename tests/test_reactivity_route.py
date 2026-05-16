"""HTTP tests for /api/reactivity/prompt."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_reactivity_prompt_returns_filled_template(client):
    resp = client.get("/api/reactivity/prompt", params={"shader": "auroras.glsl"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "prompt" in body
    p = body["prompt"]
    assert "Make this GLSL shader MusiCue-reactive" in p
    assert "kick_pulse_camera" in p
    assert "<paste" not in p
    assert "declared_uniforms" in body
    assert "missing_uniforms" in body
    assert isinstance(body["declared_uniforms"], list)
    assert isinstance(body["missing_uniforms"], list)


def test_reactivity_prompt_404_on_unknown_shader(client):
    resp = client.get("/api/reactivity/prompt", params={"shader": "nope.glsl"})
    assert resp.status_code == 404


def test_reactivity_prompt_strips_shaders_prefix(client):
    """The frontend often sends the full 'shaders/foo.glsl' path; both
    forms should resolve to the same file."""
    resp = client.get("/api/reactivity/prompt", params={"shader": "shaders/auroras.glsl"})
    assert resp.status_code == 200


def test_reactivity_prompt_substitutes_every_cookbook_idiom(client):
    resp = client.get("/api/reactivity/prompt", params={"shader": "auroras.glsl"})
    p = resp.json()["prompt"]
    for name in ["kick_pulse_camera", "beat_pump_zoom", "section_palette_shift",
                 "energy_brightness_lift", "bar_anchored_strobe",
                 "melodic_glow_tint", "hat_grain"]:
        assert name in p, f"prompt missing cookbook entry {name}"


def test_fixit_prompt_returns_markdown(client):
    """POST a broken shader + log; receive a fix-it prompt back."""
    from cedartoy.server.api.shader_apply import SHADERS_DIR
    base = SHADERS_DIR / "fixit_test_temp.glsl"
    base.write_text("void main(){gl_FragColor=vec4(0.0);}", encoding="utf-8")
    try:
        resp = client.post(
            "/api/reactivity/fixit-prompt",
            json={
                "base": "fixit_test_temp.glsl",
                "broken_glsl": "void main(){iKick;}",
                "gl_log": "ERROR: 0:1: 'iKick' : undeclared identifier",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        prompt = body["prompt"]
        assert "iKick" in prompt
        assert "undeclared identifier" in prompt
        assert "gl_FragColor=vec4(0.0)" in prompt
        assert "kick_pulse_camera" in prompt
        assert "fix the compile error" in prompt.lower()
    finally:
        base.unlink(missing_ok=True)


def test_fixit_prompt_404_when_base_missing(client):
    resp = client.post(
        "/api/reactivity/fixit-prompt",
        json={
            "base": "nope_xyz.glsl",
            "broken_glsl": "void main(){}",
            "gl_log": "anything",
        },
    )
    assert resp.status_code == 404
