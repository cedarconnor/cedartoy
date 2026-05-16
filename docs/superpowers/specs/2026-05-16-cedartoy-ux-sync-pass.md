# CedarToy UX & Sync Pass — Design Spec

**Date:** 2026-05-16
**Status:** Design approved; ready for plan-writing.
**Scope:** One umbrella spec, five plans.

---

## 1. Problem

Live browser use of CedarToy v0.4 surfaced four interlinked papercuts:

1. **Bundle-vs-audio sha warning is a false positive on every export.** MusiCue sha's the original `source.m4a`; CedarToy re-decodes to `song.wav` and sha's that. They will never match. The warning fires every time, so it's noise, and we can no longer detect *real* corruption.
2. **The Claude round-trip ends in the filesystem.** "Make this shader reactive ▸" copies a prompt; pasting Claude's reply back requires the user to open a file editor, paste, save, and refresh the page. Compile errors are visible only as a small red overlay on the preview canvas — there is no path to feed them back to Claude.
3. **The output panel layout collapses.** Block `<label>`s + inline `<input>`s with no flex/grid wrapper produce a single mashed top row.
4. **Preview has no audio.** `<audio>` playback lives in a legacy `audio-viz` component that has no listener for `project-loaded`, so the project's audio path never reaches the playback engine. The user has to re-pick the audio file via "Choose File". There's no shared playhead across waveform, cue-scrubber, and shader — sync between bundle data, audio, and visuals can't be confirmed.

All four sit on top of the same surface (`web/index.html`) and share the same patterns (the helper-bar idea applies to every stage, the unified clock fixes both the missing-audio and the missing-playhead). One spec, five plans.

## 2. Goals

- A user with a fresh MusiCue export can load a project in CedarToy, hit play, and **hear audio + see a single playhead moving across the cue-scrubber + see the shader animating** — all from one Browse… click and one Spacebar press.
- A user can take a non-reactive shader, click **Make this shader reactive ▸**, paste Claude's reply into a drawer in Stage 2, and have a working `_reactive.glsl` running in the preview — **without leaving the page**. If compilation fails, the same drawer surfaces the GL error and offers a fix-it prompt to feed back to Claude.
- The output panel reads as a control surface with grouped fields, not a single collapsed row.
- The sha-mismatch warning fires only when audio is *actually* corrupt.

## 3. Non-goals

- AudioContext sample-accurate clock. `<audio>.currentTime` is good enough for v1 sync confirmation. Revisit if drift becomes a complaint.
- Per-stem uniforms (`iVocalEnergy`, etc.). Depends on MusiCue populating `stems_energy`.
- Full in-app live GLSL editor with hot-reload-on-save. The paste-back drawer is the round-trip surface.
- Server-side `glslangValidator` validation. Browser-side WebGL compile is exactly what the preview uses; adding a second compile target risks divergent error reporting.
- A reactivity "wizard" that calls the Claude API directly. Clipboard round-trip is the constraint, not a bug — keeps the no-API-key story intact.
- Loop-section playback or multi-shader timelines.

## 4. Architecture

### 4.1 Unit boundaries

```
Server (Python / FastAPI)
├── cedartoy/server/api/project.py        [extend] + GET /api/project/audio (Range)
├── cedartoy/server/api/dialog.py         [new]    POST /api/dialog/pick-folder
├── cedartoy/server/api/shader.py         [extend] + POST /api/shader/apply
├── cedartoy/server/api/reactivity.py     [extend] + GET /api/reactivity/fixit-prompt
├── cedartoy/reactivity.py                [extend] + build_fixit_prompt(...)
└── cedartoy/project.py                   [extend] prefer bundle.decoded_audio_sha256 over source_sha256

Bundle contract (MusiCue → CedarToy)
└── MusiCueBundle.schema_version "1.1"    [bump]   adds decoded_audio_sha256
                                                   (the existing source_sha256 stays for traceability)

Web (vanilla JS components, in web/js/components/)
├── transport-strip.js                    [new]    master clock + audio + FFT + waveform/sections
├── cue-scrubber.js                       [rewrite] waveform underlay, playhead, transport events
├── preview-panel.js                      [rewrite] pure canvas + camera; loses transport controls
├── audio-viz.js                          [delete]
├── output-panel.js                       [rewrite] 2×2 grid layout, pinned estimate
├── project-panel.js                      [extend] + Browse… button
├── stage-helper.js                       [new]    <stage-helper title subtitle> custom element
└── shader-reactivity-drawer.js           [new]    paste-back textarea + compile state + fix-it
```

