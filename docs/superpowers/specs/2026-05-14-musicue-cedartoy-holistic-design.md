# MusiCue ⇄ CedarToy Holistic Integration — Umbrella Design

**Date:** 2026-05-14
**Status:** Approved — ready for implementation planning (three plans, see Rollout)
**Supersedes:** nothing — additive over the existing
`2026-05-13-musicue-bundle-cedartoy-design.md` (Phase 1 bundle integration)
and MusiCue's `2026-05-02-m3-exporters-round1.md`.

---

## Goal

Tighten the MusiCue ⇄ CedarToy seam so:

1. A finished song travels between machines as a self-contained folder
   that any CedarToy install can open.
2. CedarToy treats *attaching that folder* as a first-class workflow
   stage, not a config field — and makes "does this shader actually hit
   the drop?" answerable in seconds, before committing to a multi-hour
   high-resolution spherical render.
3. An existing GLSL shader (e.g. a non-reactive tunnel) can be
   retrofitted with MusiCue-driven reactivity through a documented
   Claude prompt + a versioned cookbook of GLSL snippets — no in-app
   LLM dependency.

CedarToy is fundamentally an **offline high-resolution renderer** —
often spherical (equirect / LL180) — driven by a cuesheet/bundle. The
preview pane exists only to verify reactivity before render. Every UI
decision below reflects that framing.

---

## Scope & three-part decomposition

This umbrella spec is split into three implementation plans, each
independently shippable but bound by a shared file contract (§ Shared
file contract).

| Part | Lives in | Deliverable |
|---|---|---|
| **A — Export for CedarToy** | MusiCue | `Send to CedarToy` button on the Editor page; folder export with bundle + audio + optional stems. |
| **B — Import & verify** | CedarToy | Stage-rail UI (Project → Shader → Output → Render), spherical-first output preset, cue-scrubber timeline, render-budget estimate. |
| **C — Reactivity authoring** | CedarToy docs | `MUSICUE_REACTIVITY_PROMPT.md` + `REACTIVITY_COOKBOOK.md`, plus a stage-[2] button that pre-fills the prompt with the current shader. |

Each part has its own §Tests and §File layout subsection below; each
becomes its own plan during writing-plans.

---

## Shared file contract

Both apps agree on a single layout: **the folder is the project**.

```
<song-folder>/
  song.wav                     audio (canonical name set by exporter)
  song.musicue.json            bundle (schema_version "1.x";
                               source_sha256 matches song.wav)
  stems/                       OPTIONAL — present iff exporter included
    drums.wav  bass.wav  vocals.wav  other.wav
  manifest.json                project metadata, see below
```

`manifest.json`:

```json
{
  "schema": "cedartoy-project/1",
  "audio_filename": "song.wav",
  "original_audio": "User Song Title.mp3",
  "grammar": "concert_visuals",
  "musicue_version": "0.4.1",
  "exported_at": "2026-05-14T19:32:11Z"
}
```

Notes:

- No zip / `.cedarpack` container in v1 — that is an explicit non-goal.
- CedarToy resolves a project from *any* file or folder inside it: a
  drop of `song.wav`, of `song.musicue.json`, or of the folder itself,
  all resolve to the same project.
- Older folders without `manifest.json` (e.g. produced by today's
  `musicue export-bundle` CLI before this work) still load — the
  manifest is informational, not load-critical.
- Stems are sibling-discoverable. Future per-stem uniforms
  (`iVocalEnergy`, `iBassEnergy`) light up when stems are present and
  MusiCue's `stems_energy` is populated; otherwise they stay zero —
  same opt-in pattern as today's bundle uniforms.

---

## Part A — MusiCue "Send to CedarToy"

### UI

One new primary button on the Editor page, beside the existing
`Export cuesheet ▼`:

```
[ Export cuesheet ▼ ]   [ → Send to CedarToy ]
```

Clicking opens a small dialog (not the full Export modal):

```
Send to CedarToy
─────────────────────────────────────
Output folder:  [ …/exports/<song>/    ] [Browse]
Grammar:        [ concert_visuals  ▼ ]
[✓] Include stems (drums/bass/vocals/other)
[ ] Force re-analyze (ignore cache)

                              [Cancel]  [Export ▶]
```

### Backend

New HTTP endpoint `POST /api/songs/{id}/send-to-cedartoy` that:

1. Resolves analysis (cached, or re-run if `force_analyze=true`).
2. Compiles cuesheet with the chosen grammar (default `concert_visuals`).
3. `build_bundle(analysis, cuesheet)` → write
   `<out>/song.musicue.json`.
