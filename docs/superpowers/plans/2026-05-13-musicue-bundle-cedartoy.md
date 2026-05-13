# MusiCue Bundle → CedarToy Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a MusiCue `export-bundle` command that emits an additive `song.musicue.json` containing AnalysisResult-derived musical data + the compiled CueSheet, then wire CedarToy to load that bundle and drive `iChannel0` + five new built-in uniforms from it.

**Architecture:** Two-phase, two-codebase. Phase 1 lives in `D:\MusiCue` — a new `MusiCueBundle` pydantic schema, a `build_bundle()` composer, and a `musicue export-bundle` Typer command. Phase 2 lives in `D:\cedartoy` — a lean bundle mirror in `cedartoy/musicue.py`, a `BundleEvaluator` + `MusicalSpectrumSynth`, and integration hooks in `render.py`. Phases share only the bundle JSON contract; CedarToy tests use synthetic JSON fixtures so the phases can be developed in parallel.

**Tech Stack:** Python 3.11, pydantic v2, numpy, moderngl, typer (MusiCue), argparse (CedarToy), pytest.

**Spec:** `docs/superpowers/specs/2026-05-13-musicue-bundle-cedartoy-design.md`

---

## Phase 1: MusiCue side (D:\MusiCue)

### File structure (Phase 1)

| Path | Role |
|---|---|
| `D:\MusiCue\musicue\schemas.py` | MODIFY — add `SectionBundleEntry`, `DrumOnset`, `MidiNoteBundle`, `StemEnergyCurve`, `MusiCueBundle` |
| `D:\MusiCue\musicue\compile\bundle.py` | NEW — `build_bundle(analysis, cuesheet) -> MusiCueBundle` |
| `D:\MusiCue\musicue\cli.py` | MODIFY — add `export_bundle` Typer command |
| `D:\MusiCue\tests\test_bundle_schema.py` | NEW |
| `D:\MusiCue\tests\test_bundle_builder.py` | NEW |
| `D:\MusiCue\tests\test_bundle_cli.py` | NEW |

All Phase 1 paths are relative to `D:\MusiCue\`.

---

### Task 1.1: Bundle schema additions

**Files:**
- Modify: `musicue/schemas.py`
- Test: `tests/test_bundle_schema.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_bundle_schema.py`:

```python
from musicue.schemas import (
    BeatEvent,
    DrumOnset,
    MidiNoteBundle,
    MusiCueBundle,
    SectionBundleEntry,
    StemEnergyCurve,
    TempoInfo,
)


def _minimal_bundle_kwargs():
    return dict(
        source_sha256="x" * 64,
        duration_sec=10.0,
        fps=24.0,
        tempo=TempoInfo(bpm_global=120.0),
        beats=[],
        sections=[],
        drums={},
        midi={},
        midi_energy={},
        global_energy=StemEnergyCurve(hop_sec=0.04, values=[0.0]),
    )


def test_minimal_bundle_roundtrip():
    from musicue.schemas import CueSheet

    cs = CueSheet(source_sha256="x" * 64, grammar="concert_visuals", duration_sec=10.0)
    b = MusiCueBundle(cuesheet=cs, **_minimal_bundle_kwargs())

    assert b.schema_version == "1.0"
    assert b.stems_energy == {}                  # default factory empty dict
    roundtrip = MusiCueBundle.model_validate_json(b.model_dump_json())
    assert roundtrip.duration_sec == 10.0


def test_section_bundle_entry_required_fields():
    s = SectionBundleEntry(start=0.0, end=4.0, label="intro", confidence=0.9, energy_rank=0.5)
    assert s.lufs is None
    assert s.spectral_flux_rise is None


def test_drum_onset_and_midi_note_shapes():
    d = DrumOnset(t=1.5, strength=0.8)
    assert d.confidence is None

    n = MidiNoteBundle(t=0.5, duration=0.25, pitch=60, velocity=100)
    assert n.pitch == 60


def test_stem_energy_curve_shape():
    c = StemEnergyCurve(hop_sec=0.04, values=[0.1, 0.5, 0.9])
    assert len(c.values) == 3
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_bundle_schema.py -v`
Expected: ImportError (new classes don't exist yet).

- [ ] **Step 3: Add the bundle types to `musicue/schemas.py`**

Append to `musicue/schemas.py` (after the existing `CueSheet` class around line 198):

```python
class SectionBundleEntry(BaseModel):
    start: float
    end: float
    label: str
    confidence: float
    lufs: float | None = None
    energy_rank: float
    spectral_flux_rise: float | None = None


class DrumOnset(BaseModel):
    t: float
    strength: float
    confidence: float | None = None


class MidiNoteBundle(BaseModel):
    t: float
    duration: float
    pitch: int
    velocity: int


class StemEnergyCurve(BaseModel):
    hop_sec: float
    values: list[float] = Field(default_factory=list)


class MusiCueBundle(BaseModel):
    schema_version: str = "1.0"
    source_sha256: str
    duration_sec: float
    fps: float = 24.0

    tempo: TempoInfo
    beats: list[BeatEvent] = Field(default_factory=list)

    sections: list[SectionBundleEntry] = Field(default_factory=list)

    drums: dict[str, list[DrumOnset]] = Field(default_factory=dict)
    midi: dict[str, list[MidiNoteBundle]] = Field(default_factory=dict)
    midi_energy: dict[str, StemEnergyCurve] = Field(default_factory=dict)

    stems_energy: dict[str, StemEnergyCurve] = Field(default_factory=dict)
    global_energy: StemEnergyCurve

    cuesheet: CueSheet
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_bundle_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add musicue/schemas.py tests/test_bundle_schema.py
git commit -m "feat(schemas): add MusiCueBundle and component types"
```

---

### Task 1.2: `build_bundle()` — sha cross-check + sections

**Files:**
- Create: `musicue/compile/bundle.py`
- Test: `tests/test_bundle_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bundle_builder.py`:

```python
import pytest

from musicue.compile.bundle import build_bundle
from musicue.schemas import (
    AnalysisConfig,
    AnalysisResult,
    CueSheet,
    SectionEvent,
    SourceInfo,
    TempoInfo,
)


def _analysis(sha: str = "a" * 64, sections=None) -> AnalysisResult:
    return AnalysisResult(
        source=SourceInfo(path="x.wav", sha256=sha, duration_sec=10.0, sample_rate=44100),
        analysis_config=AnalysisConfig(),
        stems={},
        tempo=TempoInfo(bpm_global=120.0),
        sections=sections or [],
    )


def _cuesheet(sha: str = "a" * 64) -> CueSheet:
    return CueSheet(source_sha256=sha, grammar="concert_visuals", duration_sec=10.0)


def test_sha_cross_check_raises_on_mismatch():
    with pytest.raises(ValueError, match="sha"):
        build_bundle(_analysis(sha="a" * 64), _cuesheet(sha="b" * 64))


def test_empty_analysis_yields_minimal_bundle():
    bundle = build_bundle(_analysis(), _cuesheet())
    assert bundle.schema_version == "1.0"
    assert bundle.duration_sec == 10.0
    assert bundle.sections == []
    assert bundle.drums == {}


def test_sections_get_normalized_energy_rank():
    sections = [
        SectionEvent(start=0.0, end=4.0, label="intro", confidence=0.9),
        SectionEvent(start=4.0, end=8.0, label="chorus", confidence=0.9),
        SectionEvent(start=8.0, end=10.0, label="outro", confidence=0.9),
    ]
    bundle = build_bundle(_analysis(sections=sections), _cuesheet())

    assert len(bundle.sections) == 3
    # No LUFS or spectral_flux data → all sections collapse to 0.5
    for s in bundle.sections:
        assert s.energy_rank == 0.5
        assert s.lufs is None
        assert s.spectral_flux_rise is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_bundle_builder.py -v`
Expected: ImportError — `musicue.compile.bundle` doesn't exist.

- [ ] **Step 3: Create `musicue/compile/bundle.py`**

```python
"""Build a MusiCueBundle from an AnalysisResult + its compiled CueSheet."""
from __future__ import annotations

