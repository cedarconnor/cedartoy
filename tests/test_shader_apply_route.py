"""HTTP tests for POST /api/shader/apply."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


SHADERS_DIR = Path(__file__).resolve().parent.parent / "shaders"


@pytest.fixture
def temp_shader():
    """Create a temp <name>.glsl in shaders/ and clean it + its _reactive sibling on teardown."""
    base_name = "test_apply_temp"
    base_path = SHADERS_DIR / f"{base_name}.glsl"
    base_path.write_text("// original\nvoid main() { gl_FragColor = vec4(1.0); }\n", encoding="utf-8")
    sibling = SHADERS_DIR / f"{base_name}_reactive.glsl"
    yield base_name, base_path, sibling
    base_path.unlink(missing_ok=True)
    sibling.unlink(missing_ok=True)


def test_shader_apply_sibling_writes_reactive_glsl(client, temp_shader):
    base_name, base_path, sibling = temp_shader
    glsl = "// reactive\nuniform float iEnergy;\nvoid main() {}\n"
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": glsl,
        "mode": "sibling",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["path"].endswith(f"{base_name}_reactive.glsl")
    assert sibling.read_text(encoding="utf-8") == glsl
    # Original untouched.
    assert "// original" in base_path.read_text(encoding="utf-8")


def test_shader_apply_overwrite_replaces_original(client, temp_shader):
    base_name, base_path, sibling = temp_shader
    glsl = "// overwritten\nvoid main() {}\n"
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": glsl,
        "mode": "overwrite",
    })
    assert resp.status_code == 200
    assert base_path.read_text(encoding="utf-8") == glsl
    assert not sibling.exists()


def test_shader_apply_rejects_empty_glsl(client, temp_shader):
    base_name, _, _ = temp_shader
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": "",
        "mode": "sibling",
    })
    assert resp.status_code == 400


def test_shader_apply_rejects_invalid_mode(client, temp_shader):
    base_name, _, _ = temp_shader
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": "void main(){}",
        "mode": "explode",
    })
    assert resp.status_code in (400, 422)


def test_shader_apply_404_when_base_missing(client):
    resp = client.post("/api/shader/apply", json={
        "base": "definitely_does_not_exist_5b8a.glsl",
        "glsl": "void main(){}",
        "mode": "sibling",
    })
    assert resp.status_code == 404


def test_shader_apply_rejects_path_traversal(client, temp_shader):
    """A base outside shaders/ via traversal must be rejected."""
    resp = client.post("/api/shader/apply", json={
        "base": "../etc/passwd",
        "glsl": "void main(){}",
        "mode": "sibling",
    })
    assert resp.status_code in (400, 403, 404)
