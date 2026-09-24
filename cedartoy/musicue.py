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
from pydantic import BaseModel, Field, ValidationError, field_validator

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
    # Schema 1.3 (optional; absent in 1.0-1.2 bundles).
    phrase_id: Optional[int] = None
    phrase_position: Optional[int] = None   # bar index within phrase, 0-based
    phrase_length: Optional[int] = None     # bars in phrase
    is_fill: bool = False


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
    # Schema 1.3: dense, pre-normalized (0..1) control curves, e.g.
    # energy_fast / brightness / build / onset_density. Missing = absent.
    controls: Dict[str, StemEnergyCurve] = Field(default_factory=dict)

    cuesheet: Dict[str, Any]

    @field_validator("controls", "stems_energy", "midi_energy", "drums",
                     "midi", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return {} if value is None else value


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


# ---- Drum envelope shaping ----
#
# Instant attack + exponential decay whose time constant is a fraction of the
# LOCAL beat period, so hits breathe with the tempo instead of a fixed 80 ms
# blip. Default: decays to ~10% after half a beat, i.e.
# tau = ENV_DECAY_BEATS * beat_period / ln(1 / ENV_DECAY_TO), clamped to
# [ENV_TAU_MIN, ENV_TAU_MAX]. The exponential is floored at ENV_FLOOR and
# renormalised so each envelope reaches exactly 0 after a finite tail
# (tau * ln(1/ENV_FLOOR)) — only events inside that tail need summing.
ENV_DECAY_BEATS = 0.5
ENV_DECAY_TO = 0.1
ENV_TAU_MIN = 0.06
ENV_TAU_MAX = 0.4
ENV_FLOOR = 1e-3
_ENV_TAIL_K = math.log(1.0 / ENV_FLOOR)
_ENV_MAX_TAIL = ENV_TAU_MAX * _ENV_TAIL_K

# iTimeToNextSection when there is no upcoming section (or no bundle / muted).
NO_NEXT_SECTION = 1000.0


def envelope_tau(beat_period: float) -> float:
    """Exponential time constant for a drum envelope at the given beat period."""
    if not (beat_period > 0) or not math.isfinite(beat_period):
        beat_period = 0.5
    tau = ENV_DECAY_BEATS * beat_period / math.log(1.0 / ENV_DECAY_TO)
    return max(ENV_TAU_MIN, min(ENV_TAU_MAX, tau))


def envelope_value(t_since: float, tau: float, strength: float) -> float:
    """Instant-attack exponential decay, reaching exactly 0 after the tail."""
    if t_since < 0 or tau <= 0:
        return 0.0
    e = math.exp(-t_since / tau)
    if e <= ENV_FLOOR:
        return 0.0
    return strength * (e - ENV_FLOOR) / (1.0 - ENV_FLOOR)


def _sample_curve(curve: Optional["StemEnergyCurve"], t: float) -> float:
    if curve is None or not curve.values or not (curve.hop_sec > 0):
        return 0.0
    idx_f = t / curve.hop_sec
    if idx_f <= 0:
        return float(curve.values[0])
    i0 = int(idx_f)
    if i0 >= len(curve.values) - 1:
        return float(curve.values[-1])
    frac = idx_f - i0
    return float(curve.values[i0]) * (1.0 - frac) + float(curve.values[i0 + 1]) * frac


def _curve_ok(curve: Optional["StemEnergyCurve"]) -> bool:
    return curve is not None and bool(curve.values) and curve.hop_sec > 0


def _strictly_increasing(times: List[float]) -> List[int]:
    """Indices of a strictly increasing subsequence (drops dupes/out-of-order)."""
    keep: List[int] = []
    last = -math.inf
    for i, t in enumerate(times):
        if math.isfinite(t) and t > last:
            keep.append(i)
            last = t
    return keep


class _Grid:
    """A monotonic event grid (beats or downbeats) → continuous count clock.

    count(t) is index + phase between events, linearly extrapolated before
    the first / after the last event with the nearest interval (or
    ``fallback_period`` when fewer than two events exist).
    """

    def __init__(self, times: List[float], fallback_period: float):
        self.times = times
        self.fallback = fallback_period if fallback_period > 0 else 0.5

    def __len__(self) -> int:
        return len(self.times)

    def period_at(self, t: float) -> float:
        ts = self.times
        if len(ts) < 2:
            return self.fallback
        idx = bisect.bisect_right(ts, t) - 1
        idx = max(0, min(idx, len(ts) - 2))
        return ts[idx + 1] - ts[idx]

    def count(self, t: float) -> float:
        ts = self.times
        n = len(ts)
        if n == 0:
            return t / self.fallback
        if n == 1:
            return (t - ts[0]) / self.fallback
        if t < ts[0]:
            return (t - ts[0]) / (ts[1] - ts[0])
        if t >= ts[-1]:
            return (n - 1) + (t - ts[-1]) / (ts[-1] - ts[-2])
        idx = bisect.bisect_right(ts, t) - 1
        return idx + (t - ts[idx]) / (ts[idx + 1] - ts[idx])


def _fract(x: float) -> float:
    f = x - math.floor(x)
    return 0.0 if f >= 1.0 else f


@dataclass
class EvalFrame:
    bpm: float = 0.0
    beat_phase: float = 0.0
    bar: int = 0
    section_energy: float = 0.0
    section_id: int = 0
    global_energy: float = 0.0
    drum_pulses: Dict[str, float] = field(default_factory=dict)
    midi_energy: Dict[str, float] = field(default_factory=dict)
    stems_energy: Dict[str, float] = field(default_factory=dict)
    # ---- Musical-structure signals (schema-1.3 era; all degrade to 1.0) ----
    time: float = 0.0                 # video time asked for (pre av-offset)
    beat_clock: float = 0.0           # continuous beat count from the grid
    bar_phase: float = 0.0            # 0..1 within the bar
    phrase_phase: float = 0.0         # 0..1 within the phrase
    section_progress: float = 0.0     # 0..1 within the current section
    time_to_next_section: float = NO_NEXT_SECTION
    build: float = 0.0                # controls.build
    brightness: float = 0.0           # controls.brightness
    energy_fast: float = 0.0          # controls.energy_fast (fallback global)
    music_time: float = 0.0           # energy-warped clock, mean rate 1
    # Per-stem level feeding the stem.* iChannel0 bands: stems_energy when
    # present, else midi_energy. Empty → band sources fall back to midi_energy.
    stem_levels: Dict[str, float] = field(default_factory=dict)


# Sample grid for the iMusicTime integral.
_MUSIC_TIME_DT = 0.01


class BundleEvaluator:
    """Canonical evaluator: bundle + time → EvalFrame.

    ``av_offset_ms`` shifts every lookup: positive values make visuals land
    later (the music state shown at video time t is the one at t - offset).
    """

    def __init__(self, bundle: MusiCueBundle, fps: float, av_offset_ms: float = 0.0):
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.bundle = bundle
        self.fps = fps
        self.av_offset_sec = float(av_offset_ms or 0.0) / 1000.0
        self._bpm_global = bundle.tempo.bpm_global
        self._beats_per_bar = (
            bundle.tempo.time_signature[0]
            if bundle.tempo.time_signature and bundle.tempo.time_signature[0] > 0
            else 4
        )
        fallback_period = 60.0 / self._bpm_global if self._bpm_global > 0 else 0.5

        beats = sorted(bundle.beats, key=lambda b: b.t)
        keep = _strictly_increasing([b.t for b in beats])
        self._beats = [beats[i] for i in keep]
        self._beat_times = [b.t for b in self._beats]
        self._beat_grid = _Grid(self._beat_times, fallback_period)

        downs = [b for b in self._beats if b.is_downbeat]
        self._downbeat_events = downs
        self._downbeat_times = [b.t for b in downs]
        self._downbeat_bars = [b.bar for b in downs]
        self._bar_grid = _Grid(self._downbeat_times,
                               fallback_period * self._beats_per_bar)

        self._sections = sorted(bundle.sections, key=lambda s: s.start)
        self._section_starts = [s.start for s in self._sections]
        # Label → stable id, in first-seen order. Lets shaders distinguish
        # verse from chorus by index (each label maps to a unique int).
        self._section_label_ids: Dict[str, int] = {}
        for sec in self._sections:
            label = sec.label or ""
            if label not in self._section_label_ids:
                self._section_label_ids[label] = len(self._section_label_ids)

        # Drums: (times, strengths, taus) per class, sorted by time. Each
        # event's decay constant follows the local tempo at the event.
        self._drums: Dict[str, Tuple[List[float], List[float], List[float]]] = {}
        for cls, events in bundle.drums.items():
            evs = sorted(((o.t, o.strength) for o in events), key=lambda e: e[0])
            ts = [e[0] for e in evs]
            self._drums[cls] = (
                ts, [e[1] for e in evs],
                [envelope_tau(self._beat_grid.period_at(t)) for t in ts],
            )

        self._controls = {k: v for k, v in bundle.controls.items() if _curve_ok(v)}
        self._stems = {k: v for k, v in bundle.stems_energy.items() if _curve_ok(v)}
        self._music_time_table = self._build_music_time()

    # ---- helpers ----

    def local_beat_period(self, t: float) -> float:
        return self._beat_grid.period_at(t)

    def _beat_phase_at(self, t: float) -> float:
        times = self._beat_times
        if len(times) < 2:
            return 0.0
        idx = bisect.bisect_right(times, t) - 1
        if idx < 0 or idx >= len(times) - 1:
            return 0.0
        span = times[idx + 1] - times[idx]
        return max(0.0, min(1.0, (t - times[idx]) / span))

    def _bar_at(self, t: float) -> int:
        if self._downbeat_times:
            idx = bisect.bisect_right(self._downbeat_times, t) - 1
            return self._downbeat_bars[idx] if idx >= 0 else 0
        bps = self._bpm_global / 60.0
        return int(t * bps / max(1, self._beats_per_bar))

    def _bar_clock(self, t: float) -> float:
        """Continuous bar count (0 at first downbeat)."""
        if self._downbeat_times:
            return self._bar_grid.count(t)
        # No downbeats: derive bars from the beat grid.
        return self._beat_grid.count(t) / self._beats_per_bar

    def _phrase_phase_at(self, t: float, bar_clock: float) -> float:
        downs = self._downbeat_events
        if downs:
            idx = bisect.bisect_right(self._downbeat_times, t) - 1
            ref = max(0, min(idx, len(downs) - 1))
            ev = downs[ref]
            if (ev.phrase_position is not None and ev.phrase_length
                    and ev.phrase_length > 0):
                rel = bar_clock - ref           # bars since the ref downbeat
                return _fract((ev.phrase_position + rel) / ev.phrase_length)
        return _fract(bar_clock / 4.0)

    def _section_index(self, t: float) -> int:
        idx = bisect.bisect_right(self._section_starts, t) - 1
        if idx >= 0 and t < self._sections[idx].end:
            return idx
        return -1

    def _section_energy_at(self, t: float) -> float:
        idx = self._section_index(t)
        return self._sections[idx].energy_rank if idx >= 0 else 0.0

    def _section_id_at(self, t: float) -> int:
        idx = self._section_index(t)
        if idx < 0:
            return 0
        return self._section_label_ids.get(self._sections[idx].label or "", 0)

    def _section_progress_at(self, t: float) -> float:
        idx = self._section_index(t)
        if idx < 0:
            return 0.0
        sec = self._sections[idx]
        span = sec.end - sec.start
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (t - sec.start) / span))

    def _time_to_next_section_at(self, t: float) -> float:
        j = bisect.bisect_right(self._section_starts, t)
        if j < len(self._section_starts):
            return self._section_starts[j] - t
        return NO_NEXT_SECTION

    def _drum_pulses_at(self, t: float) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for cls, (times, strengths, taus) in self._drums.items():
            hi = bisect.bisect_right(times, t)
            lo = bisect.bisect_left(times, t - _ENV_MAX_TAIL, 0, hi)
            value = 0.0
            for i in range(lo, hi):
                value += envelope_value(t - times[i], taus[i], strengths[i])
            out[cls] = min(1.0, max(0.0, value))
        return out

    def _curve_dict_at(self, curves: Dict[str, "StemEnergyCurve"], t: float) -> Dict[str, float]:
        return {k: _sample_curve(v, t) for k, v in curves.items()}

    def _energy_fast_at(self, t: float) -> float:
        c = self._controls.get("energy_fast")
        return _sample_curve(c, t) if c is not None else _sample_curve(
            self.bundle.global_energy, t)

    def _build_music_time(self) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Cumulative table for iMusicTime over [0, duration].

        speed(t) = 0.5 + energy_smoothed(t), energy smoothed with a centered
        ~1-bar window (offline, so non-causal), normalised so that
        music_time(duration) == duration (mean rate 1).
        """
        dur = float(self.bundle.duration_sec)
        if not (dur > 0):
            return None
        n = int(math.ceil(dur / _MUSIC_TIME_DT)) + 1
        grid = np.linspace(0.0, dur, n)
        curve = self._controls.get("energy_fast") or self.bundle.global_energy
        if _curve_ok(curve):
            vals = np.asarray(curve.values, dtype=np.float64)
            src_t = np.arange(len(vals), dtype=np.float64) * curve.hop_sec
            energy = np.interp(grid, src_t, vals)
        else:
            energy = np.zeros(n)
        energy = np.clip(np.nan_to_num(energy), 0.0, 1.0)
        # ~1 bar centered moving average (edge-normalised).
        step = grid[1] - grid[0] if n > 1 else _MUSIC_TIME_DT
        bar_sec = self._beats_per_bar * self._beat_grid.fallback
        half = max(1, int(round(0.5 * bar_sec / step)))
        kernel = np.ones(2 * half + 1)
        num = np.convolve(energy, kernel, mode="same")
        den = np.convolve(np.ones(n), kernel, mode="same")
        smoothed = num / den
        speed = 0.5 + smoothed
        if n < 2:
            return None
        cum = np.concatenate([[0.0], np.cumsum(0.5 * (speed[1:] + speed[:-1]) * np.diff(grid))])
        total = cum[-1]
        if not (total > 0):
            return None
        cum *= dur / total
        return grid, cum

    def music_time_at(self, t: float) -> float:
        table = self._music_time_table
        if table is None:
            return t
        grid, cum = table
        if t <= 0.0:
            return t                       # rate 1 before the song
        if t >= grid[-1]:
            return float(cum[-1]) + (t - float(grid[-1]))
        return float(np.interp(t, grid, cum))

    # ---- public ----

    def evaluate(self, frame_index: int) -> EvalFrame:
        return self.evaluate_at(frame_index / self.fps)

    def evaluate_at(self, t_video: float) -> EvalFrame:
        """Evaluate at video time ``t_video`` seconds (av offset applied)."""
        t = float(t_video) - self.av_offset_sec
        bar_clock = self._bar_clock(t)
        midi = self._curve_dict_at(self.bundle.midi_energy, t)
        stems = self._curve_dict_at(self._stems, t)
        stem_levels = {k: stems[k] if k in stems else midi.get(k, 0.0)
                       for k in ("vocals", "other", "bass")}
        return EvalFrame(
            bpm=self._bpm_global,
            beat_phase=self._beat_phase_at(t),
            bar=self._bar_at(t),
            section_energy=self._section_energy_at(t),
            section_id=self._section_id_at(t),
            global_energy=_sample_curve(self.bundle.global_energy, t),
            drum_pulses=self._drum_pulses_at(t),
            midi_energy=midi,
            stems_energy=stems,
            time=float(t_video),
            beat_clock=self._beat_grid.count(t),
            bar_phase=_fract(bar_clock),
            phrase_phase=self._phrase_phase_at(t, bar_clock),
            section_progress=self._section_progress_at(t),
            time_to_next_section=self._time_to_next_section_at(t),
            build=_sample_curve(self._controls.get("build"), t),
            brightness=_sample_curve(self._controls.get("brightness"), t),
            energy_fast=self._energy_fast_at(t),
            music_time=self.music_time_at(t),
            stem_levels=stem_levels,
        )


_BIN_RANGES = {
    "low":     (0, 32),
    "low_mid": (32, 96),
    "mid_hi":  (96, 256),
    "high":    (256, 512),
}

# Canonical track inventory. Band tracks contribute to an iChannel0 band;
# uniform tracks drive scalar uniforms (handled in masked_builtin_uniforms).
# stem.bass sits in the "low" band with the kick (bass belongs in the lows).
BAND_TRACKS: Dict[str, str] = {
    "drums.kick":   "low",
    "drums.snare":  "low_mid",
    "drums.tom":    "low_mid",
    "drums.hat":    "mid_hi",
    "drums.cymbal": "mid_hi",
    "drums.other":  "mid_hi",
    "stem.vocals":  "high",
    "stem.other":   "high",
    "stem.bass":    "low",
}
UNIFORM_TRACKS = {"tempo", "sections", "energy"}
ALL_TRACK_IDS = list(BAND_TRACKS.keys()) + sorted(UNIFORM_TRACKS)

# Map a band track id to the EvalFrame field + key holding its raw value.
# stem.* read EvalFrame.stem_levels (stems_energy when the bundle has it,
# else midi_energy); see band_raw_value for the fallback on bare frames.
_BAND_TRACK_SOURCE = {
    "drums.kick":   ("drum_pulses", "kick"),
    "drums.snare":  ("drum_pulses", "snare"),
    "drums.tom":    ("drum_pulses", "tom"),
    "drums.hat":    ("drum_pulses", "hat"),
    "drums.cymbal": ("drum_pulses", "cymbal"),
    "drums.other":  ("drum_pulses", "other"),
    "stem.vocals":  ("stem_levels", "vocals"),
    "stem.other":   ("stem_levels", "other"),
    "stem.bass":    ("stem_levels", "bass"),
}


def band_raw_value(frame: "EvalFrame", track_id: str) -> float:
    """Raw (pre-settings) scalar a band track contributes for this frame."""
    src_field, key = _BAND_TRACK_SOURCE[track_id]
    values = getattr(frame, src_field)
    if key in values:
        return float(values[key])
    if src_field == "stem_levels":
        return float(frame.midi_energy.get(key, 0.0))
    return 0.0


def apply_setting(value: float, setting: Optional[dict]) -> float:
    """Stateless threshold->gain->mute. Smoothing is applied in Phase 4."""
    if not setting:
        return value
    if setting.get("mute", False):
        return 0.0
    threshold = float(setting.get("threshold", 0.0))
    gain = float(setting.get("gain", 1.0))
    v = max(0.0, value - threshold)
    return v * gain


def apply_settings_series(raw: "List[float]", setting: Optional[dict]) -> "List[float]":
    """Effective per-frame series for one track: threshold -> one-pole smooth
    -> gain -> mute. Pure function of (raw, setting) so render and preview
    match. smoothing == 0 reduces exactly to per-element apply_setting."""
    n = len(raw)
    if not setting:
        return [float(v) for v in raw]
    if setting.get("mute", False):
        return [0.0] * n
    threshold = float(setting.get("threshold", 0.0))
    gain = float(setting.get("gain", 1.0))
    a = float(setting.get("smoothing", 0.0))
    out = [0.0] * n
    prev = 0.0
    for i in range(n):
        x = max(0.0, float(raw[i]) - threshold)
        sm = x if i == 0 else (1.0 - a) * x + a * prev
        prev = sm
        out[i] = sm * gain
    return out


def masked_builtin_uniforms(
    frame: Optional["EvalFrame"], settings: Optional[Dict[str, dict]] = None
) -> Dict[str, Any]:
    """The six Phase-1 scalar uniforms with per-track mute applied.

    Uniform tracks: 'tempo' -> iBpm/iBeat/iBar, 'sections' -> iSectionEnergy/
    iSectionId, 'energy' -> iEnergy. Mute zeroes a track's uniforms; gain/
    threshold scale the energy-like uniforms (iSectionEnergy, iEnergy).
    Structural ints (iBpm/iBeat/iBar/iSectionId) honor mute only.
    """
    if frame is None:
        return {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0,
                "iSectionEnergy": 0.0, "iSectionId": 0, "iEnergy": 0.0}
    settings = settings or {}

    def muted(track_id: str) -> bool:
        s = settings.get(track_id)
        return bool(s and s.get("mute", False))

    tempo_off = muted("tempo")
    sections_off = muted("sections")

    return {
        "iBpm": 0.0 if tempo_off else float(frame.bpm),
        "iBeat": 0.0 if tempo_off else float(frame.beat_phase),
        "iBar": 0 if tempo_off else int(frame.bar),
        "iSectionEnergy": 0.0 if sections_off
            else apply_setting(float(frame.section_energy), settings.get("sections")),
        "iSectionId": 0 if sections_off else int(frame.section_id),
        "iEnergy": apply_setting(float(frame.global_energy), settings.get("energy")),
    }


# Scalar musical uniforms added alongside the Phase-1 six. Order is the
# canonical order shipped to the preview (frame_data.uniforms keys in
# MUSICAL_UNIFORM_SERIES).
MUSICAL_UNIFORMS = (
    "iBeatClock", "iBarPhase", "iPhrasePhase",
    "iSectionProgress", "iTimeToNextSection",
    "iBuild", "iKick", "iSnare", "iHat",
    "iBass", "iVocals", "iDrums", "iOther",
    "iBrightness", "iEnergyFast", "iMusicTime",
)
# uniform name -> frame_data.uniforms series key
MUSICAL_UNIFORM_SERIES = {
    "iBeatClock": "beatClock", "iBarPhase": "barPhase",
    "iPhrasePhase": "phrasePhase", "iSectionProgress": "sectionProgress",
    "iTimeToNextSection": "timeToNextSection", "iBuild": "build",
    "iKick": "kick", "iSnare": "snare", "iHat": "hat",
    "iBass": "bass", "iVocals": "vocals", "iDrums": "drums", "iOther": "other",
    "iBrightness": "brightness", "iEnergyFast": "energyFast",
    "iMusicTime": "musicTime",
}
# Masking rule per musical uniform: (track_id, how). how = "mute" zeroes on
# mute only (structural/clock values); "setting" applies threshold/gain/mute
# (apply_setting) like iEnergy. None = no track maps cleanly (unmasked).
_MUSICAL_MASK = {
    "iBeatClock": ("tempo", "mute"), "iBarPhase": ("tempo", "mute"),
    "iPhrasePhase": ("tempo", "mute"),
    "iSectionProgress": ("sections", "mute"),
    "iTimeToNextSection": ("sections", "mute"),
    "iBuild": None,
    "iKick": ("drums.kick", "setting"), "iSnare": ("drums.snare", "setting"),
    "iHat": ("drums.hat", "setting"),
    "iBass": ("stem.bass", "setting"), "iVocals": ("stem.vocals", "setting"),
    "iDrums": None, "iOther": ("stem.other", "setting"),
    "iBrightness": None, "iEnergyFast": ("energy", "setting"),
    "iMusicTime": None,
}


def raw_musical_values(frame: "EvalFrame") -> Dict[str, float]:
    """Unmasked musical uniform values for one EvalFrame."""
    return {
        "iBeatClock": float(frame.beat_clock),
        "iBarPhase": float(frame.bar_phase),
        "iPhrasePhase": float(frame.phrase_phase),
        "iSectionProgress": float(frame.section_progress),
        "iTimeToNextSection": float(frame.time_to_next_section),
        "iBuild": float(frame.build),
        "iKick": float(frame.drum_pulses.get("kick", 0.0)),
        "iSnare": float(frame.drum_pulses.get("snare", 0.0)),
        "iHat": float(frame.drum_pulses.get("hat", 0.0)),
        "iBass": float(frame.stems_energy.get("bass", 0.0)),
        "iVocals": float(frame.stems_energy.get("vocals", 0.0)),
        "iDrums": float(frame.stems_energy.get("drums", 0.0)),
        "iOther": float(frame.stems_energy.get("other", 0.0)),
        "iBrightness": float(frame.brightness),
        "iEnergyFast": float(frame.energy_fast),
        "iMusicTime": float(frame.music_time),
    }


def masked_musical_uniforms(
    frame: Optional["EvalFrame"],
    settings: Optional[Dict[str, dict]] = None,
    time_sec: float = 0.0,
) -> Dict[str, float]:
    """The musical-structure uniforms with per-track settings applied.

    Mapping to tracks (see _MUSICAL_MASK): tempo mute zeroes the clocks;
    sections mute zeroes iSectionProgress and parks iTimeToNextSection at
    NO_NEXT_SECTION; drum/stem uniforms follow their band track's
    threshold/gain/mute (not its smoothing, which is per-frame state);
    iEnergyFast follows 'energy'. iBuild/iDrums/iBrightness/iMusicTime have
    no clean track and are unmasked.

    Without a bundle (frame None) everything is 0 except iTimeToNextSection
    (NO_NEXT_SECTION: there is no upcoming section) and iMusicTime, which
    falls back to ``time_sec`` so shaders using it as an iTime replacement
    keep moving.
    """
    if frame is None:
        out = {name: 0.0 for name in MUSICAL_UNIFORMS}
        out["iTimeToNextSection"] = NO_NEXT_SECTION
        out["iMusicTime"] = float(time_sec)
        return out
    settings = settings or {}
    raw = raw_musical_values(frame)
    out: Dict[str, float] = {}
    for name in MUSICAL_UNIFORMS:
        v = raw[name]
        rule = _MUSICAL_MASK[name]
        if rule is not None:
            track_id, how = rule
            s = settings.get(track_id)
            if s and s.get("mute", False):
                v = NO_NEXT_SECTION if name == "iTimeToNextSection" else 0.0
            elif how == "setting":
                v = apply_setting(v, s)
        out[name] = float(v)
    return out


def bundle_uniforms(
    frame: Optional["EvalFrame"],
    settings: Optional[Dict[str, dict]] = None,
    time_sec: float = 0.0,
) -> Dict[str, Any]:
    """All scalar bundle uniforms (Phase-1 six + musical), masked."""
    out = masked_builtin_uniforms(frame, settings)
    out.update(masked_musical_uniforms(frame, settings, time_sec))
    return out


def _hann_envelope(width: int) -> np.ndarray:
    if width <= 0:
        return np.zeros(0, dtype=np.float32)
    if width == 1:
        return np.array([1.0], dtype=np.float32)
    return np.hanning(width).astype(np.float32)


class MusicalSpectrumSynth:
    """Synthesize a 2x512 iChannel0 texture from an EvalFrame.

    Composes row 0 from per-track band contributions so the same select-and-sum
    model can run client-side (Phase 2) and match this output exactly.
    """

    def __init__(self) -> None:
        self._envelopes = {
            name: _hann_envelope(end - start)
            for name, (start, end) in _BIN_RANGES.items()
        }

    def _raw_value(self, frame: "EvalFrame", track_id: str) -> float:
        return band_raw_value(frame, track_id)

    def track_band_contributions(
        self, frame: "EvalFrame", settings: Optional[Dict[str, dict]] = None
    ) -> Dict[str, np.ndarray]:
        """Each band track's isolated 512-bin row (settings applied)."""
        settings = settings or {}
        out: Dict[str, np.ndarray] = {}
        for track_id, band in BAND_TRACKS.items():
            value = apply_setting(self._raw_value(frame, track_id),
                                  settings.get(track_id))
            s, e = _BIN_RANGES[band]
            row = np.zeros(512, dtype=np.float32)
            if value > 0:
                row[s:e] = self._envelopes[band] * value
            out[track_id] = row
        return out

    def synthesize_effective(
        self, band_values: Dict[str, float], section_energy: float,
        beat_phase: float, global_energy: float,
    ) -> np.ndarray:
        """Compose the 2x512 texture from already-effective per-track band
        scalars (settings/smoothing already applied)."""
        tex = np.zeros((2, 512), dtype=np.float32)
        for tid, band in BAND_TRACKS.items():
            v = band_values.get(tid, 0.0)
            if v > 0:
                s, e = _BIN_RANGES[band]
                tex[0][s:e] += self._envelopes[band] * v
        tex[0] += 0.1 * float(section_energy)
        np.clip(tex[0], 0.0, 1.0, out=tex[0])
        wave = 0.5 + 0.5 * float(global_energy) * math.sin(
            2.0 * math.pi * float(beat_phase)
        )
        tex[1, :] = max(0.0, min(1.0, wave))
        return tex

    def synthesize(
        self, frame: "EvalFrame", settings: Optional[Dict[str, dict]] = None
    ) -> np.ndarray:
        settings = settings or {}
        band_values = {
            tid: apply_setting(self._raw_value(frame, tid), settings.get(tid))
            for tid in BAND_TRACKS
        }
        return self.synthesize_effective(
            band_values, frame.section_energy, frame.beat_phase, frame.global_energy)


