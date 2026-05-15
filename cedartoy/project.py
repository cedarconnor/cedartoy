"""Resolve a portable CedarToy project folder produced by MusiCue.

A project folder is the unit of portability — see the umbrella spec at
docs/superpowers/specs/2026-05-14-musicue-cedartoy-holistic-design.md.
Layout::

    <project>/
      song.wav                  audio
      song.musicue.json         bundle (optional in legacy folders)
      manifest.json             cedartoy-project/1 schema (optional)
      stems/                    drums.wav / bass.wav / vocals.wav / other.wav (optional)

load_project() accepts any path inside such a folder (the folder, the
audio file, the bundle, or a stem) and returns a CedarToyProject.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

STEM_NAMES = ("drums", "bass", "vocals", "other")


@dataclass
class CedarToyProject:
    folder: Path
    audio_path: Path | None
    bundle_path: Path | None
    stems_paths: dict[str, Path] = field(default_factory=dict)
    manifest: dict | None = None
    bundle_sha_matches_audio: bool | None = None
    warnings: list[str] = field(default_factory=list)


def discover_audio_in_folder(folder: Path) -> Path | None:
    """Find the canonical audio file in a project folder.

    Prefers song.wav. Falls back to the first .wav by name.
    """
    folder = Path(folder)
    song = folder / "song.wav"
    if song.exists():
        return song
    wavs = sorted(folder.glob("*.wav"))
    return wavs[0] if wavs else None
