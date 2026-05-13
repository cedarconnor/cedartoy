# MusiCue Bundle → CedarToy Integration Design

**Date:** 2026-05-13
**Status:** Approved — ready for implementation planning
**Supersedes:** `2026-05-12-musicue-cedartoy-integration-design.md` (the cuesheet-only design — abandoned because `CueSheet` lacks the top-level `beats`/`sections`/`tempo`/`onsets` fields the design assumed)

---

## Goal

Drive CedarToy shaders from MusiCue's musical analysis instead of raw FFT amplitude. CedarToy synthesizes `iChannel0` from per-drum impulses and MIDI-density curves, and exposes five new built-in uniforms (`iBpm`, `iBeat`, `iBar`, `iSectionEnergy`, `iEnergy`). Shaders that don't declare those uniforms are unaffected — this is a strict superset of today's behavior.

## Architecture overview

```
D:\MusiCue\                                  D:\cedartoy\
┌──────────────────────────┐                 ┌─────────────────────────────┐
│ AnalysisResult (1.3)     │                 │ render.py                   │
│ CueSheet      (1.2)      │                 │  ├── iChannel0 texture      │
│         │                │                 │  └── 5 musical uniforms     │
│  build_bundle()          │                 │            ▲                │
│         ▼                │  song.musicue.  │            │                │
│ MusiCueBundle (1.0)──────┼──── json ──────▶│   cedartoy/musicue.py       │
│         ▲                │                 │     ├── MusiCueBundle mirror│
│ export-bundle CLI        │                 │     ├── BundleEvaluator     │
└──────────────────────────┘                 │     ├── MusicalSpectrumSynth│
                                             │     └── loader              │
                                             └─────────────────────────────┘
```

**Contract location:** `MusiCueBundle` schema in `D:\MusiCue\musicue\schemas.py`. MusiCue owns versioning; CedarToy mirrors a subset for type-safe deserialization. Other future consumers (lighting controllers, DAW plugins) mirror their own subsets.

**Cuesheet sidecar continues to be emitted unchanged.** The bundle is additive — never replaces `song.cuesheet.json`. MusiCue's existing users see no change.

---

## Part 1: MusiCue side

### `MusiCueBundle` schema (`musicue/schemas.py`)

```python
class SectionBundleEntry(BaseModel):
    start: float
    end: float
    label: str
    confidence: float
    lufs: float | None = None
    energy_rank: float                       # [0,1] precomputed rank across sections
    spectral_flux_rise: float | None = None

class DrumOnset(BaseModel):
    t: float
    strength: float
    confidence: float | None = None

class MidiNoteBundle(BaseModel):
    t: float
    duration: float
    pitch: int                               # MIDI 0–127
    velocity: int                            # MIDI 0–127

class StemEnergyCurve(BaseModel):
    hop_sec: float
    values: list[float]                      # normalized to [0,1] in MusiCue

class MusiCueBundle(BaseModel):
    schema_version: str = "1.0"
    source_sha256: str
    duration_sec: float
    fps: float = 24.0

    tempo: TempoInfo                         # existing type, reused
    beats: list[BeatEvent]                   # existing type, reused

    sections: list[SectionBundleEntry]

    drums: dict[str, list[DrumOnset]]        # keys: kick/snare/hat/tom/cymbal/other
    midi: dict[str, list[MidiNoteBundle]]    # keys: stem names (vocals/other/bass)
    midi_energy: dict[str, StemEnergyCurve]  # per-stem MIDI activity envelope

    stems_energy: dict[str, StemEnergyCurve] = Field(default_factory=dict)
                                             # per-stem audio energy; empty in Phase 1
                                             # (MusiCue follow-up adds per-stem LUFS curves)
    global_energy: StemEnergyCurve           # overall energy from curves.lufs, normalized

    cuesheet: CueSheet                       # existing type, embedded verbatim
```

**Schema versioning:** independent of `CueSheet` (1.2) and `AnalysisResult` (1.3). Starts at `"1.0"`. Major-version bumps when consumers must update; minor for additive fields.

**Why `stems_energy` is optional with empty default:** per-stem LUFS curves don't exist yet in `analysis.curves`. Phase 1 ships with `stems_energy={}`. A MusiCue follow-up adds per-stem LUFS computation during analysis; the bundle picks them up automatically when present. CedarToy treats missing stems as zero-energy — shaders that read `iVocalEnergy` etc. (Phase 2) see zeros gracefully.

### `build_bundle()` (`musicue/compile/bundle.py`)