def bundle_health(bundle: "MusiCueBundle") -> Dict[str, Any]:
    """Report which bundle fields are populated (UI data-quality surface)."""
    stems = {stem: _curve_ok(curve) for stem, curve in bundle.stems_energy.items()}
    return {
        "schema_version": bundle.schema_version,
        "beats": {"present": bool(bundle.beats), "count": len(bundle.beats)},
        "phrases": {"present": any(b.phrase_length for b in bundle.beats)},
        "sections": {"present": bool(bundle.sections),
                     "count": len(bundle.sections)},
        "drums": {cls: len(events) for cls, events in bundle.drums.items()},
        "midi_energy": {stem: bool(curve.values)
                        for stem, curve in bundle.midi_energy.items()},
        "stems_energy": {"present": any(stems.values()), "stems": stems},
        "controls": {name: _curve_ok(curve)
                     for name, curve in bundle.controls.items()},
    }


def format_bundle_health(health: Dict[str, Any]) -> str:
    """Human/Claude-readable summary of which bundle data exists.

    Names empty/absent tracks explicitly so reactivity prompts avoid mapping
    visuals to data that isn't there.
    """
    beats = health.get("beats", {})
    sections = health.get("sections", {})
    drums = health.get("drums", {})
    midi = health.get("midi_energy", {})
    stems = health.get("stems_energy", {})
    controls = health.get("controls", {}) or {}

    present_drums = [f"{k}({v})" for k, v in drums.items() if v]
    empty_drums = [k for k, v in drums.items() if not v]
    present_stems = [k for k, v in midi.items() if v]
    empty_stems = [k for k, v in midi.items() if not v]
    stem_map = stems.get("stems", {}) or {}
    present_audio_stems = [k for k, v in stem_map.items() if v]
    present_controls = [k for k, v in controls.items() if v]
    absent_controls = [k for k in ("energy_fast", "brightness", "build",
                                   "onset_density") if k not in present_controls]

    if stems.get("present"):
        stems_line = ("- stems_energy: present"
                      + (f" ({', '.join(present_audio_stems)})"
                         if present_audio_stems else "")
                      + " -> iBass/iVocals/iDrums/iOther are live")
    else:
        stems_line = "- stems_energy: absent (iBass/iVocals/iDrums/iOther stay 0)"
    lines = [
        f"- beats: {beats.get('count', 0)} ({'present' if beats.get('present') else 'absent'})"
        + ("; phrase data present" if health.get("phrases", {}).get("present")
           else "; no phrase data (iPhrasePhase uses 4-bar groups)"),
        f"- sections: {sections.get('count', 0)} ({'present' if sections.get('present') else 'absent'})",
        f"- drums present: {', '.join(present_drums) if present_drums else 'none'}",
        f"- drums empty: {', '.join(empty_drums) if empty_drums else 'none'}",
        f"- melodic stems present: {', '.join(present_stems) if present_stems else 'none'}",
        f"- melodic stems empty: {', '.join(empty_stems) if empty_stems else 'none'}",
        stems_line,
        f"- controls present: {', '.join(present_controls) if present_controls else 'none'}",
        f"- controls absent: {', '.join(absent_controls) if absent_controls else 'none'}"
        + (" (iBuild/iBrightness stay 0; iEnergyFast falls back to iEnergy)"
           if absent_controls else ""),
    ]
    return "\n".join(lines)