### 4.2 The new master clock

`transport-strip` owns playback. It wraps a single `<audio>` element bound to `/api/project/audio?path=…`. On `play()/pause()/seek(t)` it drives that element and emits `transport-frame` (with `{timeSec}`) on every `requestAnimationFrame` while playing. **Three subscribers**:

- `preview-panel`: sets `renderer.currentTime = timeSec` and renders.
- `cue-scrubber`: moves its playhead line and updates the uniform readout.
- `transport-strip` itself: moves its own playhead and emits raw FFT (`audio-data` event, same shape as legacy `audio-viz`) for shaders that read `iChannel0` from live FFT.

If `<audio>` is missing or errors, `transport-strip` falls back to a `performance.now()`-based virtual clock so the shader still animates against the bundle.

## 5. Bundle schema v1.1 (where the sha actually lives)

The integrity sha lives in `song.musicue.json` (the `MusiCueBundle`), not in `manifest.json`. The current bundle carries one sha — `source_sha256` — which is the hash of the *original* m4a/mp3 the user fed MusiCue. CedarToy compares it against the hash of the **decoded WAV** it reads, and they will never match for any non-WAV input.

Fix: add a sibling `decoded_audio_sha256` field to the bundle, computed at export time after the WAV has been written. Bump `MusiCueBundle.schema_version` from `"1.0"` to `"1.1"`. The existing `source_sha256` stays for traceability back to the user's original file.

```jsonc
// song.musicue.json — bundle schema 1.1
{
  "schema_version": "1.1",
  "source_sha256":         "88598ecc80d2…",  // sha of the original m4a/mp3
  "decoded_audio_sha256":  "dfd0ebdfe15e…",  // sha of the .wav CedarToy reads  [NEW]
  "duration_sec": 235.4,
  "fps": 24.0,
  // … all other existing fields unchanged
}
```

`manifest.json` is not touched — it stays at `cedartoy-project/1`.

**CedarToy comparison logic** (`cedartoy/project.py`):
1. If bundle has `decoded_audio_sha256`: compare against `sha256(audio_file)`. Real corruption check; warning fires only on actual mismatch.
2. Else (legacy 1.0 bundles): skip the comparison entirely. Show a one-line note: *"Bundle schema 1.0 — audio integrity check unavailable. Re-export from MusiCue for schema 1.1."* No false-positive warning.

**Backwards compatibility:** CedarToy reads both `1.0` and `1.1` bundles. Only `1.1` participates in the integrity check.

## 6. Server API additions

### 6.1 `GET /api/project/audio`

Streams the active project's audio file. Honors `Range:` header so the `<audio>` element can seek without re-downloading the whole song.

- Response: `200 OK` with audio bytes, `Content-Type: audio/wav`, `Accept-Ranges: bytes`.
- `404 Not Found`: project loaded but audio file missing on disk.
- `409 Conflict`: no project loaded.

### 6.2 `POST /api/dialog/pick-folder`

Returns a native OS folder picker dialog and returns the chosen absolute path. Implementation: `tkinter.filedialog.askdirectory()` (cross-platform; Windows uses `comdlg32` under the hood). Modal; blocks until user picks or cancels.

- Body: `{ "initial_dir": "<optional path to start in>" }`
- Response: `200 OK` `{ "path": "<absolute path>" }` on pick; `200 OK` `{ "path": null }` on cancel.
- `503 Service Unavailable` when no display is available (CI, headless).

### 6.3 `POST /api/shader/apply`

Writes a GLSL string to a shader file, atomically.

- Body: `{ "base": "phantom_mode.glsl", "glsl": "...", "mode": "sibling" | "overwrite" }`
- `sibling` mode → writes `shaders/phantom_mode_reactive.glsl` (overwrites existing sibling on retry).
- `overwrite` mode → replaces `shaders/phantom_mode.glsl`.
- Atomic-rename: write to a temp file in the same dir, fsync, rename over the target.
- Response: `200 OK` `{ "path": "shaders/phantom_mode_reactive.glsl" }`.
- `400 Bad Request` on empty `glsl` or invalid `mode`.

### 6.4 `GET /api/reactivity/fixit-prompt`

Builds a Claude-ready fix-it prompt for a broken paste-back attempt.

