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
