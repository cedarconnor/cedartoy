# Track Reactivity — Phase 5: A/B Comparison Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A toggleable 2×2 grid in Validate mode showing the *same* shader at the *same* playhead under four audio sources — **raw FFT**, **cued (masked bundle)**, **blend**, **no-audio** — so you can see at a glance whether the MusiCue data is helping or hiding the music.

**Architecture:** A self-contained `<ab-grid>` component owns four `ShaderRenderer` instances (one per small canvas). It compiles the current shader into all four on `shader-select`, caches the live WebAudio FFT (`audio-data`) and the per-track timeline (`/api/reactivity/track-timeline`), and on each `transport-frame` feeds each panel its mode-specific `iChannel0` + uniforms (reusing `cue-compose.js`), then renders. It only does work while visible (A/B toggle on, in Validate mode), so it costs nothing in normal use.

**Tech Stack:** Vanilla JS ES modules + Web Components, WebGL2 (`ShaderRenderer`), FastAPI, pytest, Playwright.

---

## Background facts (read before starting)

- **`ShaderRenderer`** (`web/js/webgl/renderer.js`, imported as `'../webgl/renderer.js?v=4'`): `new ShaderRenderer(canvas)`; `compileShader(source)`; `updateAudioData(fft, waveform)` (two `Float32Array[512]` → texture rows 0/1); `updateBundleUniforms({bpm,beat,bar,energy,sectionEnergy,sectionId})`; `currentTime` field; `render()` renders one frame. Preview drives it in timeline mode by setting `currentTime` + `updateAudioData` + `updateBundleUniforms` + `render()` per `transport-frame` (no play loop needed).
- **`cue-compose.js`** exports: `composeRow1(frameData,f)`, `composeUniforms(frameData,f,eff)`, `effectiveSettings(ts,solo)`, `applySettingsSeries(raw,setting)`, `composeRow0FromValues(bandValues,sectionEnergy)`, `BAND_TRACKS`, `BAND_RANGES`.
- **Events:** `shader-select {path}` (fetch source via `api.getShader(path)`, see `web/js/api.js`), `audio-data {fft, waveform}` (live WebAudio, both `Float32Array[512]`), `transport-frame {timeSec, bundle}` (bundle = unmasked `{bpm,beat,bar,energy,sectionEnergy,sectionId,sectionLabel}`), `track-settings-change {trackSettings, soloIds}`, `project-loaded {audio_path,...}`.
- **Timeline** (`/api/reactivity/track-timeline?audio=<audio_path>`) → `{fps, frames, frame_data:{tracks, uniforms}, tracks, ...}`. `frame_data.tracks[trackId]` is the per-frame raw scalar array.
- **`window.cedartoy.currentShader`** holds the current shader path (no `shaders/` prefix when it came from the browser); `api.getShader(path)` returns `{source}`.
- **Validate-mode CSS** (`web/css/main.css`): `body.validate-mode` controls validate layout. Components imported in `web/js/app.js`; elements placed in `web/index.html` `.preview-panel-wrapper`.
- **No JS unit runner** — source-assertion tests + Playwright live check. The four panels are 320×180 (cheap; 4 extra WebGL contexts is well within limits).

**Panel definitions (the comparison contract):**

| Panel | `iChannel0` source | Uniforms |
|---|---|---|
| **raw** | live WebAudio FFT (cached `audio-data`) | masked `composeUniforms` (only the texture differs from cued) |
| **cued** | masked `composeRow0FromValues` (effective series) | masked `composeUniforms` |
| **blend** | `0.5*raw + 0.5*cued` per-bin | masked `composeUniforms` |
| **no-audio** | zeros | zeros `{}` |

raw/cued/blend share the masked uniforms so the panels isolate the **texture** difference; no-audio zeroes everything to show the un-reactive baseline.

---

## Task 1: `<ab-grid>` component

**Files:**
- Create: `web/js/components/ab-grid.js`
- Test: `tests/web/test_ab_grid_source.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_ab_grid_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/ab-grid.js"


def test_ab_grid_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('ab-grid'" in s
    # four labeled panels
    for label in ("raw", "cued", "blend", "no-audio"):
        assert label in s
    # owns ShaderRenderers + reuses composition
    assert "ShaderRenderer" in s
    assert "composeRow0FromValues" in s and "composeUniforms" in s
    assert "applySettingsSeries" in s
    # synchronized + reactive to inputs
    assert "transport-frame" in s
    assert "audio-data" in s
    assert "shader-select" in s
    assert "track-settings-change" in s
    # only works while active (cheap when off)
    assert "active" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_ab_grid_source.py -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `web/js/components/ab-grid.js`:

```javascript
/**
 * <ab-grid> — 2x2 A/B comparison: same shader + playhead, four audio sources
 * (raw FFT / cued / blend / no-audio). A verification tool for "is the bundle
 * helping?". Idle (no renders) until activated via setActive(true).
 */
import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js?v=4';
import { composeRow1, composeUniforms, effectiveSettings,
    applySettingsSeries, composeRow0FromValues } from '../webgl/cue-compose.js';

