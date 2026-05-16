"""Unit tests for the CedarToy project-folder loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cedartoy.project import (
    CedarToyProject,
    discover_audio_in_folder,
    STEM_NAMES,
)


def test_discover_audio_finds_song_wav(tmp_path):
    (tmp_path / "song.wav").write_bytes(b"")
    assert discover_audio_in_folder(tmp_path) == tmp_path / "song.wav"


def test_discover_audio_returns_none_when_missing(tmp_path):
    assert discover_audio_in_folder(tmp_path) is None


def test_discover_audio_prefers_song_wav_over_other_wavs(tmp_path):
    (tmp_path / "other.wav").write_bytes(b"")
    (tmp_path / "song.wav").write_bytes(b"")
    assert discover_audio_in_folder(tmp_path) == tmp_path / "song.wav"


def test_discover_audio_falls_back_to_first_wav(tmp_path):
    (tmp_path / "track.wav").write_bytes(b"")
    assert discover_audio_in_folder(tmp_path) == tmp_path / "track.wav"


def test_stem_names_constant():
    assert STEM_NAMES == ("drums", "bass", "vocals", "other")


def _write_silent_wav(path: Path) -> None:
    import numpy as np
    import soundfile as sf
    sf.write(str(path), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")


def _seed_minimal_project(folder: Path, *, with_bundle=True, with_manifest=True,
                          bundle_decoded_sha: str | None = None,
                          bundle_schema_version: str = "1.1") -> Path:
    """Create a minimal folder layout matching the MusiCue export contract.

    Defaults to schema 1.1 with decoded_audio_sha256 matching the written WAV
    (the "happy path" — real integrity check passes). Override
    bundle_decoded_sha to force a mismatch, or set bundle_schema_version="1.0"
    + bundle_decoded_sha=None to seed a legacy bundle.
    """
    from cedartoy.project import compute_audio_sha256
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "song.wav"
    _write_silent_wav(audio)
    if with_bundle:
        audio_sha = compute_audio_sha256(audio)
        doc = {
            "schema_version": bundle_schema_version,
            "source_sha256": audio_sha,
            "duration_sec": 0.25,
            "fps": 24.0,
            "tempo": {"bpm_global": 120.0},
            "beats": [],
            "sections": [],
            "drums": {},
            "midi": {},
            "midi_energy": {},
            "stems_energy": {},
            "global_energy": {"hop_sec": 0.04, "values": []},
            "cuesheet": {"schema_version": "1.0", "source_sha256": audio_sha,
                         "grammar": "concert_visuals", "duration_sec": 0.25},
        }
        if bundle_schema_version == "1.1":
            doc["decoded_audio_sha256"] = (
                bundle_decoded_sha if bundle_decoded_sha is not None else audio_sha
            )
        (folder / "song.musicue.json").write_text(json.dumps(doc))
    if with_manifest:
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "cedartoy-project/1",
            "audio_filename": "song.wav",
            "original_audio": "song.wav",
            "grammar": "concert_visuals",
            "musicue_version": "0.4.1-test",
            "exported_at": "2026-05-14T00:00:00Z",
        }))
    return audio


def test_load_project_resolves_folder(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "my_song"
    _seed_minimal_project(folder)
    proj = load_project(folder)
    assert proj.folder == folder.resolve()
    assert proj.audio_path == (folder / "song.wav").resolve() or \
           proj.audio_path == folder / "song.wav"
    assert proj.bundle_path is not None and proj.bundle_path.name == "song.musicue.json"
    assert proj.manifest is not None
    assert proj.manifest["grammar"] == "concert_visuals"
    assert proj.bundle_sha_matches_audio is True


def test_load_project_resolves_audio_file_path(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "my_song"
    _seed_minimal_project(folder)
    proj = load_project(folder / "song.wav")
    assert proj.folder == folder.resolve()
    assert proj.audio_path is not None and proj.audio_path.name == "song.wav"


def test_load_project_resolves_bundle_file_path(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "my_song"
    _seed_minimal_project(folder)
    proj = load_project(folder / "song.musicue.json")
    assert proj.folder == folder.resolve()
    assert proj.bundle_path is not None and proj.bundle_path.name == "song.musicue.json"


def test_load_project_legacy_folder_without_manifest(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "legacy"
    _seed_minimal_project(folder, with_manifest=False)
    proj = load_project(folder)
    assert proj.manifest is None
    assert proj.audio_path is not None
    assert proj.bundle_path is not None  # still loads


def test_load_project_audio_only(tmp_path):
    """Folder with audio but no bundle — raw-FFT-mode fallback."""
    from cedartoy.project import load_project
    folder = tmp_path / "audio_only"
    _seed_minimal_project(folder, with_bundle=False, with_manifest=False)
    proj = load_project(folder)
    assert proj.audio_path is not None
    assert proj.bundle_path is None
    assert proj.bundle_sha_matches_audio is None


def test_load_project_warns_on_sha_mismatch(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "mismatch"
    _seed_minimal_project(folder, bundle_decoded_sha="0" * 64)
    proj = load_project(folder)
    assert proj.bundle_sha_matches_audio is False
    assert any("audio has changed" in w.lower() for w in proj.warnings)


def test_load_project_legacy_bundle_1_0_skips_sha_check(tmp_path):
    """Bundle schema 1.0 (no decoded_audio_sha256): match=None, benign note, no warning."""
    from cedartoy.project import load_project
    folder = tmp_path / "legacy_bundle"
    _seed_minimal_project(folder, bundle_schema_version="1.0")
    proj = load_project(folder)
    assert proj.bundle_sha_matches_audio is None
    notes = " ".join(proj.warnings).lower()
    assert "integrity check unavailable" in notes
    assert "audio has changed" not in notes  # no false-positive warning


def test_load_project_includes_stems(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "with_stems"
    _seed_minimal_project(folder)
    (folder / "stems").mkdir()
    for name in ("drums", "bass", "vocals", "other"):
        _write_silent_wav(folder / "stems" / f"{name}.wav")
    proj = load_project(folder)
    assert set(proj.stems_paths) == {"drums", "bass", "vocals", "other"}