- Query: `?broken=<path to broken _reactive.glsl>&base=<original shader path>`
- Body: `{ "gl_log": "ERROR: 0:42: ..." }`
- Response: `200 OK` `{ "prompt": "<markdown>" }` — same shape as the existing `GET /api/reactivity/prompt`. Contains: original shader source, broken attempt, verbatim gl_log, full cookbook, directive "fix the compile error while preserving the reactivity goals from the previous prompt".

## 7. Web component contracts

### 7.1 `<transport-strip>` (new)

Replaces the legacy `audio-viz`. Renders directly under the preview canvas as a single horizontal strip:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [▶]  [waveform underlay │ section blocks │ beat ticks │ kick dots │ ▏  ] 01:14 / 03:55 │
└──────────────────────────────────────────────────────────────────────────────┘
  iBpm 125 · iBeat 0.42 · iBar 14 · iEnergy 0.68 · iSectionEnergy 0.83 · chorus
```

**Public API (events it emits):**
- `transport-frame` `{timeSec: float}` — every animation frame while playing.
- `audio-data` `{fft: Float32Array(512), waveform: Float32Array(512)}` — every animation frame while playing (mirrors today's `audio-viz` so shaders that read raw FFT keep working).

**Public API (events it listens for):**
- `project-loaded` `{audio_path, bundle_path, manifest, audio_url}` — loads audio source, resets to t=0, paints waveform/sections.
- `transport-seek` `{t: float}` — sets `<audio>.currentTime = t`. Dispatched by cue-scrubber clicks.
- Keyboard: Space (toggle play/pause), ←/→ (seek ±1s), `[` / `]` (jump prev/next section), but only when focus is on body or transport-strip.

### 7.2 `<cue-scrubber>` (rewrite)

Loses ownership of click-to-seek (still captures clicks but emits `transport-seek`). Gains a waveform peaks layer rendered as a polyline using the existing `/api/audio/waveform` endpoint. Gains a single vertical playhead line driven by `transport-frame`.

When no bundle is loaded, draws the waveform only — section/beat/kick layers are absent. Readout shows `iEnergy (raw)` from the FFT analyser; bundle-only uniforms show `—`.

### 7.3 `<preview-panel>` (rewrite)

Becomes a pure WebGL canvas + camera-mode/tilt controls. Removes its `#play-btn`, `#time-slider`, `#time-display`. Subscribes to `transport-frame` and sets `renderer.currentTime` from it. Camera controls still emit `config-change` for the renderer.

Adds a new event `shader-compile-result` `{ok: bool, log: string}` that fires after every `compileShader()` call, capturing the concatenated vertex + fragment + link logs from `gl.getShaderInfoLog()` / `gl.getProgramInfoLog()`.

### 7.4 `<output-panel>` (rewrite)

Layout: 2×2 grid by concern.

```
┌────────────────────────────────────────────────────────────────┐
│ Stage 3 · Output — Pick a preset, set duration, then Render.  │  ← <stage-helper>
├────────────────────────────────────────────────────────────────┤
│ ┌──────────────────┐ ┌──────────────────┐                     │
│ │ GEOMETRY         │ │ TIME             │                     │
│ │ Preset │Equirect ▼│ │ FPS      [ 60 ]   │                     │
│ │ Res    │8192×4096│ │ Duration [120 s]  │                     │
│ │ Tilt   │  39°    │ │                  │                     │
│ └──────────────────┘ └──────────────────┘                     │
│ ┌──────────────────┐ ┌──────────────────┐                     │
│ │ QUALITY          │ │ FILE             │                     │
│ │ Supersample [2x] │ │ Format    [PNG ▼] │                     │
│ │ Temporal    [ 4]│ │ Bit depth [8-bit▼]│                     │
│ │ Shutter   [0.5] │ │                  │                     │
│ │ Tiling   1 × 1  │ │                  │                     │
│ └──────────────────┘ └──────────────────┘                     │
│                                                                │
│ Estimate: 5.0 s/frame · 14400 frames · ~20 min · 6.4 GB        │  ← pinned bottom
└────────────────────────────────────────────────────────────────┘
```

Every input has a `title=""` tooltip explaining what it does (e.g. "Temporal samples ≥ 2 enables motion blur; higher values are slower").

### 7.5 `<project-panel>` (extend)

