# MusiCue → CedarToy integration (Phase 1: retrofit)

**Date:** 2026-05-12
**Status:** Design approved, pending implementation plan
**Scope:** Phase 1 only. Phase 2 (rich music-aware authoring API) is out of scope for this spec.

## Summary

Drive CedarToy shader animation from MusiCue's structured `CueSheet` JSON instead of relying solely on raw audio amplitude. Phase 1 retrofits existing shaders without code changes by (a) replacing CedarToy's raw FFT/waveform `iChannel0` texture with a cue-driven "musical spectrum" texture, and (b) exposing five new built-in uniforms (`iBpm`, `iBeat`, `iBar`, `iSectionEnergy`, `iEnergy`) that shaders may opt-in to.

The intent is to validate the integration on real shaders before designing Phase 2's richer authoring surface. Phase 1 is the smallest change that makes existing shaders react *musically* (locked to beats, sections, drum onsets) rather than to raw amplitude.

## Goals

- Existing CedarToy shaders that sample `iChannel0` start hitting beats and section boundaries cleanly, with zero shader code edits.
- A small, conservative set of new built-in uniforms is available for 5-line shader edits that exercise structural cues (downbeats, bar counts, section energy).
- Friction is zero: drop `song.cuesheet.json` next to `song.wav` and render; sibling auto-discovery handles the rest.
- MusiCue is unchanged. Coupling is one-way and schema-version-aware.

## Non-goals (Phase 2 or later)