4. Copies source audio → `<out>/song.wav`. If the source is `.wav`
   matching the analyzed sha, hardlink/copy. Otherwise decode → WAV via
   soundfile at the source's native sample rate (no resampling).
5. If `include_stems`: copies cached Demucs stems
   (`runs/<song>/stems/*.wav`) → `<out>/stems/`. Re-runs Demucs if
   `force_analyze` is set; if cache is missing and force is off, warns
   and exports without stems, recording the omission in `manifest`.
6. Writes `<out>/manifest.json`.
7. Streams progress events `{stage, pct, eta}` back to the dialog using
   the existing export-job streaming machinery.

Atomicity: write everything to a sibling temp folder, then atomic-rename
on success. No partial folder ever visible to CedarToy.

### CLI parity

Extend the existing `musicue export-bundle` with `--folder PATH` and
`--include-stems`. When `--folder` is set, the command writes the
folder layout above (not a bare `.musicue.json`). The today-form
(emit a sibling `.musicue.json` only) keeps working as a default.

A thin alias `musicue send-to-cedartoy` is added for discoverability,
internally calling the same code path.

### Tests (Part A)

`tests/test_send_to_cedartoy.py`:

- Endpoint produces folder with expected files.
- `manifest.json` fields correct (grammar, version, timestamp, original
  filename).
- Bundle `source_sha256` matches the copied `song.wav` sha.
- Stems present iff `include_stems=True`.
- `force_analyze=True` re-runs pipeline (mock `run_analysis`, assert
  called).
- Atomic-rename: simulated failure mid-export leaves no folder at the
  target.
- CLI parity: `musicue export-bundle --folder <out>` produces a layout
  byte-identical to the web endpoint.

### File layout (Part A)

```
D:\MusiCue\
  musicue/api/send_to_cedartoy.py                  NEW endpoint
  musicue/cli.py                                   MODIFY — --folder / --include-stems flags + alias
  musicue/compile/bundle.py                        UNCHANGED (existing)
  musicue/ui/web/src/components/
    SendToCedartoyDialog.tsx                       NEW dialog
  musicue/ui/web/src/pages/Editor.tsx              + button
  tests/test_send_to_cedartoy.py                   NEW
```

### Part A non-goals

- No zip / single-file pack format.
- No Library-page batch send button (CLI handles batch).
- No upload-to-remote-CedarToy. File delivery is the user's job.

---

## Part B — CedarToy stage rail + cue scrubber

### Layout

```
┌─ CedarToy ────────────────────────────────────────────────────────┐
│  [1] Project  ›  [2] Shader  ›  [3] Output  ›  [4] Render         │
├───────────────────────────────────────────────────────────────────┤
│  active stage panel (left)        │  preview + cue scrubber       │
│                                   │  (persistent across stages)   │
└───────────────────────────────────────────────────────────────────┘
```

Shader-browser side panel collapses by default; auto-opens on stage [2].
Existing `RenderJob`/`config_model` schemas are unchanged — this is
front-end reorganization plus a project-loader endpoint.

### Stage [1] — Project

```
┌─ Project ────────────────────────────────────────────────┐
│  Drop a song folder (or any file inside one)             │
│  ───────────────────────────────────────────             │
│  Audio   ✔ song.wav            44.1 kHz · 3:42           │
│  Bundle  ✔ song.musicue.json   schema 1.0 · sha match    │
│          ↳ grammar: concert_visuals · 124 BPM · 8 sects  │
│  Stems   ✔ drums bass vocals other  (4)                  │
│                                                          │
│  [Open another project]                                  │
└──────────────────────────────────────────────────────────┘
```

Validation rules:

| Situation | Surface |
|---|---|
| Bundle `source_sha256` ≠ audio sha | Red banner, "stale bundle — re-export from MusiCue". Allow proceed via checkbox. |
| `manifest.musicue_version` outside compatible range | Yellow warning row. |
| Missing bundle | Info row only ("no bundle — raw FFT mode"); no error. |
| Missing manifest | Tolerated silently — older exports work. |
| Bundle `schema_version` major incompatible | Block project load with the specific MusiCue version needed. |
| Drag of single file (audio or bundle) | Resolve to parent folder and apply same validation. |

### Stage [2] — Shader

Existing shader browser + parameter form, with one new read-out at the
top of the parameter panel:

```
Reactivity in this shader:
  Declared uniforms:  iBpm  iBeat  iEnergy
  Missing (cookbook): iBar  iSectionEnergy  iChannel0
  [Make this shader reactive ▸]   ← opens Part C prompt template
```