const PANELS = ['raw', 'cued', 'blend', 'no-audio'];
const Z = new Float32Array(512);

class AbGrid extends HTMLElement {
    constructor() {
        super();
        this._active = false;
        this._renderers = {};            // panel -> ShaderRenderer
        this._source = null;             // current shader source
        this._timeline = null;
        this._fps = 24.0;
        this._effSettings = {};
        this._effSeries = {};
        this._liveFft = new Float32Array(512);
        this._liveWave = new Float32Array(512);
        this._t = 0;
    }

    connectedCallback() {
        this.render();
        for (const name of PANELS) {
            this._renderers[name] = new ShaderRenderer(this.querySelector(`#ab-${this._id(name)}`));
        }
        document.addEventListener('shader-select', (e) => this._loadShader(e.detail.path));
        document.addEventListener('audio-data', (e) => {
            this._liveFft = e.detail.fft; this._liveWave = e.detail.waveform;
        });
        document.addEventListener('project-loaded', (e) => this._onProject(e.detail));
        document.addEventListener('track-settings-change', (e) => {
            this._effSettings = effectiveSettings(e.detail.trackSettings, e.detail.soloIds);
            this._rebuildEffSeries();
            if (this._active) this._renderAll(this._t);
        });
        document.addEventListener('transport-frame', (e) => {
            this._t = e.detail.timeSec || 0;
            if (this._active) this._renderAll(this._t);
        });
    }

    _id(name) { return name.replace('-', ''); }

    render() {
        this.innerHTML = `<div class="ab-grid">
            ${PANELS.map((n) => `<div class="ab-cell">
                <span class="ab-label">${n}</span>
                <canvas id="ab-${this._id(n)}" width="320" height="180"></canvas>
            </div>`).join('')}
        </div>`;
    }

    setActive(on) {
        this._active = !!on;
        if (this._active && this._source) {
            // (re)compile lazily on first activation
            for (const name of PANELS) {
                try { this._renderers[name].compileShader(this._source); } catch (_) {}
            }
            this._rebuildEffSeries();
            this._renderAll(this._t);
        }
    }

    async _loadShader(path) {
        try {
            const data = await api.getShader(path);
            this._source = data.source;
            if (this._active) {
                for (const name of PANELS) {
                    try { this._renderers[name].compileShader(this._source); } catch (_) {}
                }
                this._renderAll(this._t);
            }
        } catch (_) { /* leave previous source */ }
    }

    async _onProject(detail) {
        const audio = detail?.audio_path || detail?.path;
        this._timeline = null;
        if (!audio) return;
        try {
            const r = await fetch('/api/reactivity/track-timeline?audio=' + encodeURIComponent(audio));
            if (r.ok) {
                this._timeline = await r.json();
                this._fps = this._timeline.fps || 24.0;
                const ce = document.querySelector('config-editor');
                this._effSettings = effectiveSettings((ce && ce.config && ce.config.track_settings) || {}, null);
                this._rebuildEffSeries();
            }
        } catch (_) { this._timeline = null; }
    }

    _rebuildEffSeries() {
        this._effSeries = {};
        if (!this._timeline) return;
        const tracks = this._timeline.frame_data.tracks;
        for (const tid of Object.keys(tracks)) {
            this._effSeries[tid] = applySettingsSeries(tracks[tid], this._effSettings[tid]);
        }
    }

    _frameIndex(t) {
        if (!this._timeline) return 0;
        let f = Math.round(t * this._fps);
        if (f < 0) f = 0;
        if (f >= this._timeline.frames) f = this._timeline.frames - 1;
        return f;
    }

    _cuedRow0(f) {
        const bandValues = {};
        for (const tid of Object.keys(this._effSeries)) bandValues[tid] = this._effSeries[tid][f];
        return composeRow0FromValues(bandValues, this._timeline.frame_data.uniforms.sectionEnergy[f]);
    }

    _renderAll(t) {
        if (!this._source) return;
        const f = this._frameIndex(t);
        const cued = this._timeline ? this._cuedRow0(f) : Z;
        const row1 = this._timeline ? composeRow1(this._timeline.frame_data, f) : Z;
        const uni = this._timeline ? composeUniforms(this._timeline.frame_data, f, this._effSettings) : {};
        const blend = new Float32Array(512);
        for (let i = 0; i < 512; i++) blend[i] = 0.5 * this._liveFft[i] + 0.5 * cued[i];

        this._drive('raw', t, this._liveFft, this._liveWave, uni);
        this._drive('cued', t, cued, row1, uni);
        this._drive('blend', t, blend, row1, uni);
        this._drive('no-audio', t, Z, Z, {});
    }

    _drive(name, t, fft, wave, uniforms) {
        const r = this._renderers[name];
        if (!r) return;
        r.currentTime = t;
        r.updateAudioData(fft, wave);
        r.updateBundleUniforms(uniforms);
        r.render();
    }
}

