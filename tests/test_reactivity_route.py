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