- Per-cuesheet-track auto-bound uniforms (`uniform float kick;` for arbitrary track names).
- A generic cue texture exposing every cuesheet track for shader sampling.
- `@cue` declaration comments mirroring `@param`.
- New shaders written specifically against a structural music API.
- A new MusiCue exporter target. Phase 1 reads MusiCue's native `cuesheet.json` directly.
- GPU-side spectrum synthesis (Phase 1 synthesizes on CPU at load time, matching CedarToy's existing `_precompute_textures` pattern).

## Key design decisions (and the alternatives considered)

| Decision | Chosen | Alternative considered | Why |
|---|---|---|---|
| Shader binding model | Hybrid: named built-in uniforms + (later) generic texture | A: named uniforms only; B: generic texture only | A maps cleanly to a small Phase 1 surface; B is reserved for Phase 2 expansion. |
| File format CedarToy reads | MusiCue's native `cuesheet.json` | New `cedartoy` exporter in MusiCue emitting baked curves | Native JSON preserves event metadata (ADSR, tags, drum class), allows re-evaluation at any FPS without re-baking, avoids a two-step workflow. |
| Creative use case priority | Retrofit existing shaders first, expand API later | Author new music-aware shaders from day one | Retrofit-first validates pipeline on real material; failures (timing, decay shape, "energy" semantics) inform Phase 2's API. |
| Retrofit mechanism | Synthesize a "musical `iChannel0`" replacing raw FFT | Auto-drive existing `@param` uniforms by name match | Texture upgrade is one well-defined transformation that benefits every shader uniformly. Name-match heuristics fight author intent. |
| Cuesheet location | Sibling auto-discovery + explicit `--cuesheet` override | Sibling only; or explicit only | Drop-in works for the common case; override unblocks testing and remixing. |
| Time alignment | Cuesheet time = audio time = render time, all shifted uniformly by any audio offset | Independent offset for cuesheet | Decoupled time is a footgun without a use case. |
| Phase 1 uniform surface | Five built-ins (`iBpm`, `iBeat`, `iBar`, `iSectionEnergy`, `iEnergy`) | `iChannel0` upgrade only; or full hybrid surface | Marginal cost (~20 LOC); unlocks 5-line shader edits that prove Phase 2's direction. |
| Schema mirroring | CedarToy mirrors MusiCue's CueSheet pydantic models locally | Extract a shared `musicue-schema` package | Schema is small (~7 model classes), MusiCue is the only known source, CedarToy is the only known consumer. Promote to a package if/when a third consumer appears. |

## Architecture

One new module — `cedartoy/cuesheet.py` — sits beside `audio.py` and hooks into `render.py` at the same initialization point that loads audio. MusiCue is untouched.

```
   audio.wav  ──►  AudioProcessor (raw FFT/waveform)
                          │
   song.cuesheet.json ─►  CueSheetEvaluator
                          │
                          ├──► MusicalSpectrumSynth ──► 2x512 texture
                          │                              │
                          │   (audio_mode: raw|cued|blend chooses
                          │    raw FFT, synth, or weighted mix)
                          │                              │
                          ├──► BuiltInsBinder           │
                          │      iBpm/iBeat/iBar/...    ▼
                          ▼                          iChannel0
                    render.py per-frame uniforms ──► shader
```

## Components

### `cedartoy/cuesheet.py` — schema mirrors

Pydantic models mirroring MusiCue's `CueSheet`, `CueTrack`, `BeatEvent`, `SectionEvent`, `OnsetEvent`, `TempoInfo`, `Patterns`, `ADSREnvelope`. Approximately 30 lines. Includes a `schema_version` major-version gate that hard-fails on unsupported major versions.

### `CueSheetEvaluator`

Loads a CueSheet, exposes `evaluate(frame_index: int) -> EvalFrame`. `EvalFrame` fields:

- `beat_phase: float` — 0.0–1.0 within the current beat, derived from the beat list and tempo curve.
- `bar: int` — current bar number (0-indexed), derived from beats with `is_downbeat`.
- `bpm: float` — current BPM from `tempo.bpm_curve` (interpolated) or `tempo.bpm_global` fallback.
- `section_energy: float` — 0.0–1.0 weight of the current section, precomputed at load from per-section LUFS and spectral flux.
- `global_energy: float` — 0.0–1.0 short-window global energy curve, interpolated.
- `drum_pulses: dict[str, float]` — per-drum-class ADSR-decayed envelope value, keyed by `drum_class` (`kick`, `snare`, `clap`, `hat`, `cymbal`, ...).
- `midi_energy: dict[str, float]` — smoothed per-stem MIDI energy (`vocals`, `bass`, `other`).

Internals:
- Impulse onsets decay with ADSR pulled from the event's `envelope` field when MusiCue's grammar emits one, otherwise the conservative default `A=0.005, D=0.08, S=0, R=0` (fast attack, eighth-note decay at typical tempos). Multiple overlapping impulses sum additively, clamped to `[0, 1]`.
- Continuous tracks (`hop_sec` grid) are linearly interpolated between samples.
- Section lookup uses binary search by frame time.
- Beat/bar lookup uses binary search; `beat_phase` is `(t - beats[i].t) / (beats[i+1].t - beats[i].t)`.

### `MusicalSpectrumSynth`

Takes an `EvalFrame` per frame, returns a `(2, 512)` float32 numpy array drop-in replacing CedarToy's current FFT/waveform texture. Shape and value range are identical to what `AudioProcessor._compute_shadertoy_texture` returns, so existing shaders work unchanged.

**Row 0 — synthesized spectrum (replaces FFT row):**

| Bin range | Driven by |
|---|---|
| `0–32` (sub/low) | `drum_pulses["kick"]` |
| `32–96` (low-mid) | `drum_pulses["snare"] + drum_pulses["clap"]` |
| `96–256` (mid-high) | `drum_pulses["hat"] + drum_pulses["cymbal"]` |
| `256–512` (high) | `midi_energy["vocals"] + midi_energy["other"]`, smoothed |

Each bin range is filled with a Hann-window envelope across the range (not flat) so shaders integrating across narrow bin windows see a natural curve. Section energy adds a baseline tilt of `+0.1 × section_energy` so high-energy sections sustain rather than going silent between hits. Final values clamped to `[0, 1]`.

**Row 1 — synthesized "waveform" (replaces waveform row):**

A `[0, 1]` ribbon (matching the raw row's `(sample × 0.5) + 0.5` encoding) computed as `0.5 + 0.5 × global_energy × sin(2π × beat_phase)`. Shaders sampling Row 1 for waveform displacement see a tempo-locked heartbeat; zero-crossings land on beats.

### `BuiltInsBinder`

Given an `EvalFrame`, returns the five Phase 1 built-in uniforms. `render.py` binds them per frame; shaders not declaring them are unaffected (moderngl tolerates unbound uniforms).

| Uniform | GLSL type | Semantics | Default when no cuesheet |
|---|---|---|---|
| `iBpm` | `float` | Current BPM from tempo curve | `0.0` |
| `iBeat` | `float` | Phase within current beat, 0.0–1.0 | `0.0` |
| `iBar` | `int` | Current bar number (0-indexed) | `0` |
| `iSectionEnergy` | `float` | Energy weight of current section, 0.0–1.0 | `0.0` |
| `iEnergy` | `float` | Short-window global energy, 0.0–1.0 | `0.0` |

These five names are committed for Phase 2 stability.

### `render.py` patch points

- **Init**: After `AudioProcessor` loads, look for sibling cuesheet (or honor `cuesheet_path` override). Instantiate `CueSheetEvaluator`. Validate `source_sha256` against the audio file's sha; WARN on mismatch but proceed.
- **Texture source selection**: Based on `audio_mode` (`raw`/`cued`/`blend`), choose between `AudioProcessor`'s raw texture, `MusicalSpectrumSynth`'s synthesized texture, or a weighted mix `raw × (1-b) + cued × b` per `cued_blend`.
- **Per-frame uniform binding**: Bind the five built-ins from `BuiltInsBinder.bind(eval_frame)`.

## Configuration surface

New fields on the render job (`config_model.py`):

- `cuesheet_path: Path | None` — explicit override. `None` triggers sibling auto-discovery: `<audio_stem>.cuesheet.json` in the same directory as `audio_path`.
- `audio_mode: Literal["raw", "cued", "blend"]` — defaults to `"cued"` when a valid cuesheet is loaded, else `"raw"`.
- `cued_blend: float` — 0.0–1.0, used in `"blend"` mode only. Defaults to `0.5`.

**Web UI** — one row added to the Audio panel:

- **Cuesheet status line** — one of: `✓ song.cuesheet.json (sha matches)`, `⚠ song.cuesheet.json (sha mismatch — using anyway)`, `— none detected`. `[browse]` and `[clear]` controls.
- **Texture mode dropdown** — `Raw FFT` / `Musical (cued)` / `Blend` (the last with a blend slider).

**CLI** — `--cuesheet PATH` and `--audio-mode {raw,cued,blend}` flags mirror the job fields. `--cued-blend FLOAT` for blend mode.

## Error handling

| Condition | Behavior |
|---|---|
| No cuesheet found (no sibling, no flag) | Silent fallback to `audio_mode="raw"`, INFO log. Render proceeds. |
| Cuesheet present but `source_sha256` ≠ audio file sha | WARN log; proceed with cuesheet. UI shows ⚠ chip. (User's choice — they may be intentionally reusing cues across remasters.) |
| Cuesheet `schema_version` major doesn't match CedarToy's supported major | Hard fail at job init: `"Cuesheet schema X.Y not supported; expected major N. Re-export with current MusiCue."` |
| Malformed JSON / pydantic validation error | Hard fail at job init with the pydantic error surfaced verbatim. |
| Cuesheet valid but `tracks` empty and no tempo | Fall back to `"raw"` with WARN; don't synthesize from nothing. |
| `iBeat`/`iBar`/etc. requested but no cuesheet | Uniforms bind to defaults from the table above; no failure. |
| Audio file missing but cuesheet present | Existing CedarToy behavior (FileNotFoundError) is unchanged. |

## Testing

**Unit — `tests/test_cuesheet_evaluator.py`**

- Synthetic CueSheet with a single kick impulse at `t=1.0` (default ADSR) → assert `evaluate(frame_at(1.0)).drum_pulses["kick"] ≈ 1.0` and `evaluate(frame_at(1.5))` decays to near zero.
- Continuous track at `hop_sec=0.04` with known values → assert linear interpolation between grid samples.
- Section boundary lookup at exact and near-boundary frames returns the correct section.
- Beat phase: synthetic beats at `t=0.0, 0.5, 1.0` → `evaluate(frame_at(0.25)).beat_phase ≈ 0.5`.

**Unit — `tests/test_spectrum_synth.py`**

- `EvalFrame` with `drum_pulses["kick"]=1.0`, all else zero → Row 0 bins `0–32` peak around `1.0`, bins `96–256` near zero.
- `EvalFrame` with all zeros and `section_energy=0.8` → assert baseline tilt is present and ≈ `0.08`.
- Row 1 waveform with `global_energy=1.0, beat_phase=0.25` → assert value ≈ `1.0` (matches `0.5 + 0.5 × sin(π/2)`).

**Unit — `tests/test_render_integration.py`**

- Mocked tiny CueSheet (2 bars, 4 kicks, 1 section) + 1 second of silent audio. Render 24 frames in `cued` mode. Inspect bound uniforms each frame; assert `iBeat` cycles correctly given the synthetic tempo and `iBar` increments at the expected frame.

**Schema gate — `tests/test_schema_gate.py`**

- Hand-crafted cuesheet with `schema_version: "2.0"` → assert clean error (`ValueError` or specific custom exception), not crash. Error message includes the expected major.

**Sha-mismatch — `tests/test_sha_mismatch.py`**

- Cuesheet with wrong `source_sha256` → assert WARN is logged via `caplog` and render still completes a frame successfully.

**Visual smoke (manual, documented in `docs/AUDIO_SYSTEM.md`)**

- Render `shaders/luminescence.glsl` against the same song with `audio_mode=raw` then `audio_mode=cued`. Eyeball that pulses in `cued` mode land on beats and sustain in high-energy sections. Document the comparison in the audio docs.

## Open questions for implementation planning

- Should `cued_blend` be exposed as a `@param`-style live slider during interactive renders, or stay job-config-only? Suggest job-config-only for Phase 1; revisit if useful.
- The `section_energy` mapping from LUFS + spectral flux to a `[0, 1]` weight needs a concrete formula. Suggest: rank sections by `lufs_integrated + α × spectral_flux_rise`, normalize to `[0, 1]`, with α tuned on a few real cuesheets during implementation.
- What does `iBar` do when the cuesheet has no beats with `is_downbeat`? Suggest: derive from time signature + first beat, fall back to `0`.

These are noted for the implementation plan, not blocking the design.