Gains a `Browse…` button next to the path input. Clicking it calls `POST /api/dialog/pick-folder` and on success populates the input and triggers Load. The text input stays — for paste-and-keyboard workflows.

### 7.6 `<stage-helper>` (new)

```html
<stage-helper
  title="Stage 1 · Project"
  subtitle="Load a folder produced by MusiCue's Send to CedarToy. CedarToy reads the bundle, links audio, and shows what's inside.">
</stage-helper>
```

Rendered as the compact bar at the top of every stage panel. Applied to all four stages.

### 7.7 `<shader-reactivity-drawer>` (new)

Lives under the existing "Make this shader reactive ▸" button in the config editor (Stage 2). Two visual states:

**Idle / clean compile state:**

- Textarea: `placeholder="Paste Claude's reply (including the \`\`\`glsl fence) here…"`
- Buttons: `Apply` (default; writes `_reactive.glsl` sibling), `Apply over original` (confirm modal).
- Success banner after compile: `✔ Compiled · running phantom_mode_reactive.glsl`.

**Error state (compile failed):**

- Error banner: `✗ Compile failed · phantom_mode_reactive.glsl`.
- Verbatim GL log in a monospace box (max-height 90px, scroll).
- Buttons: `📋 Copy fix-it prompt ▸`, `Revert to original`.

Paste extraction: extract first fenced `\`\`\`glsl` block; if absent and paste starts with `#version` / `precision` / `void main`, treat whole paste as GLSL; otherwise show "Couldn't find a \`\`\`glsl block".

## 8. Data flows

### Flow A — Loading a project

```
[Browse…]  → POST /api/dialog/pick-folder → server picks via tkinter → {path}
           → POST /api/project/load       → server reads manifest, validates audio
           → 'project-loaded' event {audio_path, bundle_path, manifest, audio_url='/api/project/audio'}
              ↓                ↓                  ↓
        project-panel    transport-strip     cue-scrubber
        (renders         (sets <audio src>,  (loads bundle, draws
         summary)         arms transport,     sections+beats+kicks
                          fetches waveform    +waveform underlay)
                          peaks)
```

### Flow B — Playing

```
transport-strip.play()
   → <audio>.play()
   → rAF loop reads <audio>.currentTime each frame
   → emits 'transport-frame' {timeSec}
       ↓                  ↓                       ↓
  preview-panel      cue-scrubber           transport-strip (self)
  (renderer.         (moves playhead         (moves own playhead,
   currentTime=t,    line, updates           emits FFT 'audio-data')
   renders WebGL)    readout)
```

### Flow C — Apply Claude's GLSL → maybe error → fix-it

```
[Drawer: textarea has Claude's reply]
   → drawer extracts ```glsl ... ``` block
   → POST /api/shader/apply {base, glsl, mode:"sibling"}
   → server writes shaders/<name>_reactive.glsl atomically
   → drawer dispatches 'shader-select' with new path
       ↓
   preview-panel.loadShader(path)
   → api.getShader(path) → GLSL source
   → renderer.compileShader(source)
   → fires 'shader-compile-result' {ok, log}
       ↓
   ┌── compile OK ────────┐  ┌── compile FAIL ──────────────────────────┐
   │ drawer shows         │  │ drawer flips to error state, shows log,  │
   │ ✔ Compiled · running │  │ enables 'Copy fix-it prompt ▸'.          │
   │ <name>_reactive.glsl │  │ Click → POST /api/reactivity/fixit-prompt│
   └──────────────────────┘  │ → clipboard. User pastes back, Apply.    │
                             └──────────────────────────────────────────┘
```

## 9. Error handling

