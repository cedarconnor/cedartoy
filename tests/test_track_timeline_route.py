import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cedartoy.server.api.reactivity import router


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api/reactivity")
    return TestClient(app)


def _write_bundle(audio: Path):
    bundle = {
        "schema_version": "1.0", "source_sha256": "x", "duration_sec": 4.0,
        "fps": 24.0, "tempo": {"bpm_global": 120.0, "time_signature": [4, 4]},
        "beats": [{"t": 0.0, "beat_in_bar": 0, "bar": 0, "is_downbeat": True}],
        "sections": [{"start": 0.0, "end": 4.0, "label": "verse",
                      "energy_rank": 0.5}],
        "drums": {"kick": [{"t": 0.0, "strength": 0.9}]},
        "midi": {}, "midi_energy": {}, "stems_energy": {},
        "global_energy": {"hop_sec": 0.5, "values": [0.2, 0.4]},
        "cuesheet": {},
    }
    audio.with_suffix("").with_suffix(".musicue.json").write_text(
        json.dumps(bundle), encoding="utf-8")


def test_track_timeline_returns_tracks_and_health(tmp_path):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF....fake")
    _write_bundle(audio)

    r = _client().get("/api/reactivity/track-timeline",
                      params={"audio": str(audio)})
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"]["drums.kick"]["onsets"][0]["strength"] == 0.9
    assert data["health"]["beats"]["count"] == 1
    assert data["bands"] == ["low", "low_mid", "mid_hi", "high"]


def test_track_timeline_404_when_no_bundle(tmp_path):
    audio = tmp_path / "nobundle.wav"
    audio.write_bytes(b"RIFF....fake")
    r = _client().get("/api/reactivity/track-timeline",
                      params={"audio": str(audio)})
    assert r.status_code == 404
