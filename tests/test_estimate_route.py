"""HTTP tests for /api/render/estimate."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_estimate_returns_payload(client):
    resp = client.post("/api/render/estimate", json={
        "shader_basename": "auroras",
        "width": 1920, "height": 1080,
        "fps": 60, "duration_sec": 10.0,
        "tile_count": 1, "ss_scale": 1.0,
        "format": "png", "bit_depth": 8,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_frames"] == 600
    assert body["total_seconds"] > 0
    assert body["output_bytes"] > 0
    assert isinstance(body["history_hit"], bool)
    assert isinstance(body["exceeds_time_threshold_1h"], bool)
    assert isinstance(body["exceeds_size_threshold_50gb"], bool)


def test_estimate_400_on_unknown_format(client):
    resp = client.post("/api/render/estimate", json={
        "shader_basename": "x", "width": 100, "height": 100,
        "fps": 60, "duration_sec": 1.0, "tile_count": 1, "ss_scale": 1.0,
        "format": "tiff", "bit_depth": 8,
    })
    assert resp.status_code == 400
