"""POST /api/config/save may only write .yaml/.yml files inside configs/."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"


@pytest.fixture
def client():
    return TestClient(app)


def test_config_save_writes_inside_configs(client):
    target = CONFIGS_DIR / "zz_test_save_tmp.yaml"
    try:
        resp = client.post("/api/config/save",
                           params={"filepath": "zz_test_save_tmp.yaml"},
                           json={"config": {"width": 64}})
        assert resp.status_code == 200, resp.text
        assert Path(resp.json()["path"]) == target.resolve()
        assert "width: 64" in target.read_text()
    finally:
        target.unlink(missing_ok=True)


@pytest.mark.parametrize("filepath,status", [
    ("../cedartoy/evil.yaml", 403),
    ("/tmp/evil.yaml", 403),
    ("notes.txt", 400),
    ("evil.py", 400),
])
def test_config_save_rejects_outside_or_wrong_type(client, filepath, status):
    resp = client.post("/api/config/save", params={"filepath": filepath},
                       json={"config": {"a": 1}})
    assert resp.status_code == status, resp.text