```python
def build_bundle(
    analysis: AnalysisResult,
    cuesheet: CueSheet,
) -> MusiCueBundle:
```

Steps:

1. **Sha cross-check.** `analysis.source.sha256 == cuesheet.source_sha256`, else `ValueError("analysis and cuesheet are not from the same source")`.
2. **Sections.** For each `analysis.sections[i]`:
   - `lufs`: compute from `analysis.curves["lufs"]` windowed to `[start, end]` if a global LUFS curve exists; else `None`.
   - `spectral_flux_rise`: pull from the matching `analysis.section_transitions` entry by `t` proximity; else `None`.
   - `energy_rank`: computed in a second pass after all sections built — rank by `0.5·spectral_flux_rise_normalized + 0.5·lufs_normalized` (using whichever component is available), normalize to `[0,1]` by `(rank − min) / (max − min)`. Single section → `0.5`. All-zero rankings → `0.5` uniform.
3. **Drums.** Regroup `analysis.onsets.get("drums", [])` by `drum_class` field. Onsets with `drum_class is None` are dropped. Result keyed by `"kick"`, `"snare"`, `"hat"`, `"tom"`, `"cymbal"`, `"other"` (matching `DRUM_CLASSES` in `drum_classifier.py`).
4. **MIDI.** Pass through `analysis.midi` keys as-is. Each `MidiNote` → `MidiNoteBundle` (drops `frame`/`timecode` which are derived).
5. **midi_energy.** For each stem in `analysis.midi`, derive an activity curve at `hop_sec = analysis.analysis_config.curve_hop_sec` (default 0.04). Per bin: `sum(velocity/127 × max(0, min(bin_end, note.t + note.duration) − max(bin_start, note.t)) / hop_sec)` over notes touching the bin. Clip to `[0, 1]`.
6. **stems_energy.** Empty `{}` in Phase 1 (see follow-up note above).
7. **global_energy.** Normalize `analysis.curves["lufs"]` to `[0, 1]` by `(v − min) / (max − min)`; if the curve is missing or constant, all zeros.
8. **Embed cuesheet** verbatim.

### CLI: `musicue export-bundle`

```
musicue export-bundle <audio_path>
  [--analysis PATH]    # default: auto-discover via MusiCue's cache (by audio sha)
  [--cuesheet PATH]    # default: auto-discover sibling <audio_stem>.cuesheet.json
  [--grammar NAME]     # if no cuesheet present, compile one with this grammar (default: concert_visuals)
  [--output PATH]      # default: <audio_stem>.musicue.json (sibling of audio)
  [--force]            # overwrite existing
```

Input discovery (auto-run if missing, unless `--no-analyze` flag added later as a polish):
- Analysis: `--analysis` arg → MusiCue cache lookup by audio sha → run `analyze` pipeline
- Cuesheet: `--cuesheet` arg → sibling discovery → run `compile` with `--grammar`

Output: `<audio_stem>.musicue.json` next to the audio file.

### MusiCue tests

- `tests/test_bundle_schema.py` — pydantic round-trip; default `schema_version="1.0"`; `stems_energy` defaults to `{}`
- `tests/test_bundle_builder.py` — synthetic `AnalysisResult` + `CueSheet` fixtures; assertions on:
  - sha cross-check raises on mismatch
  - sections regrouped with `energy_rank` in `[0,1]`, monotone with input ranking
  - drums regrouped by `drum_class`; `drum_class is None` dropped
  - midi notes pass through; `midi_energy` curves have correct length (`int(duration_sec / hop_sec)`) and `[0,1]` range
  - missing `analysis.curves["lufs"]` → `global_energy` all zeros
- `tests/test_bundle_cli.py` — invoke the command end-to-end against a fixture audio; verify file written; verify round-trip back through `MusiCueBundle.model_validate`

---

## Part 2: CedarToy side

### Module layout

| Path | Role |
|---|---|
| `cedartoy/musicue.py` | NEW — bundle mirror, `BundleEvaluator`, `MusicalSpectrumSynth`, loader |
| `cedartoy/config_model.py` | MODIFY — add `bundle_path`, `bundle_mode`, `bundle_blend` |
| `cedartoy/options_schema.py` | MODIFY — three new `Option` entries |
| `cedartoy/types.py` | MODIFY — three new `RenderJob` fields (appended at end of dataclass) |
| `cedartoy/render.py` | MODIFY — wire bundle load + texture mix + uniform binding |
| `cedartoy/cli.py` | MODIFY — `--bundle`, `--bundle-mode`, `--bundle-blend` flags |
| `web/js/components/config-editor.js` | MODIFY — surface new fields in audio section |
| `tests/test_musicue_*.py` | NEW — schema, evaluator, synth, loader, integration |
| `docs/AUDIO_SYSTEM.md`, `README.md` | MODIFY — document the integration |

