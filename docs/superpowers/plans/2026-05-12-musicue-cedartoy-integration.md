# MusiCue → CedarToy Integration (Phase 1 Retrofit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive CedarToy shaders from MusiCue's `CueSheet` JSON sidecar by synthesizing a musical `iChannel0` texture (replacing raw FFT) and exposing five new built-in uniforms — all without requiring shader code changes.

**Architecture:** A new `cedartoy/cuesheet.py` module mirrors MusiCue's pydantic schemas locally, evaluates events into per-frame floats (`CueSheetEvaluator`), and synthesizes the 2×512 `iChannel0` texture (`MusicalSpectrumSynth`). `render.py` hooks into the existing audio texture pipeline — replacing the data written to `self.audio_tex_512` when a cuesheet is loaded — and binds five new uniforms. MusiCue is untouched.

**Tech Stack:** Python 3.11, pydantic v2, numpy, moderngl, pytest.

**Deviation from spec:** The spec used `audio_mode: raw|cued|blend`, but CedarToy already has `audio_mode: shadertoy|history|both` (texture-output selection). This plan introduces a new orthogonal field **`cuesheet_mode`** with values `auto|raw|cued|blend` (default `auto` — uses `cued` when a cuesheet is loaded, otherwise `raw`). Same semantics, no collision.

**File structure:**

| Path | Role |
|---|---|
| `cedartoy/cuesheet.py` | NEW — pydantic mirrors, `CueSheetEvaluator`, `MusicalSpectrumSynth`, sibling discovery + sha helpers |
| `cedartoy/types.py` | MODIFY — add `cuesheet_path`, `cuesheet_mode`, `cuesheet_blend` to `RenderJob` |
| `cedartoy/config_model.py` | MODIFY — add three fields with validation |
| `cedartoy/options_schema.py` | MODIFY — add three `Option` entries under `# --- Audio ---` |
| `cedartoy/render.py` | MODIFY — load cuesheet at init, synthesize texture per frame, bind built-in uniforms |
| `cedartoy/cli.py` | MODIFY — add `--cuesheet`, `--cuesheet-mode`, `--cuesheet-blend` flags |
| `web/js/components/config-editor.js` | MODIFY — surface new options in the audio section |
| `tests/test_cuesheet_schema.py` | NEW — schema mirror + version gate tests |
| `tests/test_cuesheet_evaluator.py` | NEW — per-frame evaluation tests |
| `tests/test_spectrum_synth.py` | NEW — texture synthesis tests |
| `tests/test_cuesheet_loader.py` | NEW — sibling discovery + sha mismatch tests |
| `tests/test_cuesheet_integration.py` | NEW — end-to-end render-job-level test with mock cuesheet |

---

## Task 1: Pydantic schema mirrors and version gate

**Files:**
- Create: `cedartoy/cuesheet.py`
- Test: `tests/test_cuesheet_schema.py`

CedarToy mirrors only the subset of MusiCue's CueSheet it actually consumes: `CueSheet`, `CueTrack`, `BeatEvent`, `SectionEvent`, `OnsetEvent`, `TempoInfo`. Events on `CueTrack` stay as `list[dict[str, Any]]` (MusiCue's own type) — they're heterogeneous bags of fields and the evaluator reads them as dicts. A `load_cuesheet(path)` helper hard-fails on unsupported major schema versions.

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_cuesheet_schema.py`:

```python
import json
from pathlib import Path

import pytest

from cedartoy.cuesheet import (
    CueSheet,
    SUPPORTED_SCHEMA_MAJOR,
    UnsupportedSchemaError,
    load_cuesheet,
)


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


def _minimal_payload(schema_version: str = "1.2") -> dict:
    return {
        "schema_version": schema_version,
        "source_sha256": "deadbeef",
        "grammar": "concert_visuals",
        "duration_sec": 10.0,
        "fps": 24.0,
        "drop_frame": False,
        "tempo_map": [],
        "tracks": [],
    }


def test_loads_minimal_cuesheet(tmp_path):
    path = _write(tmp_path, "song.cuesheet.json", _minimal_payload())

    cuesheet = load_cuesheet(path)

    assert isinstance(cuesheet, CueSheet)
    assert cuesheet.schema_version == "1.2"
    assert cuesheet.source_sha256 == "deadbeef"
    assert cuesheet.grammar == "concert_visuals"
    assert cuesheet.duration_sec == 10.0
    assert cuesheet.tracks == []


def test_rejects_unsupported_major_schema(tmp_path):
    path = _write(tmp_path, "future.cuesheet.json", _minimal_payload("2.0"))

    with pytest.raises(UnsupportedSchemaError) as exc_info:
        load_cuesheet(path)

    assert "2.0" in str(exc_info.value)
    assert str(SUPPORTED_SCHEMA_MAJOR) in str(exc_info.value)


def test_accepts_same_major_higher_minor(tmp_path):
    path = _write(tmp_path, "newer.cuesheet.json", _minimal_payload("1.9"))

    cuesheet = load_cuesheet(path)

    assert cuesheet.schema_version == "1.9"


