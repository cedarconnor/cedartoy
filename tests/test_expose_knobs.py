"""'Expose knobs ▸' authoring prompt: template, builder, endpoint, and the
reused paste-back (apply) + fix-it loop."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from cedartoy.modulation import CURVES, MOD_SOURCES
from cedartoy.reactivity import build_expose_knobs_prompt, build_fixit_prompt
from cedartoy.server.app import app
from tests.test_musical_signals import _bundle

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs/reactivity/EXPOSE_KNOBS_PROMPT.md"
SHADERS_DIR = ROOT / "shaders"


@pytest.fixture
def client():
    return TestClient(app)


def test_builder_fills_slots_and_appends_health():
    out = build_expose_knobs_prompt(shader_src="void mainImage(){/*MARK*/}",
                                    template_path=TEMPLATE,
                                    bundle_summary="- beats: 30 (present)")
    assert "Expose this shader's 4–8 most expressive constants" in out
    assert "Don't write audio-reactive code" in out
    assert "/*MARK*/" in out and "<paste" not in out
    assert "<sources>" not in out and "<curves>" not in out
    for s in MOD_SOURCES:
        assert f"`{s}`" in out
    for c in CURVES:
        assert f"`{c}`" in out
    assert "@mod" in out and "@param" in out
    assert out.rstrip().endswith("- beats: 30 (present)")


def test_builder_rejects_template_without_slots(tmp_path):
    bad = tmp_path / "t.md"
    bad.write_text("no slots here", encoding="utf-8")
    with pytest.raises(ValueError):
        build_expose_knobs_prompt(shader_src="x", template_path=bad)


def test_knobs_prompt_endpoint(client):
    r = client.get("/api/reactivity/knobs-prompt", params={"shader": "shaders/auroras.glsl"})
    assert r.status_code == 200, r.text
    p = r.json()["prompt"]
    assert "Expose this shader's" in p and "triNoise2d" in p
    assert "This song's available MusiCue data" not in p
    assert client.get("/api/reactivity/knobs-prompt",
                      params={"shader": "../README.md"}).status_code == 400
    assert client.get("/api/reactivity/knobs-prompt",
                      params={"shader": "nope.glsl"}).status_code == 404


def test_knobs_prompt_includes_bundle_health_for_loaded_project(client, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    audio = folder / "song.wav"
    sf.write(str(audio), np.zeros(4410, dtype="float32"), 44100, subtype="PCM_16")
    (folder / "song.musicue.json").write_text(_bundle().model_dump_json(), encoding="utf-8")
    # Not loaded yet: the summary is silently omitted (path not allowed).
    r = client.get("/api/reactivity/knobs-prompt",
                   params={"shader": "auroras.glsl", "audio": str(audio)})
    assert "This song's available MusiCue data" not in r.json()["prompt"]
    assert client.post("/api/project/load", json={"path": str(folder)}).status_code == 200
    r = client.get("/api/reactivity/knobs-prompt",
                   params={"shader": "auroras.glsl", "audio": str(audio)})
    p = r.json()["prompt"]
    assert "This song's available MusiCue data" in p
    assert "drums present: kick(2), snare(1)" in p


def test_fixit_prompt_knobs_kind(client):
    out = build_fixit_prompt(broken_glsl="B", gl_log="L", original_glsl="O",
                             cookbook="G", kind="knobs")
    assert "exposed @param knobs" in out and "## Expose-knobs guidance" in out
    assert "Reactivity cookbook" not in out
    r = client.post("/api/reactivity/fixit-prompt", json={
        "base": "auroras.glsl", "broken_glsl": "void main(){", "gl_log": "ERR",
        "kind": "knobs"})
    assert r.status_code == 200, r.text
    p = r.json()["prompt"]
    assert "exposed @param knobs" in p and "@mod" in p
    r = client.post("/api/reactivity/fixit-prompt", json={
        "base": "auroras.glsl", "broken_glsl": "x", "gl_log": "ERR"})
    assert "## Reactivity cookbook" in r.json()["prompt"]


def test_apply_knobs_writes_knobs_sibling(client):
    base = SHADERS_DIR / "test_knobs_temp.glsl"
    sibling = SHADERS_DIR / "test_knobs_temp_knobs.glsl"
    base.write_text("// original\n", encoding="utf-8")
    try:
        r = client.post("/api/shader/apply", json={
            "base": "test_knobs_temp.glsl", "glsl": "// knobs\n", "kind": "knobs"})
        assert r.status_code == 200, r.text
        assert r.json()["path"] == "shaders/test_knobs_temp_knobs.glsl"
        assert sibling.read_text(encoding="utf-8") == "// knobs\n"
        r = client.post("/api/shader/apply", json={
            "base": "test_knobs_temp.glsl", "glsl": "x", "kind": "evil"})
        assert r.status_code == 422
    finally:
        base.unlink(missing_ok=True)
        sibling.unlink(missing_ok=True)