customElements.define('ab-grid', AbGrid);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_ab_grid_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/ab-grid.js tests/web/test_ab_grid_source.py
git commit -m "feat(web): ab-grid component (raw/cued/blend/no-audio panels)"
```

---

## Task 2: A/B toggle + layout + mount

**Files:**
- Modify: `web/index.html`, `web/js/app.js`, `web/css/main.css`
- Test: `tests/web/test_ab_grid_toggle_source.py` (create)

An "A/B" header button (enabled in Validate mode) toggles `body.ab-mode`; CSS shows the grid (and hides the single preview canvas) only when both `validate-mode` and `ab-mode` are on. `setActive` is called so the grid is idle until shown.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_ab_grid_toggle_source.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ab_grid_mounted_and_toggled():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "<ab-grid>" in html
    assert 'id="ab-toggle"' in html
    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "ab-grid.js" in appjs
    assert "ab-mode" in appjs
    assert "setActive" in appjs               # grid told when active
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "ab-mode" in css
    assert ".ab-grid" in css
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_ab_grid_toggle_source.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

In `web/index.html`, add the toggle next to `#validate-toggle`:

```html
                <button id="ab-toggle" class="btn btn-secondary">A/B</button>
```

Mount the grid in `.preview-panel-wrapper`, after `<cue-inspector>`:

```html
                <ab-grid></ab-grid>
```

In `web/js/app.js`, import the component (after the cue-inspector import):

```javascript
import './components/ab-grid.js?v=1';
```

Wire the toggle (after the validate-toggle wiring):

```javascript
const abToggle = document.getElementById('ab-toggle');
if (abToggle) {
    abToggle.addEventListener('click', () => {
        const on = document.body.classList.toggle('ab-mode');
        abToggle.classList.toggle('btn-primary', on);
        const grid = document.querySelector('ab-grid');
        if (grid && typeof grid.setActive === 'function') grid.setActive(on);
        window.dispatchEvent(new Event('resize'));
    });
}
```

In `web/css/main.css`, append:

```css
/* A/B grid: shown only in validate-mode + ab-mode. */
.ab-grid { display: none; }
body.validate-mode.ab-mode .ab-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 6px; padding: 6px; }
body.validate-mode.ab-mode #preview-canvas { display: none; }
.ab-grid .ab-cell { position: relative; }
.ab-grid .ab-cell canvas { width: 100%; height: auto; background: #000; border-radius: 4px; }
.ab-grid .ab-label { position: absolute; top: 4px; left: 6px; font-size: 10px;
    font-family: monospace; color: #cde; background: rgba(0,0,0,0.5);
    padding: 1px 4px; border-radius: 3px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_ab_grid_toggle_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/js/app.js web/css/main.css tests/web/test_ab_grid_toggle_source.py
git commit -m "feat(web): A/B grid toggle + layout"
```

---

## Task 3: Regression sweep + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Python suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (E2E skips without a server). No Phase 1-4 regressions.

- [ ] **Step 2: Live smoke (start server, drive browser)**

Start the UI (`python -m cedartoy.cli ui`). With a headless Playwright script against `D:\MusiCue\exports\hair dye`: load project → select a reactive shader (e.g. one of `shaders/*_reactive.glsl`) → click Validate → click A/B → wait for the grid → for each of the four canvases read a center-pixel sample via `canvas.getContext('webgl2')` is not directly readable, so instead assert structurally: `document.querySelectorAll('ab-grid canvas').length === 4`, `getComputedStyle(document.querySelector('.ab-grid')).display === 'grid'`, and that the single `#preview-canvas` is hidden. Then seek to a kick-active time and confirm no JS console errors. (Pixel-diffing 4 WebGL canvases is brittle headless; structural + no-error is the practical bar, consistent with the repo's Playwright tests.)

- [ ] **Step 3: Stop server, record results, commit any fix**

Stop the UI server. No code change expected; commit any fix surfaced.

---

## Self-Review

**Spec coverage (Phase 5 of `2026-05-22-track-reactivity-validation-design.md`):**
- §5.7 A/B comparison grid: synced raw / cued / blend / no-audio, same shader + playhead → Tasks 1-2. raw/cued/blend share masked uniforms (isolating the texture difference); no-audio is the zeroed baseline.

**Placeholder scan:** No TBD/TODO. Component code complete. Verification is source-assertion + structural Playwright + no-console-error (pixel-diffing 4 headless WebGL canvases is brittle — the structural bar matches the repo's existing Playwright approach; stated, not a gap).

**Type/contract consistency:** `ab-grid` reuses `composeRow0FromValues(bandValues, sectionEnergy)`, `composeRow1(frameData,f)`, `composeUniforms(frameData,f,eff)`, `applySettingsSeries(raw,setting)`, `effectiveSettings(ts,solo)` with the exact signatures from Phase 2/4 — no new composition logic, so the grid's cued panel matches the main preview by construction. `ShaderRenderer` API (`compileShader`/`updateAudioData`/`updateBundleUniforms`/`currentTime`/`render`) used as in `preview-panel.js`. `setActive(bool)` is the only new public method, called from the Phase-5 toggle.

**Carry-over note:** the grid recompiles the shader into 4 contexts on activation/`shader-select`; it stays idle (no per-frame work) while `ab-mode` is off, so it has zero cost in normal Validate use. Blend factor is fixed at 0.5 (a comparison constant, not a tunable) — intentional scope limit.