def test_rejects_malformed_json(tmp_path):
    path = tmp_path / "bad.cuesheet.json"
    path.write_text("not json at all")

    with pytest.raises(ValueError):
        load_cuesheet(path)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_cuesheet_schema.py -v`
Expected: ImportError — `cedartoy.cuesheet` does not exist.

- [ ] **Step 3: Implement `cedartoy/cuesheet.py` with schema mirrors**

Create `cedartoy/cuesheet.py`:

```python
"""MusiCue CueSheet ingestion for CedarToy.

Mirrors the subset of MusiCue's pydantic schema CedarToy consumes, plus a
loader with major-version gating. The schema mirror is intentionally
minimal — event payloads stay as ``dict[str, Any]`` since MusiCue treats
them heterogeneously per track type.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

SUPPORTED_SCHEMA_MAJOR = 1


class UnsupportedSchemaError(ValueError):
    """Raised when a cuesheet's schema major version isn't supported."""


class TempoInfo(BaseModel):
    bpm_global: float
    bpm_curve: List[Dict[str, float]] = Field(default_factory=list)
    time_signature: List[int] = Field(default=[4, 4])


class BeatEvent(BaseModel):
    t: float
    beat_in_bar: int
    bar: int
    is_downbeat: bool
    confidence: float = 1.0


class SectionEvent(BaseModel):
    start: float
    end: float
    label: str
    confidence: float = 1.0


class OnsetEvent(BaseModel):
    t: float
    strength: float
    drum_class: Optional[str] = None
    drum_class_conf: Optional[float] = None


class CueTrack(BaseModel):
    name: str
    type: Literal["impulse", "envelope", "step", "ramp", "continuous"]
    timescale: Literal["micro", "meso", "macro"]
    events: List[Dict[str, Any]] = Field(default_factory=list)
    hop_sec: Optional[float] = None
    values: Optional[List[float]] = None


class CueSheet(BaseModel):
    schema_version: str
    source_sha256: str
    grammar: str
    duration_sec: float
    fps: float = 24.0
    drop_frame: bool = False
    tempo_map: List[Dict[str, float]] = Field(default_factory=list)
    tracks: List[CueTrack] = Field(default_factory=list)

    # Optional analysis-derived data MusiCue may include alongside tracks.
    # Kept loose because Phase 1 doesn't need to validate this deeply.
    tempo: Optional[TempoInfo] = None
    beats: List[BeatEvent] = Field(default_factory=list)
    sections: List[SectionEvent] = Field(default_factory=list)
    onsets: Dict[str, List[OnsetEvent]] = Field(default_factory=dict)
    curves: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def load_cuesheet(path: Path) -> CueSheet:
    """Load and validate a CueSheet JSON file.

    Raises ``UnsupportedSchemaError`` if the major version doesn't match
    ``SUPPORTED_SCHEMA_MAJOR``. Raises ``ValueError`` on malformed JSON or
    pydantic validation failure.
    """
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cuesheet {path} is not valid JSON: {exc}") from exc

    version = str(data.get("schema_version", "0.0"))
    if _major(version) != SUPPORTED_SCHEMA_MAJOR:
        raise UnsupportedSchemaError(
            f"Cuesheet schema {version} is not supported "
            f"(CedarToy expects major {SUPPORTED_SCHEMA_MAJOR}). "
            "Re-export with the current MusiCue."
        )

    try:
        return CueSheet.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Cuesheet {path} failed validation: {exc}") from exc
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_cuesheet_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/cuesheet.py tests/test_cuesheet_schema.py
git commit -m "feat(cuesheet): add CueSheet schema mirrors and version-gated loader"
```

---

## Task 2: `CueSheetEvaluator` — per-frame evaluation

**Files:**
- Modify: `cedartoy/cuesheet.py` (append `EvalFrame` + `CueSheetEvaluator`)
- Test: `tests/test_cuesheet_evaluator.py`

The evaluator precomputes lookup tables at construction time, then exposes `evaluate(frame_index: int) -> EvalFrame`. Impulse onsets decay with ADSR pulled from each event's `envelope` dict if present, else defaults of `A=0.005, D=0.08, S=0, R=0`. Continuous tracks are linearly interpolated from their `hop_sec` grid. Section/beat lookups are binary search. `section_energy` is precomputed once: rank sections by `lufs_integrated + 0.5 × spectral_flux_rise` and normalize to `[0, 1]`; when those fields aren't available, every section gets `0.5`. `iBar` falls back to `floor(t × bpm / 60 / time_signature[0])` when no `is_downbeat` flags exist.

- [ ] **Step 1: Write failing evaluator tests**

Create `tests/test_cuesheet_evaluator.py`:

```python
import math
from typing import Any, Dict, List

import pytest

from cedartoy.cuesheet import (
    BeatEvent,
    CueSheet,
    CueSheetEvaluator,
    CueTrack,
    EvalFrame,
    SectionEvent,
    TempoInfo,
)


def _cuesheet(
    *,
    duration: float = 4.0,
    tempo_bpm: float = 120.0,
    beats: List[BeatEvent] = None,
    sections: List[SectionEvent] = None,
    tracks: List[CueTrack] = None,
) -> CueSheet:
    return CueSheet(
        schema_version="1.2",
        source_sha256="x",
        grammar="concert_visuals",
        duration_sec=duration,
        fps=24.0,
        tempo=TempoInfo(bpm_global=tempo_bpm),
        beats=beats or [],
        sections=sections or [],
        tracks=tracks or [],
    )


def _impulse_track(name: str, events: List[Dict[str, Any]]) -> CueTrack:
    return CueTrack(name=name, type="impulse", timescale="micro", events=events)


def _continuous_track(name: str, hop_sec: float, values: List[float]) -> CueTrack:
    return CueTrack(
        name=name, type="continuous", timescale="meso",
        hop_sec=hop_sec, values=values,
    )


def test_kick_impulse_peaks_at_event_time():
    track = _impulse_track("kick", [{"t": 1.0, "strength": 1.0, "drum_class": "kick"}])
    ev = CueSheetEvaluator(_cuesheet(tracks=[track]), fps=24.0)

    frame_at_event = int(round(1.0 * 24.0))
    eval_at_event = ev.evaluate(frame_at_event)

    assert eval_at_event.drum_pulses["kick"] == pytest.approx(1.0, abs=0.05)


def test_kick_impulse_decays_after_eighth_note():
    track = _impulse_track("kick", [{"t": 1.0, "strength": 1.0, "drum_class": "kick"}])
    ev = CueSheetEvaluator(_cuesheet(tracks=[track]), fps=24.0)

    # 0.5s after the hit, well past the default 0.08s decay
    decayed = ev.evaluate(int(round(1.5 * 24.0))).drum_pulses["kick"]

    assert decayed < 0.05


def test_drum_class_pulled_from_event_dict():
    track = _impulse_track("drums", [
        {"t": 0.0, "strength": 1.0, "drum_class": "snare"},
    ])
    ev = CueSheetEvaluator(_cuesheet(tracks=[track]), fps=24.0)

    frame_zero = ev.evaluate(0)

    assert frame_zero.drum_pulses.get("snare", 0.0) == pytest.approx(1.0, abs=0.05)
    assert frame_zero.drum_pulses.get("kick", 0.0) == 0.0


def test_continuous_track_linear_interpolation():
    track = _continuous_track("global_energy", hop_sec=1.0, values=[0.0, 1.0, 0.0])
    ev = CueSheetEvaluator(_cuesheet(tracks=[track]), fps=24.0)

    # t=0.5s should sit halfway between values[0]=0 and values[1]=1
    midpoint = ev.evaluate(int(round(0.5 * 24.0))).global_energy

    assert midpoint == pytest.approx(0.5, abs=0.02)


def test_beat_phase_advances_linearly_between_beats():
    beats = [
        BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
        BeatEvent(t=0.5, beat_in_bar=1, bar=0, is_downbeat=False),
        BeatEvent(t=1.0, beat_in_bar=2, bar=0, is_downbeat=False),
    ]
    ev = CueSheetEvaluator(_cuesheet(beats=beats), fps=24.0)

    frame = ev.evaluate(int(round(0.25 * 24.0)))

    assert frame.beat_phase == pytest.approx(0.5, abs=0.05)
    assert frame.bar == 0


def test_bar_increments_at_next_downbeat():
    beats = [
        BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
        BeatEvent(t=2.0, beat_in_bar=0, bar=1, is_downbeat=True),
    ]
    ev = CueSheetEvaluator(_cuesheet(beats=beats), fps=24.0)

    assert ev.evaluate(int(round(0.5 * 24.0))).bar == 0
    assert ev.evaluate(int(round(2.5 * 24.0))).bar == 1


def test_section_energy_lookup_at_boundary():
    sections = [
        SectionEvent(start=0.0, end=1.0, label="intro"),
        SectionEvent(start=1.0, end=2.0, label="chorus"),
    ]
    ev = CueSheetEvaluator(_cuesheet(sections=sections), fps=24.0)

    # No LUFS data → uniform 0.5 baseline for every section
    in_intro = ev.evaluate(int(round(0.5 * 24.0))).section_energy
    in_chorus = ev.evaluate(int(round(1.5 * 24.0))).section_energy

    assert in_intro == pytest.approx(0.5, abs=0.01)
    assert in_chorus == pytest.approx(0.5, abs=0.01)


def test_bpm_from_tempo_global():
    ev = CueSheetEvaluator(_cuesheet(tempo_bpm=128.0), fps=24.0)

    assert ev.evaluate(0).bpm == pytest.approx(128.0)


def test_evaluate_empty_cuesheet_returns_zeros():
    ev = CueSheetEvaluator(_cuesheet(), fps=24.0)

    frame = ev.evaluate(0)

    assert frame.bpm == pytest.approx(120.0)  # global from default
    assert frame.beat_phase == 0.0
    assert frame.bar == 0
    assert frame.section_energy == 0.0
    assert frame.global_energy == 0.0
    assert frame.drum_pulses == {}
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_cuesheet_evaluator.py -v`
Expected: ImportError — `EvalFrame` and `CueSheetEvaluator` not defined yet.

- [ ] **Step 3: Append `EvalFrame` and `CueSheetEvaluator` to `cedartoy/cuesheet.py`**

Add the following at the bottom of `cedartoy/cuesheet.py`:

```python
import bisect
from dataclasses import dataclass, field
from typing import Tuple


_DEFAULT_ADSR = (0.005, 0.08, 0.0, 0.0)  # A, D, S, R


@dataclass
class EvalFrame:
    bpm: float = 0.0
    beat_phase: float = 0.0
    bar: int = 0
    section_energy: float = 0.0
    global_energy: float = 0.0
    drum_pulses: Dict[str, float] = field(default_factory=dict)
    midi_energy: Dict[str, float] = field(default_factory=dict)


def _adsr_value(t_since: float, adsr: Tuple[float, float, float, float], strength: float) -> float:
    """Evaluate an ADSR envelope at ``t_since`` seconds after the event."""
    if t_since < 0:
        return 0.0
    a, d, s, _r = adsr
    if t_since < a:
        return strength * (t_since / a) if a > 0 else strength
    if t_since < a + d:
        # Decay from peak (strength) to sustain (strength * s)
        progress = (t_since - a) / d if d > 0 else 1.0
        return strength * (1.0 - progress * (1.0 - s))
    return strength * s  # Sustain; no release modeling in Phase 1


def _event_adsr(event: Dict[str, Any]) -> Tuple[float, float, float, float]:
    env = event.get("envelope")
    if isinstance(env, dict):
        return (
            float(env.get("a", _DEFAULT_ADSR[0])),
            float(env.get("d", _DEFAULT_ADSR[1])),
            float(env.get("s", _DEFAULT_ADSR[2])),
            float(env.get("r", _DEFAULT_ADSR[3])),
        )
    return _DEFAULT_ADSR


class CueSheetEvaluator:
    """Evaluate a CueSheet at a given render frame index."""

    def __init__(self, cuesheet: CueSheet, fps: float):
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.cuesheet = cuesheet
        self.fps = fps

        # Pre-index impulse events by drum class for fast per-frame lookup.
        self._impulses_by_class: Dict[str, List[Tuple[float, float, Tuple[float, float, float, float]]]] = {}
        for track in cuesheet.tracks:
            if track.type != "impulse":
                continue
            for event in track.events:
                drum_class = event.get("drum_class") or track.name
                t = float(event.get("t", 0.0))
                strength = float(event.get("strength", 1.0))
                adsr = _event_adsr(event)
                self._impulses_by_class.setdefault(drum_class, []).append((t, strength, adsr))
        for events in self._impulses_by_class.values():
            events.sort(key=lambda e: e[0])

        # Pre-extract continuous tracks by name for interpolation.
        self._continuous: Dict[str, CueTrack] = {
            t.name: t for t in cuesheet.tracks if t.type == "continuous"
        }

        # Beat times in a flat sorted list for bisect.
        self._beat_times = [b.t for b in cuesheet.beats]
        self._downbeat_bars = [(b.t, b.bar) for b in cuesheet.beats if b.is_downbeat]

        # Section index for lookup; section_energy precomputed once.
        self._sections = sorted(cuesheet.sections, key=lambda s: s.start)
        self._section_energies = self._precompute_section_energies()

        # BPM curve helper.
        self._bpm_global = cuesheet.tempo.bpm_global if cuesheet.tempo else 120.0

    def _precompute_section_energies(self) -> List[float]:
        """Compute a normalized [0,1] energy weight per section.

        Phase 1 has no LUFS/spectral data available on the bare ``SectionEvent``
        mirror, so every section gets 0.5 as a placeholder. When MusiCue extends
        the schema with per-section LUFS, replace this with a real ranking.
        """
        return [0.5] * len(self._sections) if self._sections else []

    def _section_index_at(self, t: float) -> int:
        for i, sec in enumerate(self._sections):
            if sec.start <= t < sec.end:
                return i
        return -1

    def _bar_at(self, t: float) -> int:
        if not self._downbeat_bars:
            # Fallback: derive bars from global BPM assuming 4/4
            beats_per_bar = 4
            if self.cuesheet.tempo and self.cuesheet.tempo.time_signature:
                beats_per_bar = self.cuesheet.tempo.time_signature[0]
            bps = self._bpm_global / 60.0
            return int(t * bps / beats_per_bar)
        # Find last downbeat at or before t
        for time_t, bar in reversed(self._downbeat_bars):
            if time_t <= t:
                return bar
        return 0

    def _beat_phase_at(self, t: float) -> float:
        times = self._beat_times
        if not times or len(times) < 2:
            return 0.0
        idx = bisect.bisect_right(times, t) - 1
        if idx < 0:
            return 0.0
        if idx >= len(times) - 1:
            return 0.0
        span = times[idx + 1] - times[idx]
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (t - times[idx]) / span))

    def _continuous_value_at(self, name: str, t: float) -> float:
        track = self._continuous.get(name)
        if not track or not track.values or not track.hop_sec:
            return 0.0
        if track.hop_sec <= 0:
            return 0.0
        idx_f = t / track.hop_sec
        i0 = int(idx_f)
        if i0 < 0:
            return float(track.values[0])
        if i0 >= len(track.values) - 1:
            return float(track.values[-1])
        frac = idx_f - i0
        return float(track.values[i0]) * (1.0 - frac) + float(track.values[i0 + 1]) * frac

    def _drum_pulses_at(self, t: float) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for drum_class, events in self._impulses_by_class.items():
            value = 0.0
            for event_t, strength, adsr in events:
                if event_t > t:
                    break
                value += _adsr_value(t - event_t, adsr, strength)
            result[drum_class] = min(1.0, max(0.0, value))
        return result

    def evaluate(self, frame_index: int) -> EvalFrame:
        t = frame_index / self.fps

        section_idx = self._section_index_at(t)
        section_energy = self._section_energies[section_idx] if section_idx >= 0 else 0.0

        return EvalFrame(
            bpm=self._bpm_global,
            beat_phase=self._beat_phase_at(t),
            bar=self._bar_at(t),
            section_energy=section_energy,
            global_energy=self._continuous_value_at("global_energy", t),
            drum_pulses=self._drum_pulses_at(t),
            midi_energy={},  # Phase 1 leaves this empty unless a continuous "midi_*" track exists
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_cuesheet_evaluator.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/cuesheet.py tests/test_cuesheet_evaluator.py
git commit -m "feat(cuesheet): add CueSheetEvaluator with ADSR decay and beat phase"
```

---

## Task 3: `MusicalSpectrumSynth` — synthesize the 2×512 `iChannel0` texture

**Files:**
- Modify: `cedartoy/cuesheet.py` (append `MusicalSpectrumSynth`)
- Test: `tests/test_spectrum_synth.py`

Produces a `(2, 512)` float32 numpy array matching the shape and value range of `AudioProcessor._compute_shadertoy_texture` output. Row 0 distributes `EvalFrame.drum_pulses` and `midi_energy` across four bin ranges using Hann-shaped envelopes. Row 1 is `0.5 + 0.5 × global_energy × sin(2π × beat_phase)`, clamped to `[0, 1]`.

- [ ] **Step 1: Write failing synth tests**

Create `tests/test_spectrum_synth.py`:

```python
import numpy as np
import pytest

from cedartoy.cuesheet import EvalFrame, MusicalSpectrumSynth


def test_output_shape_and_dtype():
    synth = MusicalSpectrumSynth()
    texture = synth.synthesize(EvalFrame())

    assert texture.shape == (2, 512)
    assert texture.dtype == np.float32


def test_kick_drives_low_bins():
    synth = MusicalSpectrumSynth()
    frame = EvalFrame(drum_pulses={"kick": 1.0})

    texture = synth.synthesize(frame)

    # Low bins (0-32) should have substantial energy
    assert texture[0, 0:32].max() > 0.5
    # Mid-high bins (96-256) should be near zero
    assert texture[0, 96:256].max() < 0.1


def test_hat_drives_mid_high_bins():
    synth = MusicalSpectrumSynth()
    frame = EvalFrame(drum_pulses={"hat": 1.0})

    texture = synth.synthesize(frame)

    assert texture[0, 96:256].max() > 0.5
    assert texture[0, 0:32].max() < 0.1


def test_section_energy_adds_baseline_tilt():
    synth = MusicalSpectrumSynth()
    quiet = synth.synthesize(EvalFrame())
    loud = synth.synthesize(EvalFrame(section_energy=0.8))

    # Baseline tilt is +0.1 * section_energy = +0.08 in loud
    assert loud[0].mean() > quiet[0].mean()
    assert loud[0].mean() == pytest.approx(0.08, abs=0.02)


def test_waveform_row_zero_crossings_on_beats():
    synth = MusicalSpectrumSynth()

    # At beat_phase = 0, sin(0) = 0 → waveform = 0.5
    at_beat = synth.synthesize(EvalFrame(beat_phase=0.0, global_energy=1.0))
    # At beat_phase = 0.25, sin(pi/2) = 1 → waveform = 1.0
    quarter = synth.synthesize(EvalFrame(beat_phase=0.25, global_energy=1.0))

    assert at_beat[1].mean() == pytest.approx(0.5, abs=0.01)
    assert quarter[1].mean() == pytest.approx(1.0, abs=0.01)


def test_values_clamped_to_zero_one():
    synth = MusicalSpectrumSynth()
    # Saturate every drum class to overflow into clamping
    frame = EvalFrame(
        drum_pulses={"kick": 1.0, "snare": 1.0, "clap": 1.0, "hat": 1.0, "cymbal": 1.0},
        section_energy=1.0,
        global_energy=1.0,
    )

    texture = synth.synthesize(frame)

    assert texture.min() >= 0.0
    assert texture.max() <= 1.0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_spectrum_synth.py -v`
Expected: ImportError — `MusicalSpectrumSynth` not defined.

- [ ] **Step 3: Append `MusicalSpectrumSynth` to `cedartoy/cuesheet.py`**

```python
import math

import numpy as np


# Bin range assignments. Hann-shaped envelopes filled into these ranges.
_BIN_RANGES = {
    "low": (0, 32),
    "low_mid": (32, 96),
    "mid_high": (96, 256),
    "high": (256, 512),
}


# Which drum classes / midi energies contribute to each bin range.
_LOW_CLASSES = ("kick",)
_LOW_MID_CLASSES = ("snare", "clap")
_MID_HIGH_CLASSES = ("hat", "cymbal")
_HIGH_MIDI_KEYS = ("vocals", "other")


def _hann_envelope(width: int) -> np.ndarray:
    if width <= 0:
        return np.zeros(0, dtype=np.float32)
    if width == 1:
        return np.array([1.0], dtype=np.float32)
    # numpy hanning has zeros at endpoints; ensure peak = 1
    return np.hanning(width).astype(np.float32)


class MusicalSpectrumSynth:
    """Synthesize a 2×512 iChannel0 texture from an EvalFrame."""

    def __init__(self) -> None:
        self._envelopes = {
            name: _hann_envelope(end - start)
            for name, (start, end) in _BIN_RANGES.items()
        }

    def _add_range(self, row: np.ndarray, range_name: str, weight: float) -> None:
        if weight <= 0:
            return
        start, end = _BIN_RANGES[range_name]
        row[start:end] += self._envelopes[range_name] * weight

    def synthesize(self, frame: EvalFrame) -> np.ndarray:
        texture = np.zeros((2, 512), dtype=np.float32)
        row0 = texture[0]

        # Distribute drum pulses across bin ranges
        low = sum(frame.drum_pulses.get(c, 0.0) for c in _LOW_CLASSES)
        low_mid = sum(frame.drum_pulses.get(c, 0.0) for c in _LOW_MID_CLASSES)
        mid_high = sum(frame.drum_pulses.get(c, 0.0) for c in _MID_HIGH_CLASSES)
        high = sum(frame.midi_energy.get(k, 0.0) for k in _HIGH_MIDI_KEYS)

        self._add_range(row0, "low", low)
        self._add_range(row0, "low_mid", low_mid)
        self._add_range(row0, "mid_high", mid_high)
        self._add_range(row0, "high", high)

        # Section energy baseline tilt
        row0 += 0.1 * float(frame.section_energy)

        np.clip(row0, 0.0, 1.0, out=row0)

        # Row 1: tempo-locked heartbeat ribbon
        wave_value = 0.5 + 0.5 * float(frame.global_energy) * math.sin(
            2.0 * math.pi * float(frame.beat_phase)
        )
        wave_value = max(0.0, min(1.0, wave_value))
        texture[1, :] = wave_value

        return texture
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_spectrum_synth.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/cuesheet.py tests/test_spectrum_synth.py
git commit -m "feat(cuesheet): synthesize musical iChannel0 texture from EvalFrame"
```

---

## Task 4: Config and `RenderJob` field additions

**Files:**
- Modify: `cedartoy/config_model.py`
- Modify: `cedartoy/types.py`
- Modify: `cedartoy/options_schema.py`
- Test: `tests/test_config_model.py` (extend)

Add three fields end-to-end: `cuesheet_path: Optional[Path]`, `cuesheet_mode: Literal["auto", "raw", "cued", "blend"]` (default `"auto"`), and `cuesheet_blend: float` (default `0.5`). Validate that `cuesheet_blend` is in `[0, 1]`.

- [ ] **Step 1: Write failing config tests**

Append to `tests/test_config_model.py`:

```python
def test_cuesheet_fields_have_safe_defaults():
    cfg = CedarToyConfig(shader=Path("shaders/test.glsl"))

    assert cfg.cuesheet_path is None
    assert cfg.cuesheet_mode == "auto"
    assert cfg.cuesheet_blend == 0.5


def test_cuesheet_path_accepts_explicit_path():
    cfg = CedarToyConfig(
        shader=Path("shaders/test.glsl"),
        cuesheet_path=Path("song.cuesheet.json"),
    )

    assert cfg.cuesheet_path == Path("song.cuesheet.json")


def test_cuesheet_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        CedarToyConfig(shader=Path("shaders/test.glsl"), cuesheet_mode="bogus")


def test_cuesheet_blend_must_be_in_unit_range():
    with pytest.raises(ValueError, match="cuesheet_blend"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), cuesheet_blend=1.5)

    with pytest.raises(ValueError, match="cuesheet_blend"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), cuesheet_blend=-0.1)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_config_model.py -v`
Expected: 4 failures on the new tests; existing tests still pass.

- [ ] **Step 3: Add fields to `cedartoy/config_model.py`**

Add to `cedartoy/config_model.py`:

1. After the existing type aliases at the top:

```python
CuesheetMode = Literal["auto", "raw", "cued", "blend"]
```

2. Inside `CedarToyConfig`, after the `audio_mode: AudioMode = "both"` line:

```python
    cuesheet_path: Optional[Path] = None
    cuesheet_mode: CuesheetMode = "auto"
    cuesheet_blend: float = 0.5
```

3. Add a validator before the `to_runtime_dict` method:

```python
    @field_validator("cuesheet_blend")
    @classmethod
    def cuesheet_blend_in_unit_range(cls, value: float):
        if value < 0 or value > 1:
            raise ValueError("cuesheet_blend must be between 0 and 1")
        return value
```

- [ ] **Step 4: Add `RenderJob` fields in `cedartoy/types.py`**

Inside the `RenderJob` dataclass, in the `# audio` section after `audio_meta: Optional[AudioMeta]`:

```python
    # cuesheet (MusiCue integration)
    cuesheet_path: Optional[Path] = None
    cuesheet_mode: str = "auto"
    cuesheet_blend: float = 0.5
```

(Defaults are required because earlier fields without defaults exist; Python dataclasses allow defaulting trailing fields. If a positional construction breaks because of ordering, move these to the end of `RenderJob`.)

- [ ] **Step 5: Add option entries in `cedartoy/options_schema.py`**

After the existing `audio_mode` option (around line 80), insert:

```python
OPTIONS.append(Option("cuesheet_path", "Cuesheet Path", "path", None,
    help_text="Path to a MusiCue cuesheet.json. Defaults to sibling of audio_path."))
OPTIONS.append(Option("cuesheet_mode", "Cuesheet Mode", "choice", "auto",
    choices=["auto", "raw", "cued", "blend"],
    help_text="auto=cued when cuesheet loaded; raw=ignore cuesheet; cued=synthesized texture; blend=mix raw and cued"))
OPTIONS.append(Option("cuesheet_blend", "Cuesheet Blend (0-1)", "float", 0.5,
    help_text="Mix weight for cued texture when cuesheet_mode='blend'"))
```

- [ ] **Step 6: Run all config tests — expect pass**

Run: `python -m pytest tests/test_config_model.py -v`
Expected: All passing (new + existing).

- [ ] **Step 7: Commit**

```bash
git add cedartoy/config_model.py cedartoy/types.py cedartoy/options_schema.py tests/test_config_model.py
git commit -m "feat(config): add cuesheet_path/mode/blend fields"
```

---

## Task 5: Cuesheet loader with sibling discovery and sha validation

**Files:**
- Modify: `cedartoy/cuesheet.py` (append `discover_cuesheet_path`, `compute_audio_sha256`, `CuesheetLoadResult`, `load_for_audio`)
- Test: `tests/test_cuesheet_loader.py`

Adds the glue that decides which cuesheet (if any) to use for a given audio path and what to log. `load_for_audio(audio_path, override_path)` returns a small dataclass with the loaded cuesheet, the source path, and a `sha_match` flag. The render integration in Task 6 consumes this; this task keeps the loader testable in isolation.

- [ ] **Step 1: Write failing loader tests**

Create `tests/test_cuesheet_loader.py`:

```python
import hashlib
import json
import logging
from pathlib import Path

import pytest

from cedartoy.cuesheet import (
    CuesheetLoadResult,
    compute_audio_sha256,
    discover_cuesheet_path,
    load_for_audio,
)


def _write_audio(tmp_path: Path, name: str = "song.wav") -> Path:
    audio = tmp_path / name
    audio.write_bytes(b"fake-audio-bytes")
    return audio


def _write_cuesheet(path: Path, source_sha256: str = "x" * 64) -> Path:
    path.write_text(json.dumps({
        "schema_version": "1.2",
        "source_sha256": source_sha256,
        "grammar": "concert_visuals",
        "duration_sec": 1.0,
        "fps": 24.0,
        "drop_frame": False,
        "tempo_map": [],
        "tracks": [],
    }))
    return path


def test_discover_sibling_cuesheet(tmp_path):
    audio = _write_audio(tmp_path)
    cuesheet = _write_cuesheet(tmp_path / "song.cuesheet.json")

    found = discover_cuesheet_path(audio)

    assert found == cuesheet


def test_discover_returns_none_when_missing(tmp_path):
    audio = _write_audio(tmp_path)

    assert discover_cuesheet_path(audio) is None


def test_compute_audio_sha256_matches_hashlib(tmp_path):
    audio = _write_audio(tmp_path)
    expected = hashlib.sha256(audio.read_bytes()).hexdigest()

    assert compute_audio_sha256(audio) == expected


def test_load_for_audio_returns_match_when_sha_aligns(tmp_path):
    audio = _write_audio(tmp_path)
    audio_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    _write_cuesheet(tmp_path / "song.cuesheet.json", source_sha256=audio_sha)

    result = load_for_audio(audio)

    assert isinstance(result, CuesheetLoadResult)
    assert result.cuesheet is not None
    assert result.sha_match is True
    assert result.path == tmp_path / "song.cuesheet.json"


def test_load_for_audio_warns_on_sha_mismatch(tmp_path, caplog):
    audio = _write_audio(tmp_path)
    _write_cuesheet(tmp_path / "song.cuesheet.json", source_sha256="mismatched")

    with caplog.at_level(logging.WARNING):
        result = load_for_audio(audio)

    assert result.cuesheet is not None
    assert result.sha_match is False
    assert any("sha" in msg.lower() for msg in caplog.messages)


def test_load_for_audio_returns_none_when_no_cuesheet(tmp_path):
    audio = _write_audio(tmp_path)

    result = load_for_audio(audio)

    assert result.cuesheet is None
    assert result.path is None
    assert result.sha_match is False


def test_load_for_audio_honors_explicit_override(tmp_path):
    audio = _write_audio(tmp_path)
    # Sibling exists but we should ignore it in favor of override
    _write_cuesheet(tmp_path / "song.cuesheet.json", source_sha256="sibling")
    override = _write_cuesheet(tmp_path / "override.cuesheet.json", source_sha256="override")

    result = load_for_audio(audio, override_path=override)

    assert result.path == override
    assert result.cuesheet.source_sha256 == "override"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_cuesheet_loader.py -v`
Expected: ImportError — loader functions not defined.

- [ ] **Step 3: Append loader functions to `cedartoy/cuesheet.py`**

```python
import hashlib
import logging

_logger = logging.getLogger(__name__)


@dataclass
class CuesheetLoadResult:
    cuesheet: Optional[CueSheet] = None
    path: Optional[Path] = None
    sha_match: bool = False


def discover_cuesheet_path(audio_path: Path) -> Optional[Path]:
    """Return the sibling ``<audio_stem>.cuesheet.json`` if it exists."""
    candidate = audio_path.with_suffix("").with_suffix(".cuesheet.json")
    # ``with_suffix("").with_suffix(...)`` strips one suffix then adds one.
    # For ``song.wav`` -> ``song`` -> ``song.cuesheet.json``. For ``song.tar.gz``
    # we'd get ``song.tar.cuesheet.json``, which is fine.
    if candidate.exists():
        return candidate
    return None


def compute_audio_sha256(audio_path: Path) -> str:
    """SHA-256 of the audio file bytes."""
    h = hashlib.sha256()
    with open(audio_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_for_audio(
    audio_path: Path,
    override_path: Optional[Path] = None,
) -> CuesheetLoadResult:
    """Load the cuesheet for ``audio_path`` (override > sibling > none).

    Logs an INFO when no cuesheet is found, a WARNING when sha mismatches.
    """
    target = override_path if override_path is not None else discover_cuesheet_path(audio_path)
    if target is None:
        _logger.info("No cuesheet found for %s; rendering with raw FFT.", audio_path)
        return CuesheetLoadResult()

    cuesheet = load_cuesheet(target)
    audio_sha = compute_audio_sha256(audio_path)
    sha_match = cuesheet.source_sha256 == audio_sha
    if not sha_match:
        _logger.warning(
            "Cuesheet %s source_sha256=%s does not match audio %s sha=%s; using anyway.",
            target, cuesheet.source_sha256, audio_path, audio_sha,
        )

    return CuesheetLoadResult(cuesheet=cuesheet, path=target, sha_match=sha_match)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_cuesheet_loader.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/cuesheet.py tests/test_cuesheet_loader.py
git commit -m "feat(cuesheet): sibling discovery and sha-validating loader"
```

---

## Task 6: Wire cuesheet into `render.py` (init + per-frame texture)

**Files:**
- Modify: `cedartoy/render.py`
- Modify: `cedartoy/cli.py` (build RenderJob with the new fields — only if there's a job-construction site here; otherwise the orchestrator does it)
- Test: `tests/test_cuesheet_integration.py`

Two hook points in the renderer:

1. **Init** (`Renderer.__init__`, around line 167 where `AudioProcessor` is constructed): after audio loads, call `load_for_audio` and stash `self.cuesheet_eval` and `self.spectrum_synth` if a cuesheet came back. Honor `cuesheet_mode = "raw"` by clearing them.

2. **Per-frame texture write** (around line 967–971 where `self.audio_tex_512.write(...)` is called): if `self.cuesheet_eval` exists, build the synth texture; combine with raw per `cuesheet_mode` (`cued` = synth only, `blend` = `raw × (1-b) + cued × b`); write that.

- [ ] **Step 1: Write failing integration test**

Create `tests/test_cuesheet_integration.py`:

```python
"""End-to-end test: cuesheet loading + texture choice without OpenGL.