Detection is a regex grep over the loaded shader source for
`uniform\s+\w+\s+(iBpm|iBeat|iBar|iSectionEnergy|iEnergy|iChannel0);`
— no shader compilation required.

### Stage [3] — Output (spherical-first)

The current `camera_mode` dropdown is promoted to **Output preset**.
The flat-16:9 option is demoted to a preview/test preset; equirect is
the default for new projects.

```
Output preset:  ( ) Equirectangular 2:1   ← recommended for VR / dome
                ( ) LL180 dome
                ( ) Flat 16:9             ← preview / test only
Resolution:     [ 8192 ] x [ 4096 ]   [Apply preset]
FPS:            [ 60 ]
Tiling:         [ 4 ] x [ 2 ]   → 8 tiles · 2048 × 2048 each
Format:         PNG 8-bit / EXR 16f / EXR 32f
Estimated:      9 min / frame · ~33 hr total · 142 GB
```

The estimate is computed by `cedartoy/render_estimate.py`:

- `frame_time_sec = base_shader_cost(shader) × tile_count × ss_scale²`
  where `base_shader_cost` is a moving-average from prior renders
  (default = 5 s if no history yet).
- `total_frames = ceil(duration_sec × fps)`.
- `total_seconds = total_frames × frame_time_sec`.
- `output_bytes = total_frames × bytes_per_frame(format, bit_depth,
  width, height)`.

A small history file at `~/.cedartoy/render_history.json` records prior
runs `(shader_path, resolution, ss_scale, tile_count, mean_frame_time)`
keyed by `(shader_basename, resolution_class)`. Stage [3] uses this to
refine the per-frame estimate; absent any history, the static 5 s
default is shown with a "(no prior render data)" hint.

### Stage [4] — Render

Same render panel as today, with one new gate:

```
if render_estimate.total_seconds > 3600
   or render_estimate.output_bytes > 50 * 1024**3:
   show confirm-modal with the estimate
```

Modal has a per-project "don't ask again" checkbox stored in
`localStorage`.

### Cue scrubber (always-on, below preview)

```
┌─ Preview ──────────────────────────────────┐
│   (low-res, scaled to fit, loops)          │
├────────────────────────────────────────────┤
│ intro │ verse        │ chorus     │ bridge │  ← sections
│ │┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│┃│ │  ← bars/beats
│  •  • • •  •   ••• • •   •••  •••  •• •   │  ← kick onsets
│  ░░░▒▒▒▓▓▓▓▓▓▓▓██████████▓▓▒▒░░░░          │  ← energy curve
├────────────────────────────────────────────┤
│ t=01:23.45  iBpm 124  iBeat 0.42  iBar 17  │
│ iEnergy 0.81  iSectionEnergy 0.93          │
│ [⏵] [⏸] [⏮ prev drop] [⏭ next drop]       │
└────────────────────────────────────────────┘
```

- Click on the timeline to jump preview playback to that time.
- Section blocks, bar grid, kick dots, and energy curve are read
  directly from the bundle JSON — no extra audio analysis.
- `[⏮ prev drop]` / `[⏭ next drop]` use the bundle's section
  `energy_rank` — "drops" are sections with `energy_rank ≥ 0.7`, in
  time order.
- Uniform readout below the scrubber is what makes "is the shader
  actually reading these uniforms?" answerable at a glance — values
  update once per preview frame.

### Render-budget guardrail

Confirm-modal in stage [4] when the estimate exceeds either threshold
(see Stage [4] above). Single checkbox to dismiss permanently per
project (stored in `localStorage` keyed by project folder path hash).

### Project loader

New module `cedartoy/project.py`:

```python
@dataclass
class CedarToyProject:
    folder: Path
    audio_path: Path
    bundle_path: Path | None
    stems_paths: dict[str, Path]          # {} when absent
    manifest: dict | None                 # None for legacy folders
    bundle_sha_matches_audio: bool        # False when mismatch or no bundle

def load_project(target: Path) -> CedarToyProject:
    """Resolve any file or folder inside a project to a CedarToyProject.

    Accepts a folder, an audio file, or a bundle file. Walks up to the
    containing folder, validates layout, computes sha matching.
    """
```

A new HTTP endpoint `POST /api/project/load` receives `{path}` and
returns the dataclass serialized as JSON. Stage [1] hits this endpoint
on drop / Browse.

### What changes vs. today