### `cedartoy/musicue.py` public surface

```python
SUPPORTED_SCHEMA_MAJOR = 1
class UnsupportedSchemaError(ValueError): ...

class MusiCueBundle(BaseModel): ...          # lean mirror — only fields CedarToy uses
                                             # (does NOT mirror embedded cuesheet — bundle.cuesheet kept as raw dict)
class EvalFrame:                             # dataclass
    bpm: float = 0.0
    beat_phase: float = 0.0
    bar: int = 0
    section_energy: float = 0.0
    global_energy: float = 0.0
    drum_pulses: dict[str, float] = {}       # kick/snare/hat/tom/cymbal
    midi_energy: dict[str, float] = {}       # vocals/other/bass (Phase 1)
    stems_energy: dict[str, float] = {}      # empty in Phase 1

class BundleEvaluator:
    def __init__(self, bundle: MusiCueBundle, fps: float): ...
    def evaluate(self, frame_index: int) -> EvalFrame: ...

class MusicalSpectrumSynth:
    def synthesize(self, eval_frame: EvalFrame) -> np.ndarray:  # (2, 512) float32

@dataclass
class BundleLoadResult:
    bundle: MusiCueBundle | None = None
    path: Path | None = None
    sha_match: bool = False

def discover_bundle_path(audio_path: Path) -> Path | None
def compute_audio_sha256(audio_path: Path) -> str    # hashlib.sha256 of file bytes
def load_for_audio(audio_path: Path, override_path: Path | None = None) -> BundleLoadResult
```

### `BundleEvaluator` behavior

- **`bpm`**: from `bundle.tempo.bpm_curve` interpolated at `t`, else `bundle.tempo.bpm_global`.
- **`beat_phase`**: bisect `bundle.beats` by `t`; return `(t − beats[i].t) / (beats[i+1].t − beats[i].t)`. Out-of-range or `<2` beats → `0.0`.
- **`bar`**: last `BeatEvent` with `is_downbeat=True` at or before `t` → its `bar`. If no downbeats present, fall back to `int(t × bpm / 60 / time_signature[0])`.
- **`section_energy`**: `bundle.sections[i].energy_rank` where `sections[i].start ≤ t < sections[i].end`; else `0.0`.
- **`global_energy`**: linear-interpolate `bundle.global_energy.values` at `t / hop_sec`.
- **`drum_pulses`**: per drum class, sum ADSR contributions from each `DrumOnset` at or before `t`. Default ADSR `(a=0.005, d=0.08, s=0.0, r=0.0)` — bundle doesn't carry per-onset envelope (the embedded cuesheet does; Phase 1 keeps the evaluator on top-level `bundle.drums` for simplicity). Clamped `[0,1]` per class.
- **`midi_energy`**: per stem, linear-interpolate `bundle.midi_energy[stem].values` at `t / hop_sec`.
- **`stems_energy`**: same as `midi_energy` but against `bundle.stems_energy`. Empty in Phase 1.

All event lookups precomputed/sorted at `__init__` time; per-frame cost is bisect + a few dict lookups.

### `MusicalSpectrumSynth.synthesize(eval_frame)` → `(2, 512)` float32

```
Row 0 — frequency-shaped texture:
  Bins   0– 32 : drum_pulses["kick"]                         × Hann(32)
  Bins  32– 96 : drum_pulses["snare"] + drum_pulses["tom"]   × Hann(64)
  Bins  96–256 : drum_pulses["hat"]  + drum_pulses["cymbal"] × Hann(160)
  Bins 256–512 : midi_energy["vocals"] + midi_energy["other"] × Hann(256)
  Row 0 += 0.1 × section_energy        # baseline tilt
  Row 0 = clip(row 0, 0, 1)

Row 1 — tempo-locked heartbeat:
  All bins = clip(0.5 + 0.5 × global_energy × sin(2π × beat_phase), 0, 1)
```

Shape and dtype match the existing `AudioProcessor._compute_shadertoy_texture` output so the texture-write site in `render.py` doesn't change beyond swapping the source ndarray.

### Loader behavior

