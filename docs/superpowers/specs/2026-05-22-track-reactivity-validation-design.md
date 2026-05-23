# Track-Level Reactivity Validation — Design Spec

**Date:** 2026-05-22
**Status:** Approved for planning
**Topic:** Make MusiCue reactivity visible, verifiable, and tunable in a near-full-screen preview; carry per-track settings through to the final render; align preview and render on one canonical signal path.

---

## 1. Problem & Goal

Today it is hard to tell *what the music is actually driving* in a CedarToy visual:

1. **Preview and render disagree on the audio signal path.** The headless render synthesizes `iChannel0` from the MusiCue bundle (`cedartoy/render.py`, `MusicalSpectrumSynth`), while the browser preview feeds `iChannel0` from a **live WebAudio FFT** of the playing file (`web/js/webgl/renderer.js` ← `transport-strip.js`) and only applies the scalar bundle uniforms. So "preview hit" does not mean "render hit."
2. **No way to isolate a track.** You cannot confirm that kick, snare, vocals, energy, etc. each drive the visual as intended.
3. **The preview is too small** to judge output quality.
4. **The "Make Reactive → apply over original" round-trip looks like a no-op.** Diagnosed below — it is mostly a *visibility* problem, not a broken pipeline.

**Goal:** A near-full-screen "Validate" mode where you play the song, watch a large preview that is driven by the **same** bundle data the render uses, mute/solo individual source tracks, see a per-track timeline graph and a live cue inspector, and have your per-track settings (mute/gain/etc.) persist into the final render.

### 1.1 The "apply over original looks identical" diagnosis

The make-reactive pipeline is **working**: `shader-reactivity-drawer` extracts GLSL → `POST /api/shader/apply` atomic-writes the file (`cedartoy/server/api/shader_apply.py:62`) → dispatches `shader-select` → `preview-panel.loadShader()` refetches and recompiles (`web/js/components/preview-panel.js:189-197`).

It *looks* identical for two reasons:

- **Reactivity is gated off without playback.** Reactive shaders start with a gate like `float bpsActive = step(1.0, iBpm);` (e.g. `shaders/auroras_reactive.glsl`). In the preview's default **free-run** mode, `iBpm`/`iBeat`/`iEnergy` are `0`, so every reactive term is multiplied by `0` and the output collapses to the original look. You only see a difference with the audio timeline active **and the transport playing**.
- **Possible stale GET.** `api.getShader()` (`web/js/api.js:15`) is a plain `fetch()` and `get_shader` returns JSON with no cache headers, so an overwrite (same path) *may* serve a heuristically-cached copy of the old source.

Both are addressed in Phase 6. Validate mode itself resolves the primary cause by driving the preview with non-zero bundle uniforms during playback.

---

## 2. Scope

### In scope
- Near-full-screen **Validate mode** (toggle from the existing edit layout).
- Per-track **mute / solo** for all source tracks; **mutes persist** to the render, **solo is preview-only**.
- **Preview/render parity**: a single canonical per-track timeline drives both.
- Per-track **timeline graph** with native-shape lanes + shared playhead + click-to-seek.
- **Cue inspector** debug stack at the playhead.
- **Bundle health report** (which bundle fields are populated).
- **Section loop** mode (loop chorus/drop/N-bars).
- **Calibration**: per-track gain / threshold / smoothing (mute generalizes to `gain: 0`).
- **A/B comparison grid**: synced raw-FFT / cued / blend / no-audio panels.
- **Make-reactive polish**: shader-reload cache fix; inject bundle-health summary into the reactivity prompt.

