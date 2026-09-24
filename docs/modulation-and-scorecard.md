# Modulation matrix & reactivity scorecard (design, step 3)

Goal: make any shader musical without an LLM rewriting its code. The shader only
exposes knobs (`@param`); CedarToy routes musical signals into those knobs with
tempo-aware shaping, and a scorecard measures whether the result actually follows
the music.

## 1. Modulation matrix

### Route
```json
{
  "id": "r1",
  "target": "warp_amount",          // an @param name (float only)
  "source": "iKick",                // any MOD_SOURCES key
  "depth": 0.6,                     // param units; may be negative
  "curve": "linear",                // linear | ease_in | ease_out | smoothstep | pow2 | sqrt
  "attack_beats": 0.0,              // follower attack, in beats (0 = instant)
  "release_beats": 0.5,             // follower release, in beats (0 = instant)
  "mode": "add",                    // add | integrate
  "enabled": true
}
```
- `MOD_SOURCES`: every scalar bundle uniform (`iEnergy`, `iEnergyFast`,
  `iSectionEnergy`, `iBuild`, `iKick`, `iSnare`, `iHat`, `iBass`, `iVocals`,
  `iDrums`, `iOther`, `iBrightness`, `iBarPhase`, `iPhrasePhase`,
  `iSectionProgress`, `iBeat`) plus derived `beat_pulse` (1 at each beat,
  exponential release) and `downbeat_pulse`. Values are 0..1 and use the
  post-mute/calibration values, so track mutes apply to routes too.
- Shaping order: source value → envelope follower (asymmetric one-pole whose
  time constants are attack/release × local beat period, run on a dense grid,
  offline) → curve → × depth.
- `add`: `param = base + Σ depth·shaped`, clamped to the @param min/max.
- `integrate`: contributes `depth · ∫ shaped dt` (seconds). For params that are
  phases/offsets (rotation angle, scroll offset): speed follows the music with no
  jitter. Not clamped (it's a phase); document it.
- `base` = the param's current UI slider value (`shader_parameters`).

### Defaults in shader source (`@mod`)
Shaders may declare default routes next to their params:
```glsl
// @param warp_amount float 0.2 0.0 1.0 "Warp"
// @mod warp_amount <- iKick depth=0.5 release=0.5 curve=ease_out
// @mod swirl_phase <- iEnergy depth=1.5 mode=integrate
```
User-edited routes (stored in the render config as `modulation_routes`,
list of Route) replace the shader's `@mod` defaults whenever the list is
present, even if it's empty. A missing key means "use the `@mod` defaults".

### Evaluation & parity
- `cedartoy/modulation.py` is the single canonical evaluator (pure Python, numpy).
  It builds per-route tables on a dense grid (≥ 200 Hz or 4× fps, whichever
  is higher) once, and `evaluate_at(t)` interpolates. The render evaluates at each
  temporal sample's time (same as the other bundle uniforms, incl. av_offset_ms).
- The preview gets per-frame modulated values for each param from an API
  endpoint (Python computes, JS only binds), same as the Validate timeline.
  A parity test pins it.

### UI
Stage 2 gets a "Modulation" section under the shader parameters: one row per
float @param: slider (base) + its routes (source ▾, depth, curve ▾,
attack/release in beats, mode ▾, enable, ✕) + "+ route". A live mini-meter
shows the modulated value at the playhead. Changes re-fetch the series. Routes
save with the config.

### Authoring prompt
New "Expose knobs ▸" prompt (alongside Make Reactive), with this ask: *"Expose
this shader's 4–8 most expressive constants as `@param`s with safe ranges, keep
the look identical at defaults, and suggest `@mod` routes from this song's
available data. Don't write audio-reactive code."* The existing paste-back /
fix-it loop is reused.

## 2. Reactivity scorecard

`cedartoy/scorecard.py` (pure numpy; no GL):
- Input: a directory of rendered frames (PNG/EXR/TIFF, any res; downsample to
  ≤ 256 px wide), fps, bundle (+ track settings, av offset).
- Visual features per frame: mean luminance `L`, motion `M` = mean |frame_t −
  frame_{t−1}|, and hue shift `H` (mean circular hue delta, ignoring low-saturation pixels).
- Per source (the MOD_SOURCES set + onset streams): Pearson correlation between
  the source (and its positive derivative for impulsive sources) and each
  visual feature, best lag within ±3 frames (report the lag; a negative lag means
  the visuals lag the audio).
- Jitter: fraction of `M` energy in frames whose motion spike (> median + 3·MAD)
  has no onset/beat within ±2 frames. High = visuals twitch without musical cause.
- Silence check: motion/brightness during sections with iEnergy < 0.1 vs loud.
- Output: JSON `{sources: {name: {feature: {r, lag}}}, jitter, dynamic_range,
  summary: [human-readable lines]}`, e.g. "kick → motion r=0.71 (lag 0)",
  "hats: no visible effect", "jitter 0.32: high".

Entry points:
- CLI: `python -m cedartoy.cli scorecard <frames_dir> --audio song.wav [--fps]`.
- CLI: `render ... --scorecard` renders a fast proxy (e.g. 512×256, 1 temporal
  sample, no tiling) to a temp dir, then scores it.
- API + UI: "Score reactivity" button in Validate mode → server runs a proxy render
  job (existing job infra, low-res overrides) then scores it, and shows the summary
  plus a small per-source bar list.
