"""MusiCue bundle ingestion for CedarToy.

Mirrors the subset of MusiCue's bundle schema that CedarToy consumes. The
embedded cuesheet stays as a loose ``dict[str, Any]`` — CedarToy never
introspects it in Phase 1.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field, ValidationError

SUPPORTED_SCHEMA_MAJOR = 1
_logger = logging.getLogger(__name__)


class UnsupportedSchemaError(ValueError):
    """Raised when a bundle's schema major version isn't supported."""


# ---- Schema mirror (lean — only fields CedarToy reads) ----

class TempoInfo(BaseModel):
    bpm_global: float
    bpm_curve: List[Dict[str, float]] = Field(default_factory=list)
    time_signature: List[int] = Field(default_factory=lambda: [4, 4])


class BeatEvent(BaseModel):
    t: float
    beat_in_bar: int
    bar: int
    is_downbeat: bool
    confidence: float = 1.0


class SectionBundleEntry(BaseModel):
    start: float
    end: float
    label: str
    confidence: float = 1.0
    lufs: Optional[float] = None
    energy_rank: float = 0.0
    spectral_flux_rise: Optional[float] = None


class DrumOnset(BaseModel):
    t: float
    strength: float
    confidence: Optional[float] = None


class MidiNoteBundle(BaseModel):
    t: float
    duration: float
    pitch: int
    velocity: int


class StemEnergyCurve(BaseModel):
    hop_sec: float
    values: List[float] = Field(default_factory=list)


class MusiCueBundle(BaseModel):
    schema_version: str
    source_sha256: str
    duration_sec: float
    fps: float = 24.0

    tempo: TempoInfo
    beats: List[BeatEvent] = Field(default_factory=list)
    sections: List[SectionBundleEntry] = Field(default_factory=list)

    drums: Dict[str, List[DrumOnset]] = Field(default_factory=dict)
    midi: Dict[str, List[MidiNoteBundle]] = Field(default_factory=dict)
    midi_energy: Dict[str, StemEnergyCurve] = Field(default_factory=dict)
    stems_energy: Dict[str, StemEnergyCurve] = Field(default_factory=dict)
    global_energy: StemEnergyCurve

    cuesheet: Dict[str, Any]


# ---- Loader ----

def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def load_bundle(path: Path) -> MusiCueBundle:
    """Load + validate a MusiCue bundle JSON. Hard-fails on major-version mismatch."""
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Bundle {path} is not valid JSON: {exc}") from exc

    version = str(data.get("schema_version", "0.0"))
    if _major(version) != SUPPORTED_SCHEMA_MAJOR:
        raise UnsupportedSchemaError(
            f"Bundle schema {version} is not supported "
            f"(CedarToy expects major {SUPPORTED_SCHEMA_MAJOR}). "
            "Re-export with current MusiCue: `musicue export-bundle <audio>`."
        )
    try:
        return MusiCueBundle.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Bundle {path} failed validation: {exc}") from exc


@dataclass
class EvalFrame:
    bpm: float = 0.0
    beat_phase: float = 0.0
    bar: int = 0
    section_energy: float = 0.0
    global_energy: float = 0.0
    drum_pulses: Dict[str, float] = field(default_factory=dict)
    midi_energy: Dict[str, float] = field(default_factory=dict)
    stems_energy: Dict[str, float] = field(default_factory=dict)


class BundleEvaluator:
    def __init__(self, bundle: MusiCueBundle, fps: float):
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.bundle = bundle
        self.fps = fps
        self._bpm_global = bundle.tempo.bpm_global
        self._beat_times = [b.t for b in bundle.beats]
        self._downbeats = [(b.t, b.bar) for b in bundle.beats if b.is_downbeat]
        self._sections = sorted(bundle.sections, key=lambda s: s.start)
        self._beats_per_bar = (
            bundle.tempo.time_signature[0]
            if bundle.tempo.time_signature else 4
        )

    def _beat_phase_at(self, t: float) -> float:
        times = self._beat_times
        if len(times) < 2:
            return 0.0
        idx = bisect.bisect_right(times, t) - 1
        if idx < 0 or idx >= len(times) - 1:
            return 0.0
        span = times[idx + 1] - times[idx]
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (t - times[idx]) / span))

    def _bar_at(self, t: float) -> int:
        if self._downbeats:
            bar = 0
            for time_t, b in self._downbeats:
                if time_t <= t:
                    bar = b
                else:
                    break
            return bar
        bps = self._bpm_global / 60.0
        return int(t * bps / max(1, self._beats_per_bar))

    def evaluate(self, frame_index: int) -> EvalFrame:
        t = frame_index / self.fps
        return EvalFrame(
            bpm=self._bpm_global,
            beat_phase=self._beat_phase_at(t),
            bar=self._bar_at(t),
        )