| Area | Today | After |
|---|---|---|
| Bundle attach | Typed absolute path in config form | Drop folder, validated, sha-checked |
| `audio_mode` + `bundle_mode` | Two confusing dropdowns in same section | `bundle_mode` becomes an advanced toggle (default `auto` covers 99% of cases) |
| Spherical output | One of three equally-weighted camera modes | First-class "Output preset" with the spherical options foregrounded |
| Reactivity verification | Render and hope | Scrubber + uniform read-out, before render |
| Render budget | No warning | Estimate visible in stage [3]; threshold guard at [4] |

### Tests (Part B)

| File | Coverage |
|---|---|
| `tests/test_project_loader.py` | Folder resolution from folder / audio / bundle path; sha-mismatch reporting; missing-bundle fallback; missing-manifest tolerance; corrupt manifest handled. |
| `tests/test_render_estimate.py` | Frame-time × tile × ss² math; PNG / EXR size math; threshold-trigger booleans; history-file read/write. |
| `tests/test_cue_scrubber_render.py` | Component test with a fixture bundle — verifies section blocks, beat ticks, kick dots are positioned at expected x-coordinates given a 600px-wide canvas. |
| Manual visual A/B | `auroras.glsl` with and without a real bundle; "next drop" lands on the expected timestamp. |

### File layout (Part B)

```
D:\cedartoy\
  cedartoy/project.py                    NEW — folder loader, manifest reader
  cedartoy/render_estimate.py            NEW — frame-time + size math + history
  cedartoy/cli.py                        UNCHANGED
  cedartoy/render.py                     UNCHANGED — RenderJob schema preserved
  web/js/components/
    stage-rail.js                        NEW — top stages
    project-panel.js                     NEW — stage [1]
    output-panel.js                      NEW — stage [3], spherical-first
    cue-scrubber.js                      NEW — timeline below preview
    config-editor.js                     SHRINK — fields move into stage panels
  web/index.html                         MODIFY — mount stage rail
  web/css/components.css                 MODIFY — stage rail + scrubber styles
  tests/test_project_loader.py           NEW
  tests/test_render_estimate.py          NEW
  tests/test_cue_scrubber_render.py      NEW
```

### Part B non-goals

- No real-time scrubbable shader playback at final resolution (preview
  stays low-res).
- No new spherical projection modes beyond the existing two.
- No render queue / batch UI (one render at a time).
- No resumable / checkpointed renders — already tracked under
  `docs/superpowers/plans/2026-05-10-production-reliability-pass.md`.

---

## Part C — Reactivity authoring (prompt + cookbook)

Two new documents shipped under `cedartoy/docs/reactivity/`. No app
code. The "Make this shader reactive ▸" button in stage [2] pre-fills
the template and copies / opens it; the LLM call happens outside
CedarToy (Claude.ai or `claude` CLI).

### `MUSICUE_REACTIVITY_PROMPT.md`

A single self-contained markdown file the user copies into Claude.
Structure:

```
# Make this GLSL shader MusiCue-reactive

You are modifying an existing Shadertoy-style GLSL shader so it reacts
to a song analyzed by MusiCue. Use ONLY the inputs documented below.
Do not invent uniforms. Prefer cookbook patterns when applicable.

## Inputs available
<exhaustive list of uniforms + iChannel0 layout from AUDIO_SYSTEM.md>

## Rules
1. Preserve the existing visual identity.
2. Modulate parameters the shader already exposes.
3. Cap modulation amplitudes (typical ±20% of base value).
4. Use cookbook patterns where they fit.
5. Emit only the modified shader, in one fenced glsl block, no prose.

## Cookbook (attached)
<verbatim REACTIVITY_COOKBOOK.md>

## Target shader
<paste your shader.glsl here>
```

The "emit only the shader" rule means Claude's output drops straight
into CedarToy.

### `REACTIVITY_COOKBOOK.md`

Versioned snippet library. Header carries `cookbook_version: 1`. Each
entry: name, what it does, snippet, where to drop it, default
amplitude, cap.

v1 cookbook entries:

| Name | One-liner |
|---|---|
| `kick_pulse_camera` | Forward camera nudge 0–8% on `iChannel0` row-0 bins 0–32 (kick) |
| `beat_pump_zoom` | FOV / scale wobble locked to `iBeat` phase, smoothed |
| `section_palette_shift` | Hue/palette index advanced 1 step per section, eased with `iSectionEnergy` |
| `energy_brightness_lift` | Multiply final color by `mix(0.9, 1.15, iEnergy)` |
| `bar_anchored_strobe` | Single bright frame on every Nth downbeat, gated by `iSectionEnergy > 0.6` |
| `melodic_glow_tint` | High-bin sample of `iChannel0` modulates emissive tint |
| `hat_grain` | Hi-bin energy adds film-grain density |

