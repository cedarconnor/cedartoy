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

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

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


def compute_audio_sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def _resolve_folder(target: Path) -> Path:
    """Treat target as the project folder if it's a directory; else its parent."""
    target = Path(target).resolve()
    return target if target.is_dir() else target.parent


def load_project(target: Path) -> CedarToyProject:
    """Resolve any path inside a project folder to a CedarToyProject.

    Accepts a folder, an audio file, a bundle file, or a stem file. Walks
    up to the containing folder, locates audio/bundle/manifest/stems, and
    cross-checks the bundle sha against the audio.
    """
    folder = _resolve_folder(Path(target))
    warnings: list[str] = []

    audio_path = discover_audio_in_folder(folder)
    bundle_path: Path | None = folder / "song.musicue.json"
    if not bundle_path.exists():
        bundle_path = None

    manifest: dict | None = None
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            warnings.append(f"manifest.json unreadable: {e}")
            manifest = None

    stems_paths: dict[str, Path] = {}
    stems_dir = folder / "stems"
    if stems_dir.is_dir():
        for name in STEM_NAMES:
            p = stems_dir / f"{name}.wav"
            if p.exists():
                stems_paths[name] = p

    sha_match: bool | None = None
    if audio_path is not None and bundle_path is not None:
        try:
            audio_sha = compute_audio_sha256(audio_path)
            bundle_doc = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle_sha = bundle_doc.get("source_sha256")
            sha_match = audio_sha == bundle_sha
            if not sha_match:
                warnings.append(
                    f"bundle source_sha256 ({bundle_sha[:12] if bundle_sha else '?'}…) "
                    f"does not match audio sha ({audio_sha[:12]}…); using anyway"
                )
        except Exception as e:
            warnings.append(f"sha check failed: {e}")

    return CedarToyProject(
        folder=folder,
        audio_path=audio_path,
        bundle_path=bundle_path,
        stems_paths=stems_paths,
        manifest=manifest,
        bundle_sha_matches_audio=sha_match,
        warnings=warnings,
    )