`load_for_audio(audio_path, override_path)`:
1. Target = `override_path` if given, else `discover_bundle_path(audio_path)` (sibling `<audio_stem>.musicue.json`).
2. If `target` is `None`: `INFO` log "no bundle found"; return `BundleLoadResult()` with all defaults.
3. Load JSON, validate against `MusiCueBundle`, version-gate on major (raise `UnsupportedSchemaError` on mismatch).
4. Compute `compute_audio_sha256(audio_path)`; compare to `bundle.source_sha256`. Mismatch → `WARNING` log; `sha_match=False`; use anyway.
5. Return populated `BundleLoadResult`.

### Render integration (`cedartoy/render.py`)

**At `Renderer.__init__`** (after `AudioProcessor` construction):

```python
self.bundle_eval = None
self.spectrum_synth = None
self.bundle_mode = getattr(job, "bundle_mode", "auto")
self.bundle_blend = getattr(job, "bundle_blend", 0.5)

if self.audio and self.bundle_mode != "raw" and job.audio_path is not None:
    result = load_for_audio(job.audio_path, override_path=getattr(job, "bundle_path", None))
    if result.bundle is not None:
        self.bundle_eval = BundleEvaluator(result.bundle, fps=job.fps)
        self.spectrum_synth = MusicalSpectrumSynth()
        if self.bundle_mode == "auto":
            self.bundle_mode = "cued"
    elif self.bundle_mode == "auto":
        self.bundle_mode = "raw"
```

**At the per-frame texture-write site** (currently around `render.py:967–971`):

```python
if self.job.audio_mode in ("shadertoy", "both"):
    raw_aud = self.audio.get_shadertoy_texture(frame_idx)
    if self.bundle_eval is not None and self.spectrum_synth is not None:
        eval_frame = self.bundle_eval.evaluate(frame_idx)
        cued_aud = self.spectrum_synth.synthesize(eval_frame)
        aud_data = _mix_audio_textures(raw_aud, cued_aud, self.bundle_mode, self.bundle_blend)
    else:
        aud_data = raw_aud
        eval_frame = None
    # ... existing audio_tex_512.write ...

    uni.update(_builtin_uniforms_from_eval(eval_frame))
```

Helpers (top of `render.py`):

```python
def _mix_audio_textures(raw, cued, mode, blend) -> np.ndarray:
    if mode == "raw":   return raw
    if mode == "cued":  return cued
    if mode == "blend":
        b = max(0.0, min(1.0, float(blend)))
        return (raw * (1.0 - b) + cued * b).astype(np.float32)
    return cued  # auto resolved upstream

def _builtin_uniforms_from_eval(eval_frame) -> dict:
    if eval_frame is None:
        return {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0, "iSectionEnergy": 0.0, "iEnergy": 0.0}
    return {
        "iBpm": float(eval_frame.bpm),
        "iBeat": float(eval_frame.beat_phase),
        "iBar": int(eval_frame.bar),
        "iSectionEnergy": float(eval_frame.section_energy),
        "iEnergy": float(eval_frame.global_energy),
    }
```

### Configuration / RenderJob / CLI

**`config_model.py`** — add three fields after `audio_mode`:

```python
BundleMode = Literal["auto", "raw", "cued", "blend"]

class CedarToyConfig(BaseModel):
    ...
    bundle_path: Optional[Path] = None
    bundle_mode: BundleMode = "auto"
    bundle_blend: float = 0.5
    ...

    @field_validator("bundle_blend")
    @classmethod
    def bundle_blend_in_unit_range(cls, v):
        if v < 0 or v > 1:
            raise ValueError("bundle_blend must be between 0 and 1")
        return v
```

(`field_validator` is already imported in `config_model.py` — verified during design.)

**`options_schema.py`** — append after the existing `audio_mode` option:

```python
OPTIONS.append(Option("bundle_path", "Bundle Path", "path", None,
    help_text="MusiCue bundle JSON (defaults to sibling of audio_path)."))
OPTIONS.append(Option("bundle_mode", "Bundle Mode", "choice", "auto",
    choices=["auto", "raw", "cued", "blend"],
    help_text="auto=cued when bundle present; raw=ignore bundle; cued=synthesized; blend=mix"))
OPTIONS.append(Option("bundle_blend", "Bundle Blend (0–1)", "float", 0.5,
    help_text="Mix weight for cued texture when bundle_mode='blend'"))
```

**`types.py`** — append to the end of `RenderJob` (after `shader_parameters` field, since defaults must trail non-defaulted fields):

```python
    # MusiCue bundle integration
    bundle_path: Optional[Path] = None
    bundle_mode: str = "auto"
    bundle_blend: float = 0.5
```

**`cli.py`** — add to the render subcommand alongside `--audio-path` / `--audio-mode`:

