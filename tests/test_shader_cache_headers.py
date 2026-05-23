from fastapi import FastAPI
from fastapi.testclient import TestClient

from cedartoy.server.api.shaders import router, SHADERS_DIR


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api/shaders")
    return TestClient(app)


def test_get_shader_is_no_store():
    sample = next(SHADERS_DIR.rglob("*.glsl"))
    rel = sample.relative_to(SHADERS_DIR).as_posix()
    r = _client().get(f"/api/shaders/{rel}")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    assert "source" in r.json()