| Case | Behavior |
|---|---|
| No project loaded, user hits play | Transport play disabled. Tooltip: "Load a project first." |
| Project loaded but bundle missing (raw FFT mode) | Audio plays. Cue-scrubber draws waveform only. Readout: `iEnergy (raw)` from FFT; other bundle uniforms show `—`. |
| Audio file missing | `GET /api/project/audio` → 404. Transport: "audio file not found at &lt;path&gt;" with Re-export link. Shader keeps animating against virtual clock. |
| `decoded_audio_sha256` mismatch (bundle 1.1) | Sticky banner: "Audio has changed since MusiCue exported it." Project still loads. |
| Bundle 1.0 (legacy) | Benign banner: "Bundle schema 1.0 — integrity check unavailable. Re-export for 1.1." No warning. |
| Native dialog unavailable | `/api/dialog/pick-folder` → 503. Falls back to text input with explanation. |
| Paste-back: no `\`\`\`glsl` fence | Fall back to whole-paste if it starts with `#version`/`precision`/`void main`. Otherwise: "Couldn't find a `\`\`\`glsl` block." |
| Paste-back: overwrite original | Confirm modal: "Overwrite `phantom_mode.glsl`? This can't be undone." Fires only on "Apply over original". |
| Compile failed but textarea empty | "Copy fix-it prompt ▸" disabled. Tooltip: "Apply a shader first." |
| Repeated compile failures | Each Apply overwrites the same `_reactive.glsl`. No `_v2`/`_v3` accumulation. |
| Seek past end | Audio pauses; clock holds at `audio.duration`; shader holds last frame. |
| Spacebar in input/textarea | Default text behavior. Play/pause only when focus is body or transport-strip. |
| Project loaded mid-playback | Transport pauses, resets to t=0, reloads audio. No auto-play. |

## 10. Testing

**Server (pytest):**
- `tests/test_project_audio_endpoint.py` — bytes + Range + 404 + 409 cases.
- `tests/test_dialog_pick_folder.py` — happy path, 503 when no display (mock).
- `tests/test_shader_apply.py` — sibling write, atomic-rename, overwrite, 400 on empty.
- `tests/test_reactivity_fixit_prompt.py` — output is deterministic; contains all expected sections.
- `tests/test_bundle_v1_1.py` — bundle 1.0 reads with benign note (no warning); 1.1 fires only on real `decoded_audio_sha256` mismatch.

**MusiCue:**
- `tests/test_bundle_decoded_sha.py` — emits both `source_sha256` and `decoded_audio_sha256`; the latter equals `sha256()` of the written wav bytes.

**Web (Playwright):**
- `tests/web/test_sync_workflow.py` walks: Browse → load → no Choose File present → play → playhead moves → click cue-scrubber midpoint → audio + renderer land within ±100ms → click Make Reactive → paste good GLSL → ✔ Compiled → paste broken GLSL → ✗ Compile failed with non-empty log + fix-it button enabled.

**Explicitly not tested:**
- Audio-shader drift below 50ms.
- The native dialog UI itself (mocked).
- Specific GL compile log text (varies by driver).

## 11. Rollout — five plans

1. **Plan A — Bundle schema 1.1 + sha fix** *(MusiCue + CedarToy)*. Bump `MusiCueBundle.schema_version` to 1.1, emit `decoded_audio_sha256` after WAV write, CedarToy prefers it over `source_sha256`. Kills the false-positive warning. Smallest blast radius; unblocks user confidence in the bundle pipeline.
2. **Plan B — Unified transport + project audio endpoint + cue-scrubber rewrite** *(CedarToy)*. The headline sync work. Adds `/api/project/audio`, builds `transport-strip`, deletes `audio-viz`, paints waveform underlay + playhead in the cue scrubber, makes preview-panel a pure canvas.
3. **Plan C — Native folder dialog** *(CedarToy)*. `/api/dialog/pick-folder` + Browse… button.
4. **Plan D — Output grid + stage-helper + tooltips** *(CedarToy)*. Layout-only. 2×2 grid rewrite of `output-panel`, `<stage-helper>` component, per-input tooltips.
5. **Plan E — Paste-back drawer + fix-it loop** *(CedarToy)*. `/api/shader/apply`, `/api/reactivity/fixit-prompt`, `shader-reactivity-drawer` component, `shader-compile-result` event in preview-panel.

Plans are independent (Plan B is the only one that touches multiple components). Each plan ships its own README updates and its own Playwright smoke run.

## 12. Open questions / future work

- **AudioContext sample-accurate clock** — revisit if `<audio>.currentTime` drift becomes a complaint during real renders.
- **Per-stem uniforms** — depends on MusiCue's `stems_energy` populating. Add `iVocalEnergy` / `iDrumEnergy` to the cookbook when ready.
- **Loop-section playback** — useful for nailing a single moment. Hook on `[` / `]` keyboard could grow into a loop-mode.
- **Multi-shader timeline** — sequencing shaders across sections. Separate, much bigger spec.
- **In-app live GLSL editor** — full IDE with hot-reload-on-save. The paste-back drawer is the v1 round-trip; revisit when usage shows it's limiting.