Each entry in the doc looks like:

```glsl
// === kick_pulse_camera (cookbook_version 1) ===
// Adds a forward camera nudge on kick onsets.
// Where: inside camera-position calculation, before final ray origin.
// Amplitude default: 0.08; cap: 0.20.
float kickEnergy = texture(iChannel0, vec2(0.03, 0.25)).r;
vec3 cameraPushOffset = cameraForward * kickEnergy * 0.08;
// add cameraPushOffset to ray origin / eye position
```

### CedarToy hook

Stage [2] adds a single affordance:

```
Reactivity in this shader:
  Declared uniforms: iBpm  iBeat  iEnergy
  [Make this shader reactive ▸]
```

The button:

1. Reads the current shader source.
2. Substitutes it into the prompt template at the marked slot.
3. Inlines the current cookbook.
4. Either opens the resulting markdown in a new tab *or* copies it to
   the clipboard with a toast — both behaviors are acceptable, picked
   during implementation based on browser-API friction.

### Tests (Part C)

`tests/test_reactivity_cookbook.py`:

- Loads each cookbook entry, wraps it in a minimal Shadertoy shell with
  the bundle uniforms declared, and asks CedarToy's existing GLSL
  compiler to compile it. Compile failure ⇒ test failure.
- Verifies cookbook header parses (`cookbook_version: N`).

Manual:

- Run the prompt template through Claude with `shaders/planet_4rknova.glsl`.
- Verify output compiles, declares the expected uniforms, and visibly
  reacts when attached to a real bundle.

### File layout (Part C)

```
D:\cedartoy\
  docs/reactivity/
    MUSICUE_REACTIVITY_PROMPT.md         NEW
    REACTIVITY_COOKBOOK.md               NEW
  web/js/components/shader-editor.js     MODIFY — add prompt button hook
  cedartoy/reactivity.py                 NEW — parse declared uniforms,
                                              build prompt string
  tests/test_reactivity_cookbook.py      NEW
```

### Part C non-goals

- No in-app "Reactivity Wizard" with API-key-driven LLM call or
  diff/A-B view. Explicit follow-up.
- No automatic shader rewriting on disk (output stays in the user's
  hands).
- No multi-LLM-provider support (template is Claude-aimed but
  provider-agnostic in practice).

---

## Cross-cutting error / edge-case matrix

| Situation | Behavior |
|---|---|
| **A: stems cache missing, "Include stems" checked, force_analyze off** | Warn + export without stems + note in `manifest.stems_omitted_reason` |
| **A: target folder exists** | Confirm-overwrite dialog; never silent-clobber |
| **A: source audio not WAV** | Decode → WAV; record `original_audio` in manifest |
| **A: bundle build fails** | Surface ValueError; atomic-rename keeps target clean |
| **B: project folder has audio but no bundle** | Stage [1] info row "no bundle — raw FFT mode"; render works |
| **B: bundle sha mismatches audio** | Red banner; allow override; uniforms still bind |
| **B: bundle schema_version major incompatible** | Block load with specific MusiCue version |
| **B: render estimate > 1 hr or > 50 GB** | Confirm-modal at stage [4] |
| **B: drop of single file (audio or bundle)** | Resolve to parent folder; same validation |
| **C: cookbook version drift** | Generated shaders carry `// cookbook_version: N` comment; template instructs LLM to suggest upgrades when older |
| **C: prompt button on shader with no uniforms declared** | Still opens template; LLM adds uniforms |

---

## Rollout

Three implementation plans, in this order:

1. **Plan A — `send-to-cedartoy`** (smallest, unblocks B's testing with
   real folders).
2. **Plan B-1 — stage rail + project loader** (skeleton of new
   CedarToy UI, no behavior changes to render).
3. **Plan B-2 — cue scrubber + render estimate** (the actual
   workflow wins).
4. **Plan C — reactivity docs + stage-[2] button** (lands any time
   after B-1; the docs themselves are decoupled from app code).

Each plan is generated through writing-plans after this spec is
approved.

---

## Cross-cutting non-goals (deferred to later milestones)

- In-app "Reactivity Wizard" with API-key-driven LLM diff/A-B.
- `.cedarpack` single-file container.
- Per-stem uniforms (`iVocalEnergy`, `iBassEnergy`) — wait for MusiCue
  to populate `stems_energy`, then add cookbook entries.
- Resumable / checkpointed renders — tracked in
  `2026-05-10-production-reliability-pass.md`.
- Web-UI batch send from MusiCue Library page.
- Real-time scrubbable shader playback at final resolution.
