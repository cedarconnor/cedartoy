"""HTTP tests for the project-load endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def _seed(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "song.wav"
    sf.write(str(audio), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    from cedartoy.project import compute_audio_sha256
    sha = compute_audio_sha256(audio)
    (folder / "song.musicue.json").write_text(json.dumps({
        "schema_version": "1.0", "source_sha256": sha, "duration_sec": 0.25,
        "fps": 24.0, "tempo": {"bpm_global": 120.0}, "beats": [],
        "sections": [], "drums": {}, "midi": {}, "midi_energy": {},
        "stems_energy": {}, "global_energy": {"hop_sec": 0.04, "values": []},
        "cuesheet": {"schema_version": "1.0", "source_sha256": sha,
                     "grammar": "concert_visuals", "duration_sec": 0.25},
    }))
    (folder / "manifest.json").write_text(json.dumps({
        "schema": "cedartoy-project/1", "audio_filename": "song.wav",
        "original_audio": "song.wav", "grammar": "concert_visuals",
        "musicue_version": "0.4.1-test", "exported_at": "2026-05-14T00:00:00Z",
    }))
    return audio


def test_project_load_returns_project(client, tmp_path):
    folder = tmp_path / "song"
    _seed(folder)
    resp = client.post("/api/project/load", json={"path": str(folder)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["folder"].lower() == str(folder.resolve()).lower()
    assert body["audio_path"].endswith("song.wav")
    assert body["bundle_path"].endswith("song.musicue.json")
    assert body["manifest"]["grammar"] == "concert_visuals"
    assert body["bundle_sha_matches_audio"] is True
    assert body["warnings"] == []


def test_project_load_404_when_path_missing(client, tmp_path):
    resp = client.post("/api/project/load",
                       json={"path": str(tmp_path / "nope")})
    assert resp.status_code == 404


def test_project_load_resolves_audio_path(client, tmp_path):
    folder = tmp_path / "song"
    audio = _seed(folder)
    resp = client.post("/api/project/load", json={"path": str(audio)})
    assert resp.status_code == 200
    assert resp.json()["folder"].lower() == str(folder.resolve()).lower()