```python
render_parser.add_argument("--bundle", type=Path, default=None, dest="bundle_path",
    help="Path to a MusiCue bundle JSON (defaults to sibling of audio file)")
render_parser.add_argument("--bundle-mode", choices=["auto","raw","cued","blend"], default=None,
    dest="bundle_mode")
render_parser.add_argument("--bundle-blend", type=float, default=None, dest="bundle_blend")
```

**`web/js/components/config-editor.js`** — surface `bundle_path` (file picker), `bundle_mode` (select), `bundle_blend` (slider, visible when mode = `blend`) in the audio section. Path verified to exist: `web/js/components/config-editor.js`.

### CedarToy tests

| Test file | Coverage |
|---|---|
| `tests/test_musicue_schema.py` | Mirror loads minimal payload; major-version gate; higher minor accepted; malformed JSON → `ValueError` |
| `tests/test_musicue_evaluator.py` | Drum impulse peak/decay; beat phase between two beats; bar at downbeats + bpm fallback; section_energy lookup; global_energy interpolation; empty bundle returns zeros |
| `tests/test_musicue_synth.py` | `(2, 512)` float32 shape; kick→low bins; hat→mid-high bins; **midi→high bins** (the gap the previous design had); section_energy baseline tilt; clamp invariants |
| `tests/test_musicue_loader.py` | Sibling discovery; sha match; sha mismatch logs WARNING; explicit override beats sibling; missing bundle returns empty result |
| `tests/test_musicue_integration.py` | `_mix_audio_textures` raw/cued/blend modes; `_builtin_uniforms_from_eval` with frame + None; auto→cued resolution when bundle present, auto→raw when absent |

OpenGL render-loop test stays out of scope (no GL in CI). Covered by the manual A/B visual smoke at the end.

---

## Error handling matrix

| Situation | Behavior |
|---|---|
| No `song.musicue.json` next to audio | `INFO` log "no bundle"; render raw FFT; uniforms bound to defaults |
| Bundle is malformed JSON | `ValueError` (fail-fast) |
| Bundle `schema_version` major ≠ 1 | `UnsupportedSchemaError` "re-export with current MusiCue" (fail-fast) |
| Bundle `source_sha256` ≠ audio sha | `WARNING` log; load anyway |
| `bundle_mode="cued"` but no bundle loaded | `WARNING`; fall back to raw FFT (don't crash) |
| `bundle_mode="raw"` | Skip bundle load entirely |
| `audio_path is None` | Skip bundle load; uniforms = defaults |

`bundle_mode="auto"` resolution is performed once at init: becomes `"cued"` if a bundle loaded, else `"raw"`. Observable in logs.

## File lifecycle

```
song.wav                  ← user's audio
song.cuesheet.json        ← existing MusiCue artifact, unchanged
song.musicue.json         ← NEW additive bundle (what CedarToy reads)
```

Workflow:

```
musicue analyze song.wav         # existing — produces cached AnalysisResult
musicue compile song.wav         # existing — produces song.cuesheet.json
musicue export-bundle song.wav   # NEW — composes both into song.musicue.json
```

`export-bundle` auto-runs the prerequisites if their outputs are missing.

CedarToy discovery: only `song.musicue.json`. If absent, no bundle features. (No cuesheet-only degraded mode in Phase 1 — explicit non-goal.)

---

## Phase 1 non-goals (deferred)

- **Per-stem audio-energy curves** (`stems_energy` populated). MusiCue follow-up adds per-stem LUFS during analysis; the bundle picks them up automatically when present.
- **`iVocalEnergy`/`iBassEnergy`/`iDrumsEnergy` uniforms.** Land when `stems_energy` populates; binding shaders to zeros now would be misleading.
- **Per-pitch MIDI binning.** Raw notes are in the bundle but only aggregate `midi_energy` curves drive iChannel0 today.
- **CueSheet-only degraded mode.** Users with `.cuesheet.json` but no `.musicue.json` run `musicue export-bundle` to upgrade.
- **Per-onset ADSR from the embedded cuesheet.** `BundleEvaluator` uses default ADSR; pulling per-event envelopes from `bundle.cuesheet.tracks` is a polish pass.

---

## Built-in uniforms (Phase 1)

```glsl
uniform float iBpm;            // current BPM
uniform float iBeat;           // [0,1] phase within current beat
uniform int   iBar;            // 0-indexed bar number
uniform float iSectionEnergy;  // [0,1] rank of current section
uniform float iEnergy;         // [0,1] global energy at this moment
```

Shaders that don't declare these uniforms are unaffected.
