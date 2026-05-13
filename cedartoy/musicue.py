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


_DEFAULT_ADSR = (0.0, 0.08, 0.0, 0.0)
# Attack=0 (instantaneous): visual impulses are sub-frame flashes; ramping
# from 0 over 5ms means a frame landing exactly on an event sees 0.


def _adsr_value(t_since: float, adsr: Tuple[float, float, float, float], strength: float) -> float:
    if t_since < 0:
        return 0.0
    a, d, s, _r = adsr
    if t_since < a:
        return strength * (t_since / a) if a > 0 else strength
    if t_since < a + d:
        progress = (t_since - a) / d if d > 0 else 1.0
        return strength * (1.0 - progress * (1.0 - s))
    return strength * s


def _sample_curve(curve: "StemEnergyCurve", t: float) -> float:
    if not curve.values or curve.hop_sec <= 0:
        return 0.0
    idx_f = t / curve.hop_sec
    i0 = int(idx_f)
    if i0 < 0:
        return float(curve.values[0])
    if i0 >= len(curve.values) - 1:
        return float(curve.values[-1])
    frac = idx_f - i0
    return float(curve.values[i0]) * (1.0 - frac) + float(curve.values[i0 + 1]) * frac


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
        self._drums: Dict[str, List[Tuple[float, float]]] = {
            cls: sorted([(o.t, o.strength) for o in events], key=lambda e: e[0])
            for cls, events in bundle.drums.items()
        }

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

    def _section_energy_at(self, t: float) -> float:
        for sec in self._sections:
            if sec.start <= t < sec.end:
                return sec.energy_rank
        return 0.0

    def _drum_pulses_at(self, t: float) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for cls, events in self._drums.items():
            value = 0.0
            for event_t, strength in events:
                if event_t > t:
                    break
                value += _adsr_value(t - event_t, _DEFAULT_ADSR, strength)
            out[cls] = min(1.0, max(0.0, value))
        return out

    def _curve_dict_at(self, curves: Dict[str, "StemEnergyCurve"], t: float) -> Dict[str, float]:
        return {k: _sample_curve(v, t) for k, v in curves.items()}

    def evaluate(self, frame_index: int) -> EvalFrame:
        t = frame_index / self.fps
        return EvalFrame(
            bpm=self._bpm_global,
            beat_phase=self._beat_phase_at(t),
            bar=self._bar_at(t),
            section_energy=self._section_energy_at(t),
            global_energy=_sample_curve(self.bundle.global_energy, t),
            drum_pulses=self._drum_pulses_at(t),
            midi_energy=self._curve_dict_at(self.bundle.midi_energy, t),
            stems_energy=self._curve_dict_at(self.bundle.stems_energy, t),
        )


_BIN_RANGES = {
    "low":     (0, 32),
    "low_mid": (32, 96),
    "mid_hi":  (96, 256),
    "high":    (256, 512),
}


def _hann_envelope(width: int) -> np.ndarray:
    if width <= 0:
        return np.zeros(0, dtype=np.float32)
    if width == 1:
        return np.array([1.0], dtype=np.float32)
    return np.hanning(width).astype(np.float32)


class MusicalSpectrumSynth:
    """Synthesize a 2x512 iChannel0 texture from an EvalFrame."""

    def __init__(self) -> None:
        self._envelopes = {
            name: _hann_envelope(end - start)
            for name, (start, end) in _BIN_RANGES.items()
        }

    def _add_range(self, row: np.ndarray, name: str, weight: float) -> None:
        if weight <= 0:
            return
        s, e = _BIN_RANGES[name]
        row[s:e] += self._envelopes[name] * weight

    def synthesize(self, frame: EvalFrame) -> np.ndarray:
        tex = np.zeros((2, 512), dtype=np.float32)
        row0 = tex[0]

        low = frame.drum_pulses.get("kick", 0.0)
        low_mid = frame.drum_pulses.get("snare", 0.0) + frame.drum_pulses.get("tom", 0.0)
        mid_hi = frame.drum_pulses.get("hat", 0.0) + frame.drum_pulses.get("cymbal", 0.0)
        high = frame.midi_energy.get("vocals", 0.0) + frame.midi_energy.get("other", 0.0)

        self._add_range(row0, "low", low)
        self._add_range(row0, "low_mid", low_mid)
        self._add_range(row0, "mid_hi", mid_hi)
        self._add_range(row0, "high", high)

        row0 += 0.1 * float(frame.section_energy)
        np.clip(row0, 0.0, 1.0, out=row0)

        wave = 0.5 + 0.5 * float(frame.global_energy) * math.sin(
            2.0 * math.pi * float(frame.beat_phase)
        )
        tex[1, :] = max(0.0, min(1.0, wave))
        return tex


@dataclass
class BundleLoadResult:
    bundle: Optional[MusiCueBundle] = None
    path: Optional[Path] = None
    sha_match: bool = False


def discover_bundle_path(audio_path: Path) -> Optional[Path]:
    """Return sibling ``<audio_stem>.musicue.json`` if it exists."""
    candidate = audio_path.with_suffix("").with_suffix(".musicue.json")
    return candidate if candidate.exists() else None


def compute_audio_sha256(audio_path: Path) -> str:
    h = hashlib.sha256()
    with open(audio_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_for_audio(
    audio_path: Path,
    override_path: Optional[Path] = None,
) -> BundleLoadResult:
    target = override_path if override_path is not None else discover_bundle_path(audio_path)
    if target is None:
        _logger.info("No MusiCue bundle for %s; rendering with raw FFT.", audio_path)
        return BundleLoadResult()

    bundle = load_bundle(target)
    audio_sha = compute_audio_sha256(audio_path)
    sha_match = bundle.source_sha256 == audio_sha
    if not sha_match:
        _logger.warning(
            "Bundle %s sha256=%s does not match audio %s sha=%s; using anyway.",
            target, bundle.source_sha256, audio_path, audio_sha,
        )
    return BundleLoadResult(bundle=bundle, path=target, sha_match=sha_match)