from musicue.schemas import (
    AnalysisResult,
    CueSheet,
    DrumOnset,
    MidiNoteBundle,
    MusiCueBundle,
    SectionBundleEntry,
    StemEnergyCurve,
)


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _build_sections(analysis: AnalysisResult) -> list[SectionBundleEntry]:
    if not analysis.sections:
        return []

    # Rank candidate: LUFS (windowed from analysis.curves["lufs"] if available)
    # plus spectral_flux_rise from matching section_transitions.
    # Phase 1 implementation: both signals absent on the SectionEvent mirror,
    # so every section collapses to rank=0.5. We compute the slot anyway so
    # downstream consumers always see the field.
    raw_scores: list[float] = []
    transitions_by_t = {round(tr.t, 3): tr for tr in analysis.section_transitions}

    for sec in analysis.sections:
        spectral_rise = None
        # A transition leading INTO this section sits at sec.start
        tr = transitions_by_t.get(round(sec.start, 3))
        if tr is not None:
            spectral_rise = tr.ramp_evidence.spectral_flux_rise

        lufs = None
        if "lufs" in analysis.curves:
            curve = analysis.curves["lufs"]
            if curve.hop_sec > 0 and curve.values:
                i0 = max(0, int(sec.start / curve.hop_sec))
                i1 = min(len(curve.values), int(sec.end / curve.hop_sec))
                if i1 > i0:
                    window = curve.values[i0:i1]
                    lufs = sum(window) / len(window)

        score = 0.0
        components = 0
        if spectral_rise is not None:
            score += spectral_rise
            components += 1
        if lufs is not None:
            score += lufs
            components += 1
        raw_scores.append(score / components if components else 0.0)

    ranks = _normalize(raw_scores)
    out: list[SectionBundleEntry] = []
    for sec, rank in zip(analysis.sections, ranks):
        # Re-fetch the per-section signals to attach to the bundle entry
        tr = transitions_by_t.get(round(sec.start, 3))
        spectral_rise = tr.ramp_evidence.spectral_flux_rise if tr else None
        lufs = None
        if "lufs" in analysis.curves and analysis.curves["lufs"].hop_sec > 0:
            curve = analysis.curves["lufs"]
            i0 = max(0, int(sec.start / curve.hop_sec))
            i1 = min(len(curve.values), int(sec.end / curve.hop_sec))
            if i1 > i0:
                window = curve.values[i0:i1]
                lufs = sum(window) / len(window)

        out.append(SectionBundleEntry(
            start=sec.start, end=sec.end, label=sec.label, confidence=sec.confidence,
            lufs=lufs, energy_rank=rank if rank is not None else 0.5,
            spectral_flux_rise=spectral_rise,
        ))
    return out


def build_bundle(analysis: AnalysisResult, cuesheet: CueSheet) -> MusiCueBundle:
    if analysis.source.sha256 != cuesheet.source_sha256:
        raise ValueError(
            f"Analysis sha256={analysis.source.sha256} does not match "
            f"cuesheet sha256={cuesheet.source_sha256}"
        )

    return MusiCueBundle(
        source_sha256=analysis.source.sha256,
        duration_sec=analysis.source.duration_sec,
        fps=cuesheet.fps,
        tempo=analysis.tempo if analysis.tempo else _default_tempo(),
        beats=analysis.beats,
        sections=_build_sections(analysis),
        drums={},
        midi={},
        midi_energy={},
        stems_energy={},
        global_energy=StemEnergyCurve(hop_sec=0.04, values=[]),
        cuesheet=cuesheet,
    )


def _default_tempo():
    from musicue.schemas import TempoInfo
    return TempoInfo(bpm_global=120.0)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_bundle_builder.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add musicue/compile/bundle.py tests/test_bundle_builder.py
git commit -m "feat(bundle): build_bundle with sha cross-check and section ranking"
```

---

### Task 1.3: `build_bundle()` — drums regrouping

**Files:**
- Modify: `musicue/compile/bundle.py`
- Test: `tests/test_bundle_builder.py` (extend)

- [ ] **Step 1: Append failing test**

Append to `tests/test_bundle_builder.py`:

```python
from musicue.schemas import OnsetEvent


def test_drums_regrouped_by_drum_class():
    analysis = _analysis()
    analysis.onsets = {
        "drums": [
            OnsetEvent(t=0.5, strength=1.0, drum_class="kick"),
            OnsetEvent(t=0.6, strength=0.5, drum_class="snare"),
            OnsetEvent(t=0.7, strength=0.8, drum_class="kick"),
            OnsetEvent(t=0.8, strength=0.6, drum_class=None),   # dropped
        ]
    }

    bundle = build_bundle(analysis, _cuesheet())

    assert set(bundle.drums.keys()) == {"kick", "snare"}
    assert len(bundle.drums["kick"]) == 2
    assert len(bundle.drums["snare"]) == 1
    assert bundle.drums["kick"][0].t == 0.5
    assert bundle.drums["kick"][0].strength == 1.0


def test_drums_missing_section_handled():
    analysis = _analysis()                            # no onsets at all
    bundle = build_bundle(analysis, _cuesheet())
    assert bundle.drums == {}
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_bundle_builder.py::test_drums_regrouped_by_drum_class -v`
Expected: AssertionError — drums always `{}`.

- [ ] **Step 3: Add drum regrouping to `build_bundle()`**

In `musicue/compile/bundle.py`, add helper before `build_bundle`:

```python
def _build_drums(analysis: AnalysisResult) -> dict[str, list[DrumOnset]]:
    out: dict[str, list[DrumOnset]] = {}
    for onset in analysis.onsets.get("drums", []):
        if onset.drum_class is None:
            continue
        out.setdefault(onset.drum_class, []).append(
            DrumOnset(t=onset.t, strength=onset.strength, confidence=onset.drum_class_conf)
        )
    return out
```

Replace `drums={}` in `build_bundle`'s return with `drums=_build_drums(analysis)`.

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_bundle_builder.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add musicue/compile/bundle.py tests/test_bundle_builder.py
git commit -m "feat(bundle): regroup drum onsets by drum_class"
```

---

### Task 1.4: `build_bundle()` — MIDI passthrough + `midi_energy` curves

**Files:**
- Modify: `musicue/compile/bundle.py`
- Test: `tests/test_bundle_builder.py` (extend)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_bundle_builder.py`:

```python
from musicue.schemas import MidiNote


def test_midi_notes_passed_through():
    analysis = _analysis()
    analysis.midi = {
        "vocals": [
            MidiNote(t=0.0, duration=0.5, pitch=60, velocity=80),
            MidiNote(t=1.0, duration=0.25, pitch=64, velocity=100),
        ]
    }
    bundle = build_bundle(analysis, _cuesheet())

    assert "vocals" in bundle.midi
    assert len(bundle.midi["vocals"]) == 2
    assert bundle.midi["vocals"][0].pitch == 60
    assert bundle.midi["vocals"][1].velocity == 100


