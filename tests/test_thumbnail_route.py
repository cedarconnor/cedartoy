"""GET /api/shaders/thumbnail builds a valid RenderJob (no GL needed)."""
from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

import cedartoy.render as render_mod
from cedartoy.server.api import shaders as shaders_api
from cedartoy.server.app import app


def test_thumbnail_builds_complete_render_job(tmp_path, monkeypatch):
    monkeypatch.setattr(shaders_api, "THUMBNAIL_CACHE_DIR", tmp_path)
    captured = {}

    class FakeRenderer:
        def __init__(self, job):
            captured["job"] = job

        def render_frame(self, frame_idx, out_dir):
            import imageio.v3 as iio
            iio.imwrite(out_dir / "thumb_00000.png", np.zeros((4, 4, 3), np.uint8))

        def cleanup(self):
            pass

    monkeypatch.setattr(render_mod, "Renderer", FakeRenderer)
    shader = next(p for p in shaders_api.SHADERS_DIR.glob("*.glsl"))
    resp = TestClient(app).get("/api/shaders/thumbnail", params={"path": shader.name})
    assert resp.status_code == 200
    assert "job" in captured, "RenderJob construction failed"
    assert captured["job"].disk_streaming is False
