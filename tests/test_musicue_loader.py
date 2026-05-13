import hashlib
import json
import logging
from pathlib import Path

import pytest

from cedartoy.musicue import (
    BundleLoadResult,
    compute_audio_sha256,
    discover_bundle_path,
    load_for_audio,
)


def _audio(tmp_path: Path, name: str = "song.wav") -> Path:
    p = tmp_path / name
    p.write_bytes(b"fake-audio")
    return p


def _bundle(path: Path, source_sha256: str = "x" * 64) -> Path:
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "source_sha256": source_sha256,
        "duration_sec": 1.0, "fps": 24.0,
        "tempo": {"bpm_global": 120.0, "bpm_curve": [], "time_signature": [4, 4]},
        "beats": [], "sections": [], "drums": {}, "midi": {},
        "midi_energy": {}, "stems_energy": {},
        "global_energy": {"hop_sec": 0.04, "values": []},
        "cuesheet": {"schema_version": "1.2", "source_sha256": source_sha256,
                     "grammar": "concert_visuals", "duration_sec": 1.0, "fps": 24.0,
                     "drop_frame": False, "tempo_map": [], "tracks": []},
    }))
    return path


def test_discover_sibling(tmp_path):
    audio = _audio(tmp_path)
    bundle = _bundle(tmp_path / "song.musicue.json")
    assert discover_bundle_path(audio) == bundle


def test_discover_none_when_missing(tmp_path):
    assert discover_bundle_path(_audio(tmp_path)) is None


def test_compute_audio_sha256(tmp_path):
    audio = _audio(tmp_path)
    assert compute_audio_sha256(audio) == hashlib.sha256(audio.read_bytes()).hexdigest()


def test_load_for_audio_sha_match(tmp_path):
    audio = _audio(tmp_path)
    sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    _bundle(tmp_path / "song.musicue.json", source_sha256=sha)
    result = load_for_audio(audio)
    assert isinstance(result, BundleLoadResult)
    assert result.bundle is not None
    assert result.sha_match is True


def test_load_for_audio_sha_mismatch_warns(tmp_path, caplog):
    audio = _audio(tmp_path)
    _bundle(tmp_path / "song.musicue.json", source_sha256="bad")
    with caplog.at_level(logging.WARNING):
        result = load_for_audio(audio)
    assert result.bundle is not None
    assert result.sha_match is False
    assert any("sha" in m.lower() for m in caplog.messages)


def test_load_for_audio_returns_empty_when_absent(tmp_path):
    result = load_for_audio(_audio(tmp_path))
    assert result.bundle is None
    assert result.path is None
    assert result.sha_match is False


def test_load_for_audio_override_path(tmp_path):
    audio = _audio(tmp_path)
    _bundle(tmp_path / "song.musicue.json", source_sha256="sibling")
    override = _bundle(tmp_path / "override.musicue.json", source_sha256="override")
    result = load_for_audio(audio, override_path=override)
    assert result.path == override
    assert result.bundle.source_sha256 == "override"