def test_midi_energy_curve_derived_per_stem():
    analysis = _analysis()
    # Single 1-second-long note touching bins 0..25 at hop 0.04s
    analysis.midi = {
        "vocals": [MidiNote(t=0.0, duration=1.0, pitch=60, velocity=127)],
    }
    bundle = build_bundle(analysis, _cuesheet())

    energy = bundle.midi_energy["vocals"]
    assert energy.hop_sec == 0.04
    expected_bins = int(10.0 / 0.04)               # duration_sec / hop_sec
    assert len(energy.values) == expected_bins
    # Bins 0..25 (first second) should be ~1.0; later bins ~0.0
    assert energy.values[0] > 0.95
    assert energy.values[24] > 0.95
    assert energy.values[30] < 0.05
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_bundle_builder.py -k midi -v`
Expected: KeyError or AssertionError — midi fields still empty.

- [ ] **Step 3: Add MIDI passthrough + density-curve builder**

In `musicue/compile/bundle.py`, add helpers:

```python
def _build_midi(analysis: AnalysisResult) -> dict[str, list[MidiNoteBundle]]:
    out: dict[str, list[MidiNoteBundle]] = {}
    for stem, notes in analysis.midi.items():
        out[stem] = [
            MidiNoteBundle(t=n.t, duration=n.duration, pitch=n.pitch, velocity=n.velocity)
            for n in notes
        ]
    return out


def _build_midi_energy(
    analysis: AnalysisResult, hop_sec: float, duration_sec: float
) -> dict[str, StemEnergyCurve]:
    if hop_sec <= 0:
        return {}
    n_bins = int(duration_sec / hop_sec)
    out: dict[str, StemEnergyCurve] = {}
    for stem, notes in analysis.midi.items():
        values = [0.0] * n_bins
        for note in notes:
            note_end = note.t + note.duration
            bin_start = max(0, int(note.t / hop_sec))
            bin_end = min(n_bins, int(note_end / hop_sec) + 1)
            vel_norm = note.velocity / 127.0
            for b in range(bin_start, bin_end):
                bin_t0 = b * hop_sec
                bin_t1 = bin_t0 + hop_sec
                overlap = max(0.0, min(bin_t1, note_end) - max(bin_t0, note.t))
                values[b] += vel_norm * (overlap / hop_sec)
        # Clip to [0, 1]
        values = [max(0.0, min(1.0, v)) for v in values]
        out[stem] = StemEnergyCurve(hop_sec=hop_sec, values=values)
    return out
```

In `build_bundle()`, wire them in. Pull `hop_sec` from `analysis.analysis_config.curve_hop_sec`:

```python
    hop_sec = analysis.analysis_config.curve_hop_sec
    return MusiCueBundle(
        ...
        drums=_build_drums(analysis),
        midi=_build_midi(analysis),
        midi_energy=_build_midi_energy(analysis, hop_sec, analysis.source.duration_sec),
        ...
    )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_bundle_builder.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add musicue/compile/bundle.py tests/test_bundle_builder.py
git commit -m "feat(bundle): pass through MIDI and derive per-stem midi_energy curves"
```

---

### Task 1.5: `build_bundle()` — global_energy + cuesheet embedding

**Files:**
- Modify: `musicue/compile/bundle.py`
- Test: `tests/test_bundle_builder.py` (extend)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_bundle_builder.py`:

```python
from musicue.schemas import TimedCurve


def test_global_energy_normalized_from_lufs_curve():
    analysis = _analysis()
    analysis.curves = {"lufs": TimedCurve(hop_sec=0.04, values=[-30.0, -20.0, -10.0, 0.0])}

    bundle = build_bundle(analysis, _cuesheet())

    assert bundle.global_energy.hop_sec == 0.04
    assert bundle.global_energy.values[0] == 0.0
    assert bundle.global_energy.values[-1] == 1.0


def test_global_energy_empty_when_no_lufs_curve():
    bundle = build_bundle(_analysis(), _cuesheet())
    assert bundle.global_energy.values == []


def test_cuesheet_embedded_verbatim():
    cs = _cuesheet()
    cs.grammar = "lighting"
    bundle = build_bundle(_analysis(), cs)

    assert bundle.cuesheet.grammar == "lighting"
    assert bundle.cuesheet.source_sha256 == cs.source_sha256
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_bundle_builder.py -k "global_energy or cuesheet_embedded" -v`
Expected: AssertionError — `global_energy` still has empty values.

- [ ] **Step 3: Add global energy normalization**

In `musicue/compile/bundle.py`:

```python
def _build_global_energy(analysis: AnalysisResult) -> StemEnergyCurve:
    curve = analysis.curves.get("lufs")
    if curve is None or not curve.values:
        return StemEnergyCurve(hop_sec=0.04, values=[])
    return StemEnergyCurve(hop_sec=curve.hop_sec, values=_normalize(curve.values))
```

In `build_bundle()`, replace the `global_energy=StemEnergyCurve(...)` line with:

```python
        global_energy=_build_global_energy(analysis),
```

(The cuesheet is already embedded verbatim — that test should already pass.)

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_bundle_builder.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add musicue/compile/bundle.py tests/test_bundle_builder.py
git commit -m "feat(bundle): normalize global LUFS curve into global_energy"
```

---

### Task 1.6: `musicue export-bundle` CLI command

**Files:**
- Modify: `musicue/cli.py`
- Test: `tests/test_bundle_cli.py`

MusiCue's CLI uses Typer. The new `export-bundle` command takes an audio path and emits `<audio_stem>.musicue.json` next to it. It auto-runs `analyze` if no analysis.json is available and `compile` if no cuesheet.json is available.

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_bundle_cli.py`:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from musicue.cli import app
from musicue.schemas import (
    AnalysisConfig,
    AnalysisResult,
    CueSheet,
    MusiCueBundle,
    SourceInfo,
    TempoInfo,
)

runner = CliRunner()


def _write_minimal_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake-audio-bytes")
    import hashlib
    sha = hashlib.sha256(audio.read_bytes()).hexdigest()

    analysis_dir = tmp_path / "song"
    analysis_dir.mkdir()
    analysis = AnalysisResult(
        source=SourceInfo(path=str(audio), sha256=sha, duration_sec=1.0, sample_rate=44100),
        analysis_config=AnalysisConfig(),
        stems={},
        tempo=TempoInfo(bpm_global=120.0),
    )
    analysis_path = analysis_dir / "analysis.json"
    analysis_path.write_text(analysis.model_dump_json())

    cuesheet = CueSheet(source_sha256=sha, grammar="concert_visuals", duration_sec=1.0)
    cuesheet_path = tmp_path / "song.cuesheet.json"
    cuesheet_path.write_text(cuesheet.model_dump_json())

    return audio, analysis_path, cuesheet_path


def test_export_bundle_writes_sibling_file(tmp_path):
    audio, analysis_path, cuesheet_path = _write_minimal_artifacts(tmp_path)

    result = runner.invoke(app, [
        "export-bundle", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
    ])

    assert result.exit_code == 0, result.output
    expected = tmp_path / "song.musicue.json"
    assert expected.exists()

    bundle = MusiCueBundle.model_validate_json(expected.read_text())
    assert bundle.schema_version == "1.0"
    assert bundle.duration_sec == 1.0


def test_export_bundle_explicit_output(tmp_path):
    audio, analysis_path, cuesheet_path = _write_minimal_artifacts(tmp_path)
    output = tmp_path / "custom.musicue.json"

    result = runner.invoke(app, [
        "export-bundle", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
        "--output", str(output),
    ])

    assert result.exit_code == 0, result.output
    assert output.exists()


