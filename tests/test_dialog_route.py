"""HTTP tests for POST /api/dialog/pick-folder. tkinter is mocked so the
test suite doesn't pop a real dialog (and runs in headless CI)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_pick_folder_returns_chosen_path(client, tmp_path):
    chosen = str(tmp_path)
    with patch("cedartoy.server.api.dialog._ask_directory", return_value=chosen):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 200
    assert resp.json() == {"path": chosen}


def test_pick_folder_returns_null_path_when_user_cancels(client):
    # tkinter returns "" (empty string) when the user cancels.
    with patch("cedartoy.server.api.dialog._ask_directory", return_value=""):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 200
    assert resp.json() == {"path": None}


def test_pick_folder_accepts_initial_dir(client, tmp_path):
    chosen = str(tmp_path / "deeper")
    with patch("cedartoy.server.api.dialog._ask_directory", return_value=chosen) as m:
        resp = client.post(
            "/api/dialog/pick-folder",
            json={"initial_dir": str(tmp_path)},
        )
    assert resp.status_code == 200
    assert resp.json() == {"path": chosen}
    # _ask_directory was called with the requested initial dir
    m.assert_called_once_with(initial_dir=str(tmp_path))


def test_pick_folder_503_when_no_display(client):
    # tkinter raises TclError when there's no display. We surface 503.
    tk = pytest.importorskip("tkinter")
    with patch(
        "cedartoy.server.api.dialog._ask_directory",
        side_effect=tk.TclError("no display name and no $DISPLAY environment variable"),
    ):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 503
    assert "display" in resp.json()["detail"].lower()


def test_pick_folder_503_when_tkinter_missing(client):
    from cedartoy.server.api.dialog import DialogUnavailable
    with patch(
        "cedartoy.server.api.dialog._ask_directory",
        side_effect=DialogUnavailable("tkinter is not installed"),
    ):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 503


def test_open_folder_reveals_existing_dir(client, tmp_path):
    """Happy path: existing folder -> 200, OS shell called with that path."""
    with patch("cedartoy.server.api.dialog._reveal_in_file_manager") as m:
        resp = client.post("/api/dialog/open-folder", json={"path": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json()["opened"] == str(tmp_path)
    m.assert_called_once()


def test_open_folder_404_when_missing(client, tmp_path):
    resp = client.post("/api/dialog/open-folder", json={"path": str(tmp_path / "nope")})
    assert resp.status_code == 404


def test_open_folder_400_when_not_a_directory(client, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hi")
    resp = client.post("/api/dialog/open-folder", json={"path": str(f)})
    assert resp.status_code == 400