We instantiate the cuesheet machinery directly and verify Renderer's
texture-mix helper produces the expected blend. Full OpenGL render is
covered by manual visual smoke (documented in docs/AUDIO_SYSTEM.md).
"""
import numpy as np
import pytest

from cedartoy.cuesheet import (
    CueSheet,
    CueSheetEvaluator,
    CueTrack,
    MusicalSpectrumSynth,
    TempoInfo,
)
from cedartoy.render import _mix_audio_textures


def _make_cuesheet_with_kick() -> CueSheet:
    return CueSheet(
        schema_version="1.2",
        source_sha256="x",
        grammar="concert_visuals",
        duration_sec=2.0,
        fps=24.0,
        tempo=TempoInfo(bpm_global=120.0),
        tracks=[CueTrack(
            name="kick",
            type="impulse",
            timescale="micro",
            events=[{"t": 0.5, "strength": 1.0, "drum_class": "kick"}],
        )],
    )


def test_evaluator_drives_synth_to_low_bins_at_event_time():
    cuesheet = _make_cuesheet_with_kick()
    ev = CueSheetEvaluator(cuesheet, fps=24.0)
    synth = MusicalSpectrumSynth()

    frame = ev.evaluate(int(round(0.5 * 24.0)))
    texture = synth.synthesize(frame)

    assert texture[0, 0:32].max() > 0.5


def test_mix_cued_only():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)

    mixed = _mix_audio_textures(raw, cued, mode="cued", blend=0.5)

    assert mixed.shape == (2, 512)
    assert np.allclose(mixed, 0.8)


def test_mix_raw_only():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)

    mixed = _mix_audio_textures(raw, cued, mode="raw", blend=0.5)

    assert np.allclose(mixed, 0.2)


def test_mix_blend_50_50():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)

    mixed = _mix_audio_textures(raw, cued, mode="blend", blend=0.5)

    assert np.allclose(mixed, 0.5)


def test_mix_blend_weighted():
    raw = np.full((2, 512), 0.0, dtype=np.float32)
    cued = np.full((2, 512), 1.0, dtype=np.float32)

    mixed = _mix_audio_textures(raw, cued, mode="blend", blend=0.25)

    assert np.allclose(mixed, 0.25)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_cuesheet_integration.py -v`
Expected: ImportError on `_mix_audio_textures` — not defined yet.

- [ ] **Step 3: Add `_mix_audio_textures` helper to `cedartoy/render.py`**

Add near the top of `cedartoy/render.py` (after imports, before the `Renderer` class):

```python
import numpy as np


def _mix_audio_textures(
    raw: np.ndarray,
    cued: np.ndarray,
    mode: str,
    blend: float,
) -> np.ndarray:
    """Combine raw FFT and synthesized cued textures per cuesheet_mode."""
    if mode == "raw":
        return raw
    if mode == "cued":
        return cued
    if mode == "blend":
        b = max(0.0, min(1.0, float(blend)))
        return (raw * (1.0 - b) + cued * b).astype(np.float32)
    # auto is resolved upstream; if we get here treat it as "cued"
    return cued
```

- [ ] **Step 4: Wire cuesheet load into `Renderer.__init__`**

In `cedartoy/render.py`, after the existing `self.audio = AudioProcessor(...)` block (around line 167), add:

```python
        # MusiCue cuesheet integration
        self.cuesheet_eval = None
        self.spectrum_synth = None
        self.cuesheet_mode = getattr(job, "cuesheet_mode", "auto")
        self.cuesheet_blend = getattr(job, "cuesheet_blend", 0.5)

        if self.audio and self.cuesheet_mode != "raw":
            from .cuesheet import CueSheetEvaluator, MusicalSpectrumSynth, load_for_audio
            override = getattr(job, "cuesheet_path", None)
            result = load_for_audio(job.audio_path, override_path=override)
            if result.cuesheet is not None:
                self.cuesheet_eval = CueSheetEvaluator(result.cuesheet, fps=job.fps)
                self.spectrum_synth = MusicalSpectrumSynth()
                if self.cuesheet_mode == "auto":
                    self.cuesheet_mode = "cued"
            elif self.cuesheet_mode == "auto":
                self.cuesheet_mode = "raw"
```

- [ ] **Step 5: Replace the per-frame texture write**

In `cedartoy/render.py`, find the existing block (around line 967–971):

```python
            if self.job.audio_mode in ("shadertoy", "both"):
                aud_data = self.audio.get_shadertoy_texture(frame_idx)
                if not hasattr(self, 'audio_tex_512'):
                    self.audio_tex_512 = self.ctx.texture((512, 2), 1, dtype='f4')
                self.audio_tex_512.write(aud_data.astype('f4').tobytes())
```

Replace with:

```python
            if self.job.audio_mode in ("shadertoy", "both"):
                raw_aud = self.audio.get_shadertoy_texture(frame_idx)
                if self.cuesheet_eval is not None and self.spectrum_synth is not None:
                    eval_frame = self.cuesheet_eval.evaluate(frame_idx)
                    cued_aud = self.spectrum_synth.synthesize(eval_frame)
                    aud_data = _mix_audio_textures(
                        raw_aud, cued_aud, self.cuesheet_mode, self.cuesheet_blend
                    )
                else:
                    aud_data = raw_aud
                if not hasattr(self, 'audio_tex_512'):
                    self.audio_tex_512 = self.ctx.texture((512, 2), 1, dtype='f4')
                self.audio_tex_512.write(aud_data.astype('f4').tobytes())
```

- [ ] **Step 6: Run integration tests — expect pass**

Run: `python -m pytest tests/test_cuesheet_integration.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add cedartoy/render.py tests/test_cuesheet_integration.py
git commit -m "feat(render): synthesize cued iChannel0 texture when cuesheet present"
```

---

## Task 7: Bind built-in uniforms (`iBpm`, `iBeat`, `iBar`, `iSectionEnergy`, `iEnergy`)

**Files:**
- Modify: `cedartoy/render.py`
- Test: `tests/test_cuesheet_integration.py` (extend)

The render method already builds a `uni` dict per frame. Compute the `EvalFrame` once per frame (reusing the one from Task 6 if needed — for simplicity, evaluate again here; the cost is microscopic) and add the five entries. When `cuesheet_eval is None`, bind defaults (0.0 / 0).

- [ ] **Step 1: Write failing uniform-binding test**

Append to `tests/test_cuesheet_integration.py`:

```python
from cedartoy.render import _builtin_uniforms_from_eval


def test_builtin_uniforms_with_eval_frame():
    from cedartoy.cuesheet import EvalFrame

    frame = EvalFrame(
        bpm=128.0,
        beat_phase=0.25,
        bar=3,
        section_energy=0.7,
        global_energy=0.6,
    )

    uni = _builtin_uniforms_from_eval(frame)

    assert uni["iBpm"] == pytest.approx(128.0)
    assert uni["iBeat"] == pytest.approx(0.25)
    assert uni["iBar"] == 3
    assert uni["iSectionEnergy"] == pytest.approx(0.7)
    assert uni["iEnergy"] == pytest.approx(0.6)


def test_builtin_uniforms_with_none_returns_defaults():
    uni = _builtin_uniforms_from_eval(None)

    assert uni["iBpm"] == 0.0
    assert uni["iBeat"] == 0.0
    assert uni["iBar"] == 0
    assert uni["iSectionEnergy"] == 0.0
    assert uni["iEnergy"] == 0.0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_cuesheet_integration.py::test_builtin_uniforms_with_eval_frame -v`
Expected: ImportError — helper not defined.

- [ ] **Step 3: Add `_builtin_uniforms_from_eval` and call it in render**

Append to `cedartoy/render.py` (near `_mix_audio_textures`):

```python
from typing import Any, Dict, Optional


def _builtin_uniforms_from_eval(eval_frame) -> Dict[str, Any]:
    """Translate an EvalFrame into the five Phase 1 built-in uniforms.

    ``eval_frame`` may be None when no cuesheet is loaded; defaults are bound
    in that case so shaders declaring these uniforms still receive values.
    """
    if eval_frame is None:
        return {
            "iBpm": 0.0,
            "iBeat": 0.0,
            "iBar": 0,
            "iSectionEnergy": 0.0,
            "iEnergy": 0.0,
        }
    return {
        "iBpm": float(eval_frame.bpm),
        "iBeat": float(eval_frame.beat_phase),
        "iBar": int(eval_frame.bar),
        "iSectionEnergy": float(eval_frame.section_energy),
        "iEnergy": float(eval_frame.global_energy),
    }
```

In the per-frame render method, near where `uni` is populated (the same block touched in Task 6, after the audio texture is written), add:

```python
        # Built-in cuesheet uniforms (Phase 1)
        if self.cuesheet_eval is not None:
            ct_frame = self.cuesheet_eval.evaluate(frame_idx)
        else:
            ct_frame = None
        uni.update(_builtin_uniforms_from_eval(ct_frame))
```

Place this update *after* `uni` is initialized but *before* `self._bind_uniforms(prog, uni)`. The exact location: just before the line `for k, v in self.job.shader_parameters.items():` so user shader_parameters can still override if desired.

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_cuesheet_integration.py -v`
Expected: 7 passed (5 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/render.py tests/test_cuesheet_integration.py
git commit -m "feat(render): bind iBpm/iBeat/iBar/iSectionEnergy/iEnergy uniforms"
```

---

## Task 8: CLI flags

**Files:**
- Modify: `cedartoy/cli.py`
- Test: smoke run a help dump

Add `--cuesheet PATH`, `--cuesheet-mode {auto,raw,cued,blend}`, `--cuesheet-blend FLOAT` to the existing render subcommand. They populate the same `cli_args` dict that `build_config` already merges into the runtime config.

- [ ] **Step 1: Read existing CLI argument plumbing**

Run: `python -m pytest tests/test_render_jobs.py -v` first to ensure baseline passes. Open `cedartoy/cli.py` around the `render` subcommand definition and locate the argparse section that already adds `--audio-path` and `--audio-mode`.

- [ ] **Step 2: Add three argparse entries**

In `cedartoy/cli.py`, alongside the existing `--audio-path` / `--audio-mode` flags in the render subparser, add:

```python
    render_parser.add_argument(
        "--cuesheet", type=Path, default=None, dest="cuesheet_path",
        help="Path to MusiCue cuesheet.json (defaults to sibling of audio file)",
    )
    render_parser.add_argument(
        "--cuesheet-mode", choices=["auto", "raw", "cued", "blend"], default=None,
        dest="cuesheet_mode",
        help="auto=cued if cuesheet present; raw=ignore; cued=synthesized; blend=mix",
    )
    render_parser.add_argument(
        "--cuesheet-blend", type=float, default=None, dest="cuesheet_blend",
        help="Mix weight (0-1) for cued texture in blend mode",
    )
```

(If the exact parser variable name differs from `render_parser`, mirror what `--audio-path` and `--audio-mode` use in the same file.)

- [ ] **Step 3: Verify `--help` lists the new flags**

Run: `python -m cedartoy.cli render --help`
Expected output includes:

```
  --cuesheet CUESHEET_PATH
                        Path to MusiCue cuesheet.json (defaults to sibling of audio file)
  --cuesheet-mode {auto,raw,cued,blend}
                        ...
  --cuesheet-blend CUESHEET_BLEND
                        ...
```

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/cli.py
git commit -m "feat(cli): add --cuesheet/--cuesheet-mode/--cuesheet-blend flags"
```

---

## Task 9: Web UI status row and mode dropdown

**Files:**
- Modify: `web/js/components/config-editor.js`

The config editor already renders fields from the options schema. The three new options (`cuesheet_path`, `cuesheet_mode`, `cuesheet_blend`) added in Task 4 will appear automatically if the editor iterates over `OPTIONS`. This task is **only** to add a small status chip showing whether a cuesheet was detected for the current `audio_path`.

If `config-editor.js` already renders unknown options via a generic renderer, the only work here is to verify it picks them up. If it has a hand-built audio section, add the three fields explicitly.

- [ ] **Step 1: Inspect the existing audio section in `config-editor.js`**

Open `web/js/components/config-editor.js`. Search for `audio_path` and `audio_mode` — wherever they're rendered, add equivalent renders for `cuesheet_path` (file picker / text field), `cuesheet_mode` (select with the four choices), and `cuesheet_blend` (slider 0–1, conditionally visible when mode is `blend`).

- [ ] **Step 2: Add cuesheet status fetch endpoint stub (server-side, optional)**

If the existing backend has an `/api/audio/info` style endpoint, mirror it as `/api/cuesheet/check?audio_path=...` returning `{ "found": bool, "path": str | null, "sha_match": bool | null }`. This is optional polish — the renderer logs already cover detection. Skip if the existing UI doesn't have a similar pattern. Document the skip in the commit message.

- [ ] **Step 3: Manual UI smoke**

Start the UI: `python -m cedartoy.cli ui`. Open `http://localhost:8080`. Verify the new fields appear in the audio section and that setting `cuesheet_mode=raw` is accepted without errors.

- [ ] **Step 4: Commit**

```bash
git add web/js/components/config-editor.js
git commit -m "feat(ui): surface cuesheet path/mode/blend in config editor"
```

---

## Task 10: Manual visual smoke + docs

**Files:**
- Modify: `docs/AUDIO_SYSTEM.md` (or create if absent)
- Modify: `README.md` (one paragraph in the audio reactivity section)

Wraps the work with documentation and the documented manual A/B test.

- [ ] **Step 1: Document the cuesheet integration in `docs/AUDIO_SYSTEM.md`**

Append a new section:

```markdown
## MusiCue Cuesheet Integration

CedarToy can read MusiCue `cuesheet.json` files to drive shader animation
with structured musical cues instead of raw amplitude.

**Quick start:** Drop `song.cuesheet.json` next to `song.wav`, render as
normal. CedarToy auto-discovers the sibling cuesheet and switches
`iChannel0` to a synthesized "musical spectrum" texture:

- Bins 0–32:   kick onsets (ADSR-decayed)
- Bins 32–96:  snare + clap
- Bins 96–256: hat + cymbal
- Bins 256–512: vocal / melodic stems

The waveform row (row 1 of the 2×512 texture) becomes a tempo-locked
heartbeat: `0.5 + 0.5 × iEnergy × sin(2π × iBeat)`.

**Built-in uniforms** — declare any of these in your shader to opt in:

```glsl
uniform float iBpm;           // current BPM
uniform float iBeat;          // 0..1 phase within current beat
uniform int   iBar;           // 0-indexed bar number
uniform float iSectionEnergy; // 0..1 weight of current section
uniform float iEnergy;        // 0..1 short-window global energy
```

Shaders that don't declare them are unaffected.

**Modes** — set via `--cuesheet-mode` or the config:

- `auto` (default): use cued when a cuesheet is loaded, raw otherwise
- `raw`:   ignore cuesheet, use raw FFT
- `cued`:  use synthesized texture
- `blend`: mix raw and cued by `cuesheet_blend` (0..1)

**A/B comparison** — render the same shader against the same song twice:

```bash
python -m cedartoy.cli render shaders/luminescence.glsl \
  --audio-path song.wav --cuesheet-mode raw  --output-dir renders/raw

python -m cedartoy.cli render shaders/luminescence.glsl \
  --audio-path song.wav --cuesheet-mode cued --output-dir renders/cued
```

Beats should land cleaner in the `cued` output; high-energy sections
should sustain rather than going silent between hits.
```

- [ ] **Step 2: Add a paragraph in `README.md` under "Audio Reactivity"**

Append after the existing audio reactivity section:

```markdown
### MusiCue Cuesheets

If you have a MusiCue `cuesheet.json` next to your audio file, CedarToy
will use it automatically to synthesize a beat-locked `iChannel0`
texture and expose `iBpm`, `iBeat`, `iBar`, `iSectionEnergy`, and
`iEnergy` uniforms. See `docs/AUDIO_SYSTEM.md` for details.
```

- [ ] **Step 3: Manual A/B test**

Generate a cuesheet for any short audio file using MusiCue, drop it next to the audio, run the two commands from Step 1. Eyeball the difference. Note: this is the validation gate — if `cued` doesn't feel more musical than `raw`, surface that finding before declaring Phase 1 done.

- [ ] **Step 4: Commit**

```bash
git add docs/AUDIO_SYSTEM.md README.md
git commit -m "docs: cuesheet integration usage and A/B comparison"
```

---

## Self-review pass

**Spec coverage:**

| Spec section | Task |
|---|---|
| Architecture / module layout | Task 1 (file structure decided) |
| `cuesheet.py` schemas | Task 1 |
| `CueSheetEvaluator` | Task 2 |
| `MusicalSpectrumSynth` | Task 3 |
| `BuiltInsBinder` (folded into `_builtin_uniforms_from_eval`) | Task 7 |
| `render.py` patch points | Tasks 6 + 7 |
| Configuration surface | Task 4 |
| Web UI | Task 9 |
| CLI | Task 8 |
| Error handling — schema gate | Task 1 |
| Error handling — sha mismatch | Task 5 |
| Error handling — missing cuesheet fallback | Task 5 + Task 6 |
| Unit tests — evaluator | Task 2 |
| Unit tests — synth | Task 3 |
| Unit tests — render integration | Tasks 6 + 7 |
| Schema gate test | Task 1 |
| Sha-mismatch test | Task 5 |
| Visual smoke + docs | Task 10 |

**Spec deviations (intentional and justified inline):**

- `audio_mode` field name changed to `cuesheet_mode` to avoid colliding with CedarToy's existing `audio_mode` enum. Same semantics, plus an `auto` value that subsumes the spec's "default cued when cuesheet loaded" rule.
- `section_energy` placeholder returns 0.5 uniformly in Phase 1. The bare `SectionEvent` mirror doesn't carry LUFS or spectral-flux data; deferring real ranking is the spec's "open question for implementation planning."
- `iBar` falls back to `floor(t × bpm / 60 / beats_per_bar)` when no downbeats are present, matching the spec's suggested behavior for that open question.

**Type consistency:** `CueSheetEvaluator.evaluate` returns `EvalFrame`. `_builtin_uniforms_from_eval` accepts either an `EvalFrame` or `None`. `MusicalSpectrumSynth.synthesize` accepts an `EvalFrame`. `_mix_audio_textures` returns `np.ndarray`. All names and shapes are used consistently across Tasks 2, 3, 6, and 7.

**No placeholders:** Every step contains complete code or a complete command. Task 9 Step 2 explicitly marks an *optional* polish path with a clear "skip if" condition rather than leaving it open.

---

## Plan complete

Plan saved to `docs/superpowers/plans/2026-05-12-musicue-cedartoy-integration.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