def test_export_bundle_refuses_existing_without_force(tmp_path):
    audio, analysis_path, cuesheet_path = _write_minimal_artifacts(tmp_path)
    target = tmp_path / "song.musicue.json"
    target.write_text("{}")

    result = runner.invoke(app, [
        "export-bundle", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
    ])
    assert result.exit_code != 0

    # With --force it overwrites
    result2 = runner.invoke(app, [
        "export-bundle", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
        "--force",
    ])
    assert result2.exit_code == 0, result2.output
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_bundle_cli.py -v`
Expected: Typer exit code != 0 — command doesn't exist.

- [ ] **Step 3: Add `export_bundle` command to `musicue/cli.py`**

Append to `musicue/cli.py` (after the existing `export` command):

```python
@app.command(name="export-bundle")
def export_bundle(
    audio: Path = typer.Argument(..., help="Audio file (wav/flac/mp3)"),
    analysis: Optional[Path] = typer.Option(None, "--analysis"),
    cuesheet: Optional[Path] = typer.Option(None, "--cuesheet"),
    grammar: str = typer.Option("concert_visuals", "--grammar", "-g"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Compose AnalysisResult + CueSheet into a CedarToy-targeted song.musicue.json."""
    from musicue.compile.bundle import build_bundle
    from musicue.compile.compiler import compile_analysis
    from musicue.analysis.pipeline import run_analysis
    from musicue.config import MusiCueConfig
    from musicue.schemas import AnalysisResult, CueSheet

    target = output if output else audio.with_suffix("").with_suffix(".musicue.json")
    if target.exists() and not force:
        typer.echo(f"Refusing to overwrite {target}; pass --force to override.", err=True)
        raise typer.Exit(code=1)

    # Discovery / auto-run for analysis
    if analysis is None:
        cfg = MusiCueConfig()
        candidate = cfg.runs_dir / audio.stem / "analysis.json"
        if candidate.exists():
            analysis = candidate
        else:
            typer.echo(f"No analysis found; running pipeline on {audio}.")
            result = run_analysis(audio, cfg)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(result.model_dump_json(indent=2))
            analysis = candidate

    analysis_obj = AnalysisResult.model_validate_json(analysis.read_text())

    # Discovery / auto-compile for cuesheet
    if cuesheet is None:
        sibling = audio.with_suffix("").with_suffix(".cuesheet.json")
        if sibling.exists():
            cuesheet = sibling
            cs_obj = CueSheet.model_validate_json(sibling.read_text())
        else:
            typer.echo(f"No cuesheet found; compiling with grammar '{grammar}'.")
            cs_obj = compile_analysis(analysis_obj, grammar=grammar)
    else:
        cs_obj = CueSheet.model_validate_json(cuesheet.read_text())

    bundle = build_bundle(analysis_obj, cs_obj)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bundle.model_dump_json(indent=2))
    typer.echo(f"Bundle written to {target}")
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_bundle_cli.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the entire MusiCue suite to catch regressions**

Run: `python -m pytest tests/ -x`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add musicue/cli.py tests/test_bundle_cli.py
git commit -m "feat(cli): add musicue export-bundle command"
```

---

### Task 1.7: Phase 1 smoke + handoff fixture

**Files:**
- Create: `tests/fixtures/sample.musicue.json` (committed for use by Phase 2 CedarToy tests)

This task generates a real, committed bundle JSON that Phase 2 (CedarToy) tests can use as a golden fixture. CedarToy tests still construct synthetic in-memory bundles for unit coverage, but the fixture proves the two schemas agree.

- [ ] **Step 1: Run `export-bundle` against the existing repo fixture audio**

Identify a small fixture WAV (or generate one). If `tests/fixtures/short.wav` exists, use it. Otherwise generate one:

```bash
python -c "import numpy as np, wave; n=44100; w=wave.open('tests/fixtures/sample.wav','wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(n); w.writeframes((np.sin(2*np.pi*440*np.arange(n)/n)*16384).astype(np.int16).tobytes()); w.close()"
```

- [ ] **Step 2: Generate bundle**

Run: `python -m musicue.cli export-bundle tests/fixtures/sample.wav --output tests/fixtures/sample.musicue.json`
Expected: a `sample.musicue.json` file written.

If the auto-pipeline is too heavyweight for tests (loads demucs etc.), hand-roll a minimal bundle:

```python
# Optional fallback: write a hand-crafted bundle directly
from musicue.schemas import MusiCueBundle, CueSheet, TempoInfo, StemEnergyCurve
import hashlib, json
from pathlib import Path

audio = Path("tests/fixtures/sample.wav")
sha = hashlib.sha256(audio.read_bytes()).hexdigest()
b = MusiCueBundle(
    source_sha256=sha, duration_sec=1.0, fps=24.0,
    tempo=TempoInfo(bpm_global=120.0),
    global_energy=StemEnergyCurve(hop_sec=0.04, values=[0.5]*25),
    cuesheet=CueSheet(source_sha256=sha, grammar="concert_visuals", duration_sec=1.0),
)
Path("tests/fixtures/sample.musicue.json").write_text(b.model_dump_json(indent=2))
```

- [ ] **Step 3: Add a round-trip test**

Append to `tests/test_bundle_cli.py`:

```python
def test_committed_fixture_roundtrips():
    fixture = Path("tests/fixtures/sample.musicue.json")
    if not fixture.exists():
        return  # Skip if fixture not generated for this environment
    bundle = MusiCueBundle.model_validate_json(fixture.read_text())
    assert bundle.schema_version.startswith("1.")
```

- [ ] **Step 4: Run tests + commit fixture**

Run: `python -m pytest tests/test_bundle_cli.py -v`
Expected: all passed.

```bash
git add tests/fixtures/sample.wav tests/fixtures/sample.musicue.json tests/test_bundle_cli.py
git commit -m "test(bundle): commit golden bundle fixture for downstream consumers"
```

**End of Phase 1.** The MusiCue side is complete and tested. Phase 2 can now begin.

---

## Phase 2: CedarToy side (D:\cedartoy)

### File structure (Phase 2)

| Path | Role |
|---|---|
| `cedartoy/musicue.py` | NEW — schema mirror, `BundleEvaluator`, `MusicalSpectrumSynth`, loader |
| `cedartoy/config_model.py` | MODIFY — add `bundle_path`, `bundle_mode`, `bundle_blend` |
| `cedartoy/options_schema.py` | MODIFY — three new `Option` entries |
| `cedartoy/types.py` | MODIFY — append three fields to `RenderJob` |
| `cedartoy/render.py` | MODIFY — `_mix_audio_textures`, `_builtin_uniforms_from_eval`, init hook, per-frame texture mix + uniform binding |
| `cedartoy/cli.py` | MODIFY — `--bundle`, `--bundle-mode`, `--bundle-blend` flags |
| `web/js/components/config-editor.js` | MODIFY — surface three new fields in audio section |
| `tests/test_musicue_schema.py` | NEW |
| `tests/test_musicue_evaluator.py` | NEW |
| `tests/test_musicue_synth.py` | NEW |
| `tests/test_musicue_loader.py` | NEW |
| `tests/test_musicue_integration.py` | NEW |
| `docs/AUDIO_SYSTEM.md` + `README.md` | MODIFY |

All Phase 2 paths are relative to `D:\cedartoy\`.

---

### Task 2.1: Bundle mirror schema + version gate

**Files:**
- Create: `cedartoy/musicue.py`
- Test: `tests/test_musicue_schema.py`

The mirror is lean: it only includes fields CedarToy reads. The embedded cuesheet stays as `dict[str, Any]` since CedarToy never deserializes it in Phase 1.

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_musicue_schema.py`:

```python
import json
from pathlib import Path

import pytest

from cedartoy.musicue import (
    MusiCueBundle,
    SUPPORTED_SCHEMA_MAJOR,
    UnsupportedSchemaError,
    load_bundle,
)


def _payload(schema_version: str = "1.0") -> dict:
    return {
        "schema_version": schema_version,
        "source_sha256": "x" * 64,
        "duration_sec": 10.0,
        "fps": 24.0,
        "tempo": {"bpm_global": 120.0, "bpm_curve": [], "time_signature": [4, 4]},
        "beats": [],
        "sections": [],
        "drums": {},
        "midi": {},
        "midi_energy": {},
        "stems_energy": {},
        "global_energy": {"hop_sec": 0.04, "values": []},
        "cuesheet": {"schema_version": "1.2", "source_sha256": "x" * 64,
                     "grammar": "concert_visuals", "duration_sec": 10.0,
                     "fps": 24.0, "drop_frame": False, "tempo_map": [], "tracks": []},
    }


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


def test_loads_minimal_bundle(tmp_path):
    bundle = load_bundle(_write(tmp_path, "b.musicue.json", _payload()))
    assert isinstance(bundle, MusiCueBundle)
    assert bundle.schema_version == "1.0"
    assert bundle.duration_sec == 10.0


def test_rejects_unsupported_major(tmp_path):
    path = _write(tmp_path, "b.musicue.json", _payload("2.0"))
    with pytest.raises(UnsupportedSchemaError) as exc:
        load_bundle(path)
    assert "2.0" in str(exc.value)
    assert str(SUPPORTED_SCHEMA_MAJOR) in str(exc.value)


def test_accepts_higher_minor(tmp_path):
    bundle = load_bundle(_write(tmp_path, "b.musicue.json", _payload("1.7")))
    assert bundle.schema_version == "1.7"


def test_rejects_malformed_json(tmp_path):
    path = tmp_path / "b.musicue.json"
    path.write_text("not json")
    with pytest.raises(ValueError):
        load_bundle(path)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_musicue_schema.py -v`
Expected: ImportError — `cedartoy.musicue` doesn't exist.

- [ ] **Step 3: Create `cedartoy/musicue.py`**

```python
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

    cuesheet: Dict[str, Any]                # kept opaque — CedarToy doesn't introspect


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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_musicue_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_musicue_schema.py
git commit -m "feat(musicue): mirror MusiCueBundle schema with version-gated loader"
```

---

### Task 2.2: `BundleEvaluator` — tempo, beats, bar

**Files:**
- Modify: `cedartoy/musicue.py` (append `EvalFrame` + `BundleEvaluator` with bpm/beat/bar logic)
- Test: `tests/test_musicue_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Create `tests/test_musicue_evaluator.py`:

```python
import pytest

from cedartoy.musicue import (
    BeatEvent,
    BundleEvaluator,
    EvalFrame,
    MusiCueBundle,
    StemEnergyCurve,
    TempoInfo,
)


def _bundle(*, beats=None, tempo_bpm=120.0, duration=4.0) -> MusiCueBundle:
    return MusiCueBundle(
        schema_version="1.0",
        source_sha256="x" * 64,
        duration_sec=duration,
        fps=24.0,
        tempo=TempoInfo(bpm_global=tempo_bpm),
        beats=beats or [],
        global_energy=StemEnergyCurve(hop_sec=0.04, values=[]),
        cuesheet={},
    )


def test_bpm_from_global():
    ev = BundleEvaluator(_bundle(tempo_bpm=128.0), fps=24.0)
    assert ev.evaluate(0).bpm == pytest.approx(128.0)


def test_beat_phase_advances_linearly():
    beats = [
        BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
        BeatEvent(t=0.5, beat_in_bar=1, bar=0, is_downbeat=False),
        BeatEvent(t=1.0, beat_in_bar=2, bar=0, is_downbeat=False),
    ]
    ev = BundleEvaluator(_bundle(beats=beats), fps=24.0)
    # t=0.25s sits halfway between beats[0] (t=0.0) and beats[1] (t=0.5)
    assert ev.evaluate(int(round(0.25 * 24.0))).beat_phase == pytest.approx(0.5, abs=0.05)


def test_bar_from_downbeats():
    beats = [
        BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
        BeatEvent(t=2.0, beat_in_bar=0, bar=1, is_downbeat=True),
    ]
    ev = BundleEvaluator(_bundle(beats=beats), fps=24.0)
    assert ev.evaluate(int(round(0.5 * 24.0))).bar == 0
    assert ev.evaluate(int(round(2.5 * 24.0))).bar == 1


def test_bar_fallback_when_no_downbeats():
    ev = BundleEvaluator(_bundle(tempo_bpm=120.0), fps=24.0)
    # bps=2, beats_per_bar=4 → 1 bar every 2s
    assert ev.evaluate(int(round(0.0 * 24.0))).bar == 0
    assert ev.evaluate(int(round(2.5 * 24.0))).bar == 1


def test_empty_bundle_returns_zero_phase():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    frame = ev.evaluate(0)
    assert frame.beat_phase == 0.0
    assert frame.bar == 0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_musicue_evaluator.py -v`
Expected: ImportError — `EvalFrame` and `BundleEvaluator` don't exist.

- [ ] **Step 3: Append `EvalFrame` + `BundleEvaluator` (beats/bar/bpm)**

Append to `cedartoy/musicue.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_musicue_evaluator.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_musicue_evaluator.py
git commit -m "feat(musicue): BundleEvaluator with bpm/beat_phase/bar"
```

---

### Task 2.3: `BundleEvaluator` — section energy, global energy, drum pulses with ADSR, MIDI

**Files:**
- Modify: `cedartoy/musicue.py`
- Test: `tests/test_musicue_evaluator.py` (extend)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_musicue_evaluator.py`:

```python
from cedartoy.musicue import DrumOnset, MidiNoteBundle, SectionBundleEntry


def test_section_energy_lookup():
    sections = [
        SectionBundleEntry(start=0.0, end=4.0, label="intro", energy_rank=0.3),
        SectionBundleEntry(start=4.0, end=8.0, label="chorus", energy_rank=0.9),
    ]
    b = _bundle()
    b.sections = sections
    ev = BundleEvaluator(b, fps=24.0)
    assert ev.evaluate(int(round(2.0 * 24.0))).section_energy == pytest.approx(0.3)
    assert ev.evaluate(int(round(6.0 * 24.0))).section_energy == pytest.approx(0.9)


def test_global_energy_interpolation():
    b = _bundle(duration=2.0)
    b.global_energy = StemEnergyCurve(hop_sec=1.0, values=[0.0, 1.0, 0.0])
    ev = BundleEvaluator(b, fps=24.0)
    # t=0.5 sits halfway between values[0]=0 and values[1]=1
    assert ev.evaluate(int(round(0.5 * 24.0))).global_energy == pytest.approx(0.5, abs=0.02)


def test_kick_pulse_peaks_at_event_time():
    b = _bundle()
    b.drums = {"kick": [DrumOnset(t=1.0, strength=1.0)]}
    ev = BundleEvaluator(b, fps=24.0)
    peak = ev.evaluate(int(round(1.0 * 24.0))).drum_pulses["kick"]
    assert peak == pytest.approx(1.0, abs=0.05)


def test_kick_pulse_decays_within_default_adsr():
    b = _bundle()
    b.drums = {"kick": [DrumOnset(t=1.0, strength=1.0)]}
    ev = BundleEvaluator(b, fps=24.0)
    # 0.5s after the hit — default decay is 0.08s, value should be ~0
    assert ev.evaluate(int(round(1.5 * 24.0))).drum_pulses["kick"] < 0.05


def test_midi_energy_lookup():
    b = _bundle()
    b.midi_energy = {"vocals": StemEnergyCurve(hop_sec=1.0, values=[0.2, 0.8, 0.0])}
    ev = BundleEvaluator(b, fps=24.0)
    val = ev.evaluate(int(round(0.5 * 24.0))).midi_energy["vocals"]
    assert val == pytest.approx(0.5, abs=0.02)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_musicue_evaluator.py -v`
Expected: 5 prior pass + 5 new fail (fields stay at defaults).

- [ ] **Step 3: Extend `BundleEvaluator`**

Replace the `BundleEvaluator` class in `cedartoy/musicue.py` with the extended version:

```python
_DEFAULT_ADSR = (0.005, 0.08, 0.0, 0.0)  # A, D, S, R in seconds (S is unitless level)


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


def _sample_curve(curve: StemEnergyCurve, t: float) -> float:
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
        # Pre-sort drum onsets per class for fast lookup.
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

    def _curve_dict_at(self, curves: Dict[str, StemEnergyCurve], t: float) -> Dict[str, float]:
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_musicue_evaluator.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_musicue_evaluator.py
git commit -m "feat(musicue): section/global/drum/midi/stems evaluation with ADSR decay"
```

---

### Task 2.4: `MusicalSpectrumSynth` — synthesize the 2×512 iChannel0 texture

**Files:**
- Modify: `cedartoy/musicue.py`
- Test: `tests/test_musicue_synth.py`

- [ ] **Step 1: Write failing synth tests**

Create `tests/test_musicue_synth.py`:

```python
import numpy as np
import pytest

from cedartoy.musicue import EvalFrame, MusicalSpectrumSynth


def test_shape_and_dtype():
    tex = MusicalSpectrumSynth().synthesize(EvalFrame())
    assert tex.shape == (2, 512)
    assert tex.dtype == np.float32


def test_kick_drives_low_bins():
    tex = MusicalSpectrumSynth().synthesize(EvalFrame(drum_pulses={"kick": 1.0}))
    assert tex[0, 0:32].max() > 0.5
    assert tex[0, 96:256].max() < 0.1


def test_snare_and_tom_drive_low_mid():
    tex = MusicalSpectrumSynth().synthesize(
        EvalFrame(drum_pulses={"snare": 0.7, "tom": 0.3})
    )
    assert tex[0, 32:96].max() > 0.5


def test_hat_and_cymbal_drive_mid_high():
    tex = MusicalSpectrumSynth().synthesize(
        EvalFrame(drum_pulses={"hat": 0.6, "cymbal": 0.5})
    )
    assert tex[0, 96:256].max() > 0.5
    assert tex[0, 0:32].max() < 0.1


def test_midi_drives_high_bins():
    tex = MusicalSpectrumSynth().synthesize(
        EvalFrame(midi_energy={"vocals": 0.8, "other": 0.2})
    )
    assert tex[0, 256:512].max() > 0.5
    assert tex[0, 0:96].max() < 0.1


def test_section_energy_baseline_tilt():
    quiet = MusicalSpectrumSynth().synthesize(EvalFrame())
    loud = MusicalSpectrumSynth().synthesize(EvalFrame(section_energy=0.8))
    assert loud[0].mean() > quiet[0].mean()
    assert loud[0].mean() == pytest.approx(0.08, abs=0.02)


def test_waveform_row_locked_to_beat_phase():
    at_zero = MusicalSpectrumSynth().synthesize(
        EvalFrame(beat_phase=0.0, global_energy=1.0)
    )
    quarter = MusicalSpectrumSynth().synthesize(
        EvalFrame(beat_phase=0.25, global_energy=1.0)
    )
    assert at_zero[1].mean() == pytest.approx(0.5, abs=0.01)
    assert quarter[1].mean() == pytest.approx(1.0, abs=0.01)


def test_clamped_to_unit_range():
    saturated = EvalFrame(
        drum_pulses={"kick": 1.0, "snare": 1.0, "tom": 1.0, "hat": 1.0, "cymbal": 1.0},
        midi_energy={"vocals": 1.0, "other": 1.0},
        section_energy=1.0, global_energy=1.0,
    )
    tex = MusicalSpectrumSynth().synthesize(saturated)
    assert tex.min() >= 0.0
    assert tex.max() <= 1.0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_musicue_synth.py -v`
Expected: ImportError — `MusicalSpectrumSynth` doesn't exist.

- [ ] **Step 3: Append `MusicalSpectrumSynth` to `cedartoy/musicue.py`**

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_musicue_synth.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_musicue_synth.py
git commit -m "feat(musicue): MusicalSpectrumSynth with MIDI-driven high bins"
```

---

### Task 2.5: Loader — sibling discovery, sha, `load_for_audio`

**Files:**
- Modify: `cedartoy/musicue.py`
- Test: `tests/test_musicue_loader.py`

- [ ] **Step 1: Write failing loader tests**

Create `tests/test_musicue_loader.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_musicue_loader.py -v`
Expected: ImportError — loader symbols not defined yet.

- [ ] **Step 3: Append loader to `cedartoy/musicue.py`**

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_musicue_loader.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_musicue_loader.py
git commit -m "feat(musicue): sibling discovery + sha-validating bundle loader"
```

---

### Task 2.6: Config / RenderJob / options additions

**Files:**
- Modify: `cedartoy/config_model.py`
- Modify: `cedartoy/types.py`
- Modify: `cedartoy/options_schema.py`
- Test: `tests/test_config_model.py` (extend)

- [ ] **Step 1: Write failing config tests**

Append to `tests/test_config_model.py`:

```python
def test_bundle_fields_have_safe_defaults():
    cfg = CedarToyConfig(shader=Path("shaders/test.glsl"))
    assert cfg.bundle_path is None
    assert cfg.bundle_mode == "auto"
    assert cfg.bundle_blend == 0.5


def test_bundle_path_accepts_explicit_path():
    cfg = CedarToyConfig(
        shader=Path("shaders/test.glsl"),
        bundle_path=Path("song.musicue.json"),
    )
    assert cfg.bundle_path == Path("song.musicue.json")


def test_bundle_mode_rejects_unknown():
    with pytest.raises(ValueError):
        CedarToyConfig(shader=Path("shaders/test.glsl"), bundle_mode="bogus")


def test_bundle_blend_must_be_in_unit_range():
    with pytest.raises(ValueError, match="bundle_blend"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), bundle_blend=1.5)
    with pytest.raises(ValueError, match="bundle_blend"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), bundle_blend=-0.1)
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_config_model.py -v`
Expected: 4 new failures on bundle fields.

- [ ] **Step 3: Add fields to `cedartoy/config_model.py`**

Near the existing `AudioMode` alias, add:

```python
BundleMode = Literal["auto", "raw", "cued", "blend"]
```

Inside `CedarToyConfig`, after the existing `audio_mode: AudioMode = "both"` line:

```python
    bundle_path: Optional[Path] = None
    bundle_mode: BundleMode = "auto"
    bundle_blend: float = 0.5
```

Before `to_runtime_dict`, add the validator:

```python
    @field_validator("bundle_blend")
    @classmethod
    def _bundle_blend_in_unit_range(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("bundle_blend must be between 0 and 1")
        return v
```

(`field_validator` is already imported in `config_model.py` — verified during design.)

- [ ] **Step 4: Append fields to `RenderJob` in `cedartoy/types.py`**

Add to the END of the `RenderJob` dataclass (after `shader_parameters`):

```python
    # MusiCue bundle integration
    bundle_path: Optional[Path] = None
    bundle_mode: str = "auto"
    bundle_blend: float = 0.5
```

Placing them at the end avoids defaulted-field-before-non-defaulted-field SyntaxError, since `RenderJob` has many trailing fields without defaults in the middle.

- [ ] **Step 5: Add `Option` entries to `cedartoy/options_schema.py`**

After the existing `audio_mode` option (currently `options_schema.py:80`), insert:

```python
OPTIONS.append(Option("bundle_path", "Bundle Path", "path", None,
    help_text="Path to a MusiCue bundle JSON (defaults to sibling of audio_path)."))
OPTIONS.append(Option("bundle_mode", "Bundle Mode", "choice", "auto",
    choices=["auto", "raw", "cued", "blend"],
    help_text="auto=cued when bundle present; raw=ignore; cued=synthesized; blend=mix"))
OPTIONS.append(Option("bundle_blend", "Bundle Blend (0-1)", "float", 0.5,
    help_text="Mix weight for cued texture when bundle_mode='blend'"))
```

- [ ] **Step 6: Run config tests — expect pass**

Run: `python -m pytest tests/test_config_model.py -v`
Expected: existing + 4 new all pass.

- [ ] **Step 7: Commit**

```bash
git add cedartoy/config_model.py cedartoy/types.py cedartoy/options_schema.py tests/test_config_model.py
git commit -m "feat(config): add bundle_path/mode/blend fields end-to-end"
```

---

### Task 2.7: Render integration — texture mix helper + uniform-from-eval helper

**Files:**
- Modify: `cedartoy/render.py`
- Test: `tests/test_musicue_integration.py`

The two helpers can be unit-tested in isolation without OpenGL. The actual `Renderer.__init__` wiring happens in Task 2.8 where it's exercised by the manual visual smoke; we get unit coverage on the pure-Python helpers here.

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_musicue_integration.py`:

```python
import numpy as np
import pytest

from cedartoy.musicue import EvalFrame
from cedartoy.render import _builtin_uniforms_from_eval, _mix_audio_textures


def test_mix_raw_only():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="raw", blend=0.5), 0.2)


def test_mix_cued_only():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="cued", blend=0.5), 0.8)


def test_mix_blend_50_50():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="blend", blend=0.5), 0.5)


def test_mix_blend_weighted():
    raw = np.full((2, 512), 0.0, dtype=np.float32)
    cued = np.full((2, 512), 1.0, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="blend", blend=0.25), 0.25)


def test_builtin_uniforms_from_eval_frame():
    frame = EvalFrame(bpm=128.0, beat_phase=0.25, bar=3,
                      section_energy=0.7, global_energy=0.6)
    uni = _builtin_uniforms_from_eval(frame)
    assert uni["iBpm"] == pytest.approx(128.0)
    assert uni["iBeat"] == pytest.approx(0.25)
    assert uni["iBar"] == 3
    assert uni["iSectionEnergy"] == pytest.approx(0.7)
    assert uni["iEnergy"] == pytest.approx(0.6)


def test_builtin_uniforms_none_returns_defaults():
    uni = _builtin_uniforms_from_eval(None)
    assert uni == {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0, "iSectionEnergy": 0.0, "iEnergy": 0.0}
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_musicue_integration.py -v`
Expected: ImportError — helpers not in `render.py`.

- [ ] **Step 3: Add helpers near the top of `cedartoy/render.py`**

After the imports, before the `Renderer` class:

```python
import numpy as np
from typing import Any, Dict, Optional


def _mix_audio_textures(
    raw: np.ndarray,
    cued: np.ndarray,
    mode: str,
    blend: float,
) -> np.ndarray:
    """Combine raw FFT + synthesized cued textures per bundle_mode."""
    if mode == "raw":
        return raw
    if mode == "cued":
        return cued
    if mode == "blend":
        b = max(0.0, min(1.0, float(blend)))
        return (raw * (1.0 - b) + cued * b).astype(np.float32)
    return cued                                  # auto resolved upstream → cued fallback


def _builtin_uniforms_from_eval(eval_frame) -> Dict[str, Any]:
    """Translate an EvalFrame (or None) into the five Phase 1 built-in uniforms."""
    if eval_frame is None:
        return {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0,
                "iSectionEnergy": 0.0, "iEnergy": 0.0}
    return {
        "iBpm": float(eval_frame.bpm),
        "iBeat": float(eval_frame.beat_phase),
        "iBar": int(eval_frame.bar),
        "iSectionEnergy": float(eval_frame.section_energy),
        "iEnergy": float(eval_frame.global_energy),
    }
```

(If `numpy as np` is already imported in `render.py`, skip that import line.)

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests/test_musicue_integration.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/render.py tests/test_musicue_integration.py
git commit -m "feat(render): texture-mix + uniform-from-eval helpers"
```

---

### Task 2.8: Render integration — `Renderer.__init__` + per-frame wiring

**Files:**
- Modify: `cedartoy/render.py`

This task wires the bundle into the actual render loop. The pure-Python helpers from Task 2.7 are now invoked from inside `Renderer`. No new unit tests at this level — coverage comes from Task 2.7 helpers + Task 2.10 manual visual smoke.

- [ ] **Step 1: Locate hook points**

Search `cedartoy/render.py`:

```bash
grep -n "AudioProcessor(" cedartoy/render.py
grep -n "audio_tex_512" cedartoy/render.py
grep -n "shader_parameters.items" cedartoy/render.py
```

Note the line numbers — they're the three sites we'll modify.

- [ ] **Step 2: Wire bundle load into `Renderer.__init__`**

After the existing `self.audio = AudioProcessor(...)` block, add:

```python
        # MusiCue bundle integration
        self.bundle_eval = None
        self.spectrum_synth = None
        self.bundle_mode = getattr(job, "bundle_mode", "auto")
        self.bundle_blend = getattr(job, "bundle_blend", 0.5)

        if self.audio and self.bundle_mode != "raw" and job.audio_path is not None:
            from .musicue import BundleEvaluator, MusicalSpectrumSynth, load_for_audio
            result = load_for_audio(job.audio_path, override_path=getattr(job, "bundle_path", None))
            if result.bundle is not None:
                self.bundle_eval = BundleEvaluator(result.bundle, fps=job.fps)
                self.spectrum_synth = MusicalSpectrumSynth()
                if self.bundle_mode == "auto":
                    self.bundle_mode = "cued"
            elif self.bundle_mode == "auto":
                self.bundle_mode = "raw"
```

- [ ] **Step 3: Replace the per-frame texture write**

Find the existing block (around `render.py:967–971`):

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
                if self.bundle_eval is not None and self.spectrum_synth is not None:
                    eval_frame = self.bundle_eval.evaluate(frame_idx)
                    cued_aud = self.spectrum_synth.synthesize(eval_frame)
                    aud_data = _mix_audio_textures(
                        raw_aud, cued_aud, self.bundle_mode, self.bundle_blend,
                    )
                else:
                    eval_frame = None
                    aud_data = raw_aud
                if not hasattr(self, 'audio_tex_512'):
                    self.audio_tex_512 = self.ctx.texture((512, 2), 1, dtype='f4')
                self.audio_tex_512.write(aud_data.astype('f4').tobytes())
            else:
                eval_frame = None
```

- [ ] **Step 4: Bind the five built-in uniforms**

Just before the line `for k, v in self.job.shader_parameters.items():` (so user `shader_parameters` can still override), insert:

```python
        # Built-in cuesheet/bundle uniforms (Phase 1)
        uni.update(_builtin_uniforms_from_eval(eval_frame))
```

If `eval_frame` doesn't exist in that scope (because the `audio_mode` branch above didn't run), guard with:

```python
        uni.update(_builtin_uniforms_from_eval(locals().get("eval_frame")))
```

- [ ] **Step 5: Run the full test suite to catch regressions**

Run: `python -m pytest tests/ -x`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add cedartoy/render.py
git commit -m "feat(render): wire MusiCue bundle into init + per-frame texture/uniforms"
```

---

### Task 2.9: CLI flags + web UI

**Files:**
- Modify: `cedartoy/cli.py`
- Modify: `web/js/components/config-editor.js`

- [ ] **Step 1: Add argparse entries to `cedartoy/cli.py`**

Find the render subparser (where `--audio-path` and `--audio-mode` are defined) and add alongside them:

```python
    render_parser.add_argument(
        "--bundle", type=Path, default=None, dest="bundle_path",
        help="Path to a MusiCue bundle JSON (defaults to sibling of audio file)",
    )
    render_parser.add_argument(
        "--bundle-mode", choices=["auto", "raw", "cued", "blend"], default=None,
        dest="bundle_mode",
        help="auto=cued if bundle present; raw=ignore; cued=synthesized; blend=mix",
    )
    render_parser.add_argument(
        "--bundle-blend", type=float, default=None, dest="bundle_blend",
        help="Mix weight (0-1) for cued texture in blend mode",
    )
```

(If the parser variable isn't named `render_parser`, match what `--audio-path` uses.)

- [ ] **Step 2: Verify `--help` lists the new flags**

Run: `python -m cedartoy.cli render --help`
Expected output includes `--bundle`, `--bundle-mode`, `--bundle-blend`.

- [ ] **Step 3: Surface fields in `web/js/components/config-editor.js`**

Open `web/js/components/config-editor.js`. Search for `audio_path` and `audio_mode`. Wherever they're rendered, add equivalent renders for `bundle_path` (file picker / text field), `bundle_mode` (select with the four choices), and `bundle_blend` (slider 0–1, conditionally visible when `bundle_mode === "blend"`).

If `config-editor.js` already iterates over `OPTIONS` and renders unknown options with a generic renderer, no change is needed — Task 2.6 already added the three options to `OPTIONS`. Verify by running the UI:

```bash
python -m cedartoy.cli ui
```

Open `http://localhost:8080`. Confirm Bundle Path, Bundle Mode, and Bundle Blend appear in the audio section.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -x`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/cli.py web/js/components/config-editor.js
git commit -m "feat(cli+ui): expose --bundle/--bundle-mode/--bundle-blend flags and UI fields"
```

---

### Task 2.10: Docs + manual A/B visual smoke

**Files:**
- Modify: `docs/AUDIO_SYSTEM.md` (or create if absent)
- Modify: `README.md`

- [ ] **Step 1: Document the integration in `docs/AUDIO_SYSTEM.md`**

Append:

```markdown
## MusiCue Bundle Integration

CedarToy can read MusiCue's `song.musicue.json` bundle to drive shader
animation with structured musical cues instead of raw amplitude.

**Quick start:** Drop `song.musicue.json` next to `song.wav` (generated by
`musicue export-bundle <audio>`). CedarToy auto-discovers it and switches
`iChannel0` to a synthesized "musical spectrum" texture:

- Bins   0– 32: kick onsets (ADSR-decayed)
- Bins  32– 96: snare + tom
- Bins  96–256: hat + cymbal
- Bins 256–512: MIDI energy on melodic stems (vocals, other)

The waveform row (row 1 of the 2×512 texture) becomes a tempo-locked
heartbeat: `0.5 + 0.5 × iEnergy × sin(2π × iBeat)`.

**Built-in uniforms** — declare any of these in your shader to opt in:

```glsl
uniform float iBpm;            // current BPM
uniform float iBeat;           // 0..1 phase within current beat
uniform int   iBar;            // 0-indexed bar number
uniform float iSectionEnergy;  // 0..1 weight of current section
uniform float iEnergy;         // 0..1 short-window global energy
```

Shaders that don't declare them are unaffected.

**Modes** — set via `--bundle-mode` or the config UI:

- `auto` (default): cued when bundle present, raw otherwise
- `raw`:   ignore bundle, use raw FFT
- `cued`:  use synthesized texture
- `blend`: mix raw and cued by `bundle_blend` (0..1)

**A/B comparison** — render the same shader against the same song twice:

```bash
python -m cedartoy.cli render shaders/luminescence.glsl \
  --audio-path song.wav --bundle-mode raw  --output-dir renders/raw

python -m cedartoy.cli render shaders/luminescence.glsl \
  --audio-path song.wav --bundle-mode cued --output-dir renders/cued
```

Beats should land cleaner in the `cued` output; high-energy sections
should sustain rather than going silent between hits.
```

- [ ] **Step 2: Add a paragraph to `README.md`**

Append (in or near the audio reactivity section):

```markdown
### MusiCue Bundles

If you have a MusiCue bundle (`song.musicue.json`) next to your audio file,
CedarToy uses it automatically to synthesize a beat-locked `iChannel0`
texture and bind `iBpm`, `iBeat`, `iBar`, `iSectionEnergy`, `iEnergy`
uniforms. Generate one with `musicue export-bundle <audio>`. See
`docs/AUDIO_SYSTEM.md` for the full reference.
```

- [ ] **Step 3: Manual A/B smoke**

Generate a bundle for any test audio:

```bash
musicue export-bundle test_audio.wav
```

Then render the same shader twice:

```bash
python -m cedartoy.cli render shaders/<any>.glsl \
  --audio-path test_audio.wav --bundle-mode raw  --duration-sec 10 \
  --output-dir renders/smoke_raw

python -m cedartoy.cli render shaders/<any>.glsl \
  --audio-path test_audio.wav --bundle-mode cued --duration-sec 10 \
  --output-dir renders/smoke_cued
```

Eyeball the diff. If `cued` doesn't feel more musical than `raw`, surface
that finding (it's the validation gate for Phase 1).

- [ ] **Step 4: Commit**

```bash
git add docs/AUDIO_SYSTEM.md README.md
git commit -m "docs: MusiCue bundle integration usage + A/B smoke"
```

**End of Phase 2.** Feature is shipped.

---

## Self-review

**Spec coverage:**

| Spec section | Task |
|---|---|
| `MusiCueBundle` schema (Part 1) | 1.1 |
| `build_bundle()` sha check + sections | 1.2 |
| `build_bundle()` drums | 1.3 |
| `build_bundle()` midi + midi_energy | 1.4 |
| `build_bundle()` global_energy + cuesheet embed | 1.5 |
| `musicue export-bundle` CLI (Part 1) | 1.6 |
| Phase 1 fixture handoff | 1.7 |
| `cedartoy/musicue.py` schema mirror (Part 2) | 2.1 |
| `BundleEvaluator` bpm/beat/bar | 2.2 |
| `BundleEvaluator` section/global/drum/midi/stems | 2.3 |
| `MusicalSpectrumSynth` with MIDI driving high bins | 2.4 |
| Loader sibling discovery + sha | 2.5 |
| Config / RenderJob / options additions | 2.6 |
| `_mix_audio_textures` + `_builtin_uniforms_from_eval` | 2.7 |
| `Renderer.__init__` wiring + per-frame texture/uniforms | 2.8 |
| CLI flags + web UI | 2.9 |
| Docs + manual A/B smoke | 2.10 |
| Error matrix: schema gate | 2.1 |
| Error matrix: sha mismatch | 2.5 |
| Error matrix: no bundle present | 2.5 + 2.8 |
| Phase 1 non-goal: stems_energy empty | Documented in 1.2's bundle init + 2.3 lookup returning `{}` gracefully |
| Phase 1 non-goal: cuesheet-only fallback | Explicitly removed; discovery is `.musicue.json` only |

**Placeholder scan:** no TBDs or "implement later" markers. Every step has concrete code or a concrete command.

**Type consistency:**
- `MusiCueBundle.global_energy: StemEnergyCurve` in both MusiCue (Task 1.1) and CedarToy mirror (Task 2.1) ✓
- `EvalFrame.global_energy: float` (Task 2.2/2.3); not confused with the bundle's `global_energy: StemEnergyCurve` ✓
- `BundleEvaluator.evaluate(frame_index: int) -> EvalFrame` consistent across Tasks 2.2, 2.3, 2.7, 2.8 ✓
- `MusicalSpectrumSynth.synthesize(EvalFrame) -> np.ndarray (2, 512) float32` consistent across 2.4, 2.7, 2.8 ✓
- `bundle_mode` values `auto|raw|cued|blend` consistent across config (2.6), helpers (2.7), CLI (2.9), docs (2.10) ✓

**Spec deviations (intentional):**
- None of substance — the spec was followed faithfully.

---

## Plan complete

Plan saved to `docs/superpowers/plans/2026-05-13-musicue-bundle-cedartoy.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
