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


def test_reactivity_prompt_rejects_path_traversal(client):
    """The shader query param must not escape the shaders directory.
    Regression: previously a relative `../README.md` would be read and
    embedded in the prompt."""
    resp = client.get("/api/reactivity/prompt", params={"shader": "../README.md"})
    assert resp.status_code == 400, resp.text
    assert "outside shaders directory" in resp.text


def test_reactivity_prompt_rejects_absolute_escape(client):
    """An absolute path that escapes the shaders directory should 400."""
    resp = client.get("/api/reactivity/prompt", params={"shader": "/etc/passwd"})
    assert resp.status_code == 400, resp.text


def test_reactivity_prompt_strips_shaders_prefix(client):
    """The frontend often sends the full 'shaders/foo.glsl' path; both
    forms should resolve to the same file."""
    resp = client.get("/api/reactivity/prompt", params={"shader": "shaders/auroras.glsl"})
    assert resp.status_code == 200


def test_reactivity_prompt_substitutes_every_cookbook_idiom(client):
    resp = client.get("/api/reactivity/prompt", params={"shader": "auroras.glsl"})
    p = resp.json()["prompt"]
    for name in ["noise_scale_breathe", "iteration_swell", "swirl_whip_on_kick",
                 "fold_strength_pulse", "kick_pulse_camera", "beat_pump_zoom",
                 "camera_rock_subtle", "hat_shimmer", "section_palette_shift",
                 "section_color_wash", "beat_phase_color_dance", "melodic_glow_tint",
                 "bar_anchored_strobe", "kick_displace"]:
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


def test_prompt_includes_bundle_health_when_audio_given(client, tmp_path):
    import json
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF....fake")
    bundle = {
        "schema_version": "1.0", "source_sha256": "x", "duration_sec": 2.0,
        "fps": 24.0, "tempo": {"bpm_global": 120.0, "time_signature": [4, 4]},
        "beats": [{"t": 0.0, "beat_in_bar": 0, "bar": 0, "is_downbeat": True}],
        "sections": [{"start": 0.0, "end": 2.0, "label": "verse", "energy_rank": 0.5}],
        "drums": {"kick": [{"t": 0.0, "strength": 0.9}], "hat": []},
        "midi": {}, "midi_energy": {}, "stems_energy": {},
        "global_energy": {"hop_sec": 0.5, "values": [0.2]}, "cuesheet": {},
    }
    audio.with_suffix("").with_suffix(".musicue.json").write_text(
        json.dumps(bundle), encoding="utf-8")

    r = client.get("/api/reactivity/prompt",
                   params={"shader": "auroras.glsl", "audio": str(audio)})
    assert r.status_code == 200, r.text
    p = r.json()["prompt"]
    assert "available MusiCue data" in p
    assert "kick(1)" in p              # one kick onset present
    assert "hat" in p                  # empty drum named

    # without audio, no health section
    r2 = client.get("/api/reactivity/prompt", params={"shader": "auroras.glsl"})
    assert "available MusiCue data" not in r2.json()["prompt"]