# frame_data.uniforms keys for the Phase-1 six.
_BUILTIN_SERIES = ("bpm", "beat", "bar", "sectionEnergy", "sectionId", "energy")


def build_track_timeline(bundle: "MusiCueBundle", fps: float,
                         av_offset_ms: float = 0.0) -> Dict[str, Any]:
    """Whole-song per-track data for the UI: lane-draw shapes + health.

    Ships RAW per-track data; consumers (preview/render) apply track_settings.
    """
    duration = float(bundle.duration_sec)
    tracks: Dict[str, Any] = {}

    for track_id, band in BAND_TRACKS.items():
        src_field, key = _BAND_TRACK_SOURCE[track_id]
        if src_field == "drum_pulses":
            events = bundle.drums.get(key, [])
            tracks[track_id] = {
                "band": band,
                "onsets": [{"t": o.t, "strength": o.strength} for o in events],
            }
        else:  # stem level curve: stems_energy when present, else midi_energy
            curve = bundle.stems_energy.get(key)
            if not _curve_ok(curve):
                curve = bundle.midi_energy.get(key)
            tracks[track_id] = {
                "band": band,
                "curve": {"hop_sec": curve.hop_sec, "values": list(curve.values)}
                if curve else {"hop_sec": 0.0, "values": []},
            }

    tracks["tempo"] = {
        "bpm": bundle.tempo.bpm_global,
        "beats": [{"t": b.t, "isDownbeat": b.is_downbeat, "bar": b.bar,
                   "beatInBar": b.beat_in_bar} for b in bundle.beats],
    }
    tracks["sections"] = {
        "blocks": [{"start": s.start, "end": s.end, "label": s.label,
                    "energyRank": s.energy_rank} for s in bundle.sections],
    }
    tracks["energy"] = {
        "curve": {"hop_sec": bundle.global_energy.hop_sec,
                  "values": list(bundle.global_energy.values)},
    }

    # Per-frame data the browser sums to compose iChannel0 + uniforms. Python
    # (BundleEvaluator) stays the canonical evaluator; the client only sums
    # and applies the same masks (web/js/webgl/cue-compose.js).
    n_frames = int(round(duration * fps))
    evaluator = BundleEvaluator(bundle, fps=fps, av_offset_ms=av_offset_ms)
    frame_tracks: Dict[str, List[float]] = {tid: [] for tid in BAND_TRACKS}
    uni_series: Dict[str, List[float]] = {k: [] for k in _BUILTIN_SERIES}
    for key in MUSICAL_UNIFORM_SERIES.values():
        uni_series[key] = []
    for f in range(n_frames):
        ef = evaluator.evaluate(f)
        for tid in BAND_TRACKS:
            frame_tracks[tid].append(band_raw_value(ef, tid))
        uni_series["bpm"].append(float(ef.bpm))
        uni_series["beat"].append(float(ef.beat_phase))
        uni_series["bar"].append(int(ef.bar))
        uni_series["sectionEnergy"].append(float(ef.section_energy))
        uni_series["sectionId"].append(int(ef.section_id))
        uni_series["energy"].append(float(ef.global_energy))
        for name, v in raw_musical_values(ef).items():
            uni_series[MUSICAL_UNIFORM_SERIES[name]].append(v)

    return {
        "fps": float(fps),
        "duration_sec": duration,
        "frames": n_frames,
        "av_offset_ms": float(av_offset_ms or 0.0),
        "bands": ["low", "low_mid", "mid_hi", "high"],
        "tracks": tracks,
        "frame_data": {"tracks": frame_tracks, "uniforms": uni_series},
        "health": bundle_health(bundle),
    }


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