### Out of scope (YAGNI / future milestones)
- Per-event ADSR envelopes & semantic-layer repackaging of the bundle (their #8/#9) — the namespaced track model here is a deliberate first step toward it.
- Shader reactivity manifests / sidecar mapping JSON (#5).
- Named cue textures `iCueTex` / `iEventTex` (#10).
- Visual delta meter / frame-diff correlation (#11).
- Contact-sheet / drop renderer (#7).
- A full shared JS+Python "CueFrameProvider" that *evaluates* in both languages — explicitly rejected (see §4.1).
- Audio playback isolation of soloed stems — we drive *visuals*, the song plays normally.
- Per-track gain automation over time / reordering lanes / editing the bundle.

---

## 3. The Track Model

All source tracks, namespaced to avoid the `drums.other` vs `stem.other` collision:

| Track ID | Source in bundle | Drives | Lane shape |
|---|---|---|---|
| `drums.kick` | `drums["kick"]` | `iChannel0` low band | strength-sized impulse ticks |
| `drums.snare` | `drums["snare"]` | `iChannel0` low-mid band | impulse ticks |
| `drums.hat` | `drums["hat"]` | `iChannel0` mid-hi band | impulse ticks |
| `drums.tom` | `drums["tom"]` | `iChannel0` low-mid band | impulse ticks |
| `drums.cymbal` | `drums["cymbal"]` | `iChannel0` mid-hi band | impulse ticks |
| `drums.other` | `drums["other"]` | `iChannel0` mid-hi band | impulse ticks |
| `stem.vocals` | `midi_energy["vocals"]` | `iChannel0` high band | energy sparkline |
| `stem.other` | `midi_energy["other"]` | `iChannel0` high band | energy sparkline |
| `stem.bass` | `midi_energy["bass"]` | `iChannel0` high band (low-leaning) | energy sparkline |
| `tempo` | `tempo` + `beats` | `iBpm`, `iBeat`, `iBar` | downbeat/beat ticks |
| `sections` | `sections` | `iSectionId`, `iSectionEnergy` | labeled color blocks |
| `energy` | `global_energy` | `iEnergy` | sparkline |

The exact band ranges remain those in `MusicalSpectrumSynth` (`low 0:32`, `low_mid 32:96`, `mid_hi 96:256`, `high 256:512`). The band→track assignment above is the canonical mapping; it lives in **one** place in Python (§4) and is the contract the parity test pins.

### 3.1 Per-track settings (config-persisted)

```yaml
track_settings:
  drums.kick:  { gain: 1.0, mute: false, threshold: 0.0, smoothing: 0.0 }
  stem.vocals: { gain: 1.0, mute: false, threshold: 0.0, smoothing: 0.0 }
  # ... any track may be present; absent tracks use defaults below
```

- **gain** `float ≥ 0` (default `1.0`) — scales the track's contribution. Calibration sliders allow `> 1.0` (e.g. up to ~4) for boosting.
- **mute** `bool` (default `false`) — equivalent to `gain: 0` but kept explicit so muting and a tuned gain are independent (un-mute restores the slider value).
- **threshold** `float [0,1]` (default `0`) — values below this are floored to 0 before gain (gate weak hits).
- **smoothing** `float [0,1]` (default `0`) — one-pole low-pass on the track's per-frame value (0 = none, →1 = heavy). Applied causally so render and preview match.

**Effective contribution per track per frame:**
`v' = smooth( max(0, v - threshold) ) * gain`, with `mute` forcing `v' = 0`. Absent track ⇒ defaults (pass-through).

**Persistence:** `track_settings` lives in the config-editor config (saved to localStorage) and is written into the render job. This is the **shared mask** — what you mute/tune in Validate mode is exactly what the render uses. **Solo is not persisted**; it is client-only UI state that computes an *effective* mask = "all tracks except the soloed set are muted" for the live preview only.

---

## 4. Architecture — one canonical signal path

```
bundle (.musicue.json)
   │
   ▼  GET /api/reactivity/track-timeline?audio=<path>
PerTrackTimeline   (precomputed once, whole song, at analysis fps)
   • per track: its ISOLATED contribution to each iChannel0 band, per frame
   • per track: the uniform series it drives (bpm/beat/bar/sectionId/
     sectionEnergy/energy)
   • lane-draw data: drum onsets (t, strength), stem/energy curves,
     section blocks (start,end,label,id,energyRank), beat/downbeat ticks
   • health: which bundle fields are populated + counts
   │
   ├──► CLIENT (Validate mode)
   │      • track-timeline graph draws straight from lane-draw data
   │      • each frame: apply track_settings (+ solo) → for un-muted tracks,
   │        iChannel0 = Σ (band contributions); uniforms = Σ/select of the
   │        masked uniform series → feed renderer
   │      • mute/solo/gain = which/how tracks are summed — instant, no
   │        per-frame server call
   │
   └──► RENDER (cedartoy/render.py)
          • applies the SAME track_settings (from config) by composing the
            SAME per-track contributions inside MusicalSpectrumSynth /
            BundleEvaluator → identical iChannel0 + uniforms
```

### 4.1 Why precompute-and-sum, not a shared evaluator

ChatGPT's review proposed a shared "CueFrameProvider" evaluated in *both* Python and JS. We reject that specific shape: two evaluators in two languages drift. Instead **Python stays the single canonical evaluator.** It emits each track's *isolated* contribution; both consumers merely **select-and-sum-and-scale**. Preview and render therefore match *by construction*, the synth logic exists once, and the client carries no reimplemented DSP. A parity test (§8) asserts the client's summation semantics equal the Python render output for sample frames.

### 4.2 PerTrackTimeline shape (response sketch)

```jsonc
{
  "fps": 24.0,
  "duration_sec": 201.72,
  "frames": 4841,
  "bands": ["low", "low_mid", "mid_hi", "high"],
  "tracks": {
    "drums.kick":  { "band": "low",  "contrib": [/* per-frame band rows or
                                                     compact band-energy */],
                     "onsets": [{ "t": 0.51, "strength": 0.8 }, ...] },
    "stem.vocals": { "band": "high", "curve": { "hop_sec": 0.04,
                                                "values": [...] } },
    "tempo":       { "bpm": 128.0, "beats": [{ "t":..., "isDownbeat":true,
                                               "bar":..., "beatInBar":... }] },
    "sections":    { "blocks": [{ "start":..,"end":..,"label":"chorus",
                                  "id":1,"energyRank":0.9 }] },
    "energy":      { "curve": { "hop_sec": 0.04, "values": [...] } }
  },
  "health": {
    "beats": { "present": true,  "count": 240 },
    "sections": { "present": true, "count": 18 },
    "drums": { "kick": 312, "snare": 188, "hat": 0, ... },
    "midi_energy": { "vocals": true, "other": true, "bass": false },
    "stems_energy": { "present": false }
  }
}
```

The `contrib` representation may be compacted (e.g. per-frame scalar band energy that the client expands into the 512-bin Hann-windowed row using the shared band-fill function, also exposed to JS as a tiny pure helper) to keep the payload small; the chosen encoding is an implementation detail of Phase 1, constrained by the parity test.

---

## 5. UI / UX

### 5.1 Validate mode (full-screen) — chosen layout "A"

- An **Edit / Validate** toggle in the header (`web/index.html` + `web/js/app.js`) flips the whole app into a near-full-screen layout. Edit panels (shader browser, config, output) are hidden; flipping back restores them exactly.
- Layout top→bottom: large **preview canvas** (fills available space, preserving aspect), then the docked **track-timeline graph**, then the **transport** controls.
- New component `web/js/components/validate-view.js` owns the mode; `web/js/components/track-timeline.js` owns the graph.

### 5.2 Track-timeline graph

- One **lane per track** (§3), drawn in its native shape:
  - drums → impulse ticks, height ∝ strength;
  - stems / energy → continuous sparkline;
  - sections → labeled colored blocks;
  - tempo → beat ticks (taller on downbeats).
- Each lane gutter has **M** (mute) and **S** (solo) buttons. Muted lanes render dimmed; soloed lanes highlighted.
- Shared **playhead** sweeps across all lanes; **click-to-seek** reuses the existing `transport-seek` event (`web/js/components/cue-scrubber.js`).
- Lanes whose track has `health.present == false` (e.g. empty `stem.bass`) show a subtle "no data" treatment so dead tracks are obvious (ties to §5.4).

### 5.3 Cue inspector (debug stack at playhead)

A compact readout panel updated each frame: current `section` (label + id) · `bar`/`beat` · per-track pulse/energy values (kick, snare, hat, …, vocals, bass, energy) · the actual scalar uniform values being sent (`iBpm`, `iBeat`, `iBar`, `iSectionId`, `iSectionEnergy`, `iEnergy`) · current bundle mode. Removes all doubt about "is it driving?".

### 5.4 Bundle health report

Surfaced in Validate mode (e.g. a header strip or inspector section) from `PerTrackTimeline.health`: which of beats/sections/drums(per class)/midi_energy(per stem)/stems_energy are populated and their counts. Empty fields are flagged as data quality, not silently zero.

### 5.5 Section loop

In Validate mode: select a section (or "N bars around playhead") and loop transport playback over it. Uses existing section/beat data + transport seek. UI: a loop toggle + section picker / bar-count.

### 5.6 Calibration panel

Per-lane controls for `gain` / `threshold` / `smoothing` (mute is the existing M button = `gain 0` semantics but stored as `mute`). Writes into `track_settings`; applied live in preview and persisted to render. Sliders: gain `0–4`, threshold `0–1`, smoothing `0–1`.

### 5.7 A/B comparison grid

A toggle within Validate mode that splits the preview into synchronized panels — **raw FFT**, **cued (bundle)**, **blend**, **no-audio** — same shader, same playhead, same frame. Implemented by rendering the current shader N times with different audio-source inputs (cued = our masked composition; raw = live FFT path retained; blend = mix; no-audio = zero uniforms/texture). Lets you see whether the bundle is helping or hiding the music.

---

## 6. Components & Files

### Backend
- `cedartoy/musicue.py` — refactor `MusicalSpectrumSynth` + `BundleEvaluator`:
  - expose **per-track band contributions** and **per-track uniform series**;
  - accept `track_settings` and apply gain/threshold/smoothing/mute when composing;
  - keep a single canonical band→track mapping and band-fill function (the latter mirrored as a tiny pure JS helper for the client).
- `cedartoy/server/api/reactivity.py` — `GET /api/reactivity/track-timeline` returning `PerTrackTimeline` (§4.2); enrich the reactivity prompt with a bundle-health summary (Phase 6).
- `cedartoy/types.py` + `cedartoy/config_model.py` — add `track_settings` to the render job/config model with defaults (§3.1); thread into `render.py`.
- `cedartoy/render.py` — read `track_settings` from the job and pass to the synth/evaluator so muted/tuned tracks are reflected in the final render.
- `cedartoy/server/api/shaders.py` — add `Cache-Control: no-store` to `get_shader` (Phase 6).

### Frontend
- `web/js/components/validate-view.js` *(new)* — full-screen mode + Edit/Validate toggle.
- `web/js/components/track-timeline.js` *(new)* — multi-lane graph, native-shape rendering, M/S, playhead, click-to-seek, dim-when-no-data.
- `web/js/components/cue-inspector.js` *(new)* — playhead debug stack (§5.3).
- `web/js/webgl/renderer.js` / `web/js/components/preview-panel.js` — when a bundle + timeline are loaded, compose masked `iChannel0` + uniforms from the per-track timeline instead of live FFT; support the A/B multi-render.
- `web/js/api.js` — `getTrackTimeline()`; `getShader` cache-bust (`cache: 'no-store'` and/or `?t=`).
- Config-editor — own `track_settings` (localStorage + render config); calibration UI may live here or in `validate-view`.

---

## 7. Phasing

Sequenced so each phase delivers standalone value and later phases build on earlier foundations.

1. **Parity foundation** — `track-timeline` endpoint + canonical synth refactor (per-track contributions, `track_settings`-aware) + bundle health. Wire `track_settings` into `render.py`. *Backend-only; verified by the parity test.*
2. **Validate mode + mute/solo** — full-screen layout, track-lane graph (native shapes), M/S, masked composition driving the preview. *The payoff: preview == render, tracks toggleable, big preview.*
3. **Cue inspector + section loop** — playhead debug stack; loop chorus/drop/N-bars.
4. **Calibration panel** — gain/threshold/smoothing per lane.
5. **A/B comparison grid** — synced raw / cued / blend / no-audio panels.
6. **Make-reactive polish** — shader-reload cache fix (`no-store` + cache-bust); inject bundle-health summary into the Make-Reactive prompt.

The cache fix (Phase 6) is tiny and may be pulled earlier if stale reloads recur.

---

## 8. Testing

### Python
- **Parity test** (cornerstone): for sample frames of a fixture bundle, the client summation semantics (select + sum + gain/threshold/smoothing) equal the `render.py` synth output. Encode the shared composition once and assert byte/near-float equality of the resulting `iChannel0` + uniforms.
- Per-track masking: a muted track contributes nothing to its band/uniform; gain/threshold/smoothing math correct and causal.
- Track namespacing (`drums.other` vs `stem.other` independent).
- `track_settings` config round-trip (defaults applied for absent tracks; load/save).
- `track-timeline` endpoint response shape + health flags (e.g. empty `stems_energy` reported absent).

### Web
- `track-timeline` lane rendering per native shape; M/S toggle behavior; solo computes effective mask; muted lanes dim.
- Edit/Validate mode switch preserves edit state.
- Masked composition feeds renderer; uniforms reflect mutes/gains.
- Cue inspector values track the playhead.
- Section loop bounds playback.
- A/B grid renders the four sources in sync.
- `getShader` cache-bust forces fresh source on overwrite-reload.

---

## 9. Risks & Mitigations

- **JS/Python band-fill drift** → keep the band-fill a single pure function, mirror it minimally in JS, and pin both with the parity test.
- **Timeline payload size** for long songs → compact per-frame band energy + client-side band-fill rather than shipping full 512-bin rows; lazy/streamed if needed.
- **A/B grid performance** (N renders/frame) → cap panel resolution; render sequentially within the frame budget; it is a verification tool, not the main view.
- **Scope creep** → strict phase boundaries; deferred items (§2) explicitly excluded from this spec.
