# Plan D — Output grid + stage helpers + tooltips

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Output panel as a 2×2 grouped grid (Geometry / Time / Quality / File) with a pinned estimate, and add a consistent "what is this stage for" helper bar at the top of every stage. Add tooltips to every output input.

**Architecture:** A new `<stage-helper title subtitle>` custom element renders a compact bar with bold title + secondary subtitle text. It's placed in `index.html` as a sibling above each stage panel — keeps helper text out of panel-internal logic. `output-panel.js` is rewritten to render its fields in a 2×2 CSS grid (`.output-grid` with four `.output-card` children), each card grouping a single concern. The render estimate stays pinned at the bottom. Every input gets a `title=""` tooltip describing its effect. No backend changes.

**Tech Stack:** Vanilla JS custom elements, CSS Grid, native `title=` tooltips.

**Spec:** `docs/superpowers/specs/2026-05-16-cedartoy-ux-sync-pass.md` §§ 7.4 (output grid layout), 7.6 (stage-helper), 11 (Plan D).

---

## File structure

```
Web (web/js/components/)
├── stage-helper.js               [new]   <stage-helper title subtitle>
├── output-panel.js               [rewrite] 2x2 grouped grid; tooltips on every input

Web (web/index.html)
├── index.html                    [modify] insert <stage-helper> in each of the 4 stage panels;
│                                          bump app.js cache-bust
└── web/js/app.js                 [modify] import stage-helper; bump output-panel cache-bust

Web (web/css/components.css)
└── components.css                [modify] .stage-helper, .output-grid, .output-card,
                                           .output-row, .output-estimate styles
```

`<stage-helper>` and `<output-panel>` know nothing about each other — they're both inert renderers driven by attributes/config. The 4 stages each get their own `<stage-helper>` instance with their own copy text; no shared registry, no event coupling. Easy to relocate, easy to delete one.

---

## Task 1 — `<stage-helper>` component

**Repo:** `D:\cedartoy`

**Files:**
- Create: `web/js/components/stage-helper.js`

- [ ] **Step 1: Write the component**

Create `web/js/components/stage-helper.js` with:

```javascript
/**
 * <stage-helper title="…" subtitle="…">
 *
 * Compact top-of-stage bar telling the user what this stage is for.
 * Title is bold; subtitle is dimmer secondary text. Use the same shape
 * on every stage so the user has a stable place to look for guidance.
 */
class StageHelper extends HTMLElement {
    static get observedAttributes() {
        return ['title', 'subtitle'];
    }

    connectedCallback() {
        this.render();
    }

    attributeChangedCallback() {
        if (this.isConnected) this.render();
    }

    render() {
        const title = this.getAttribute('title') || '';
        const subtitle = this.getAttribute('subtitle') || '';
        this.innerHTML = `
            <div class="stage-helper">
                <strong>${this._escape(title)}</strong>
                <span>${this._escape(subtitle)}</span>
            </div>
        `;
    }

    _escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }
}

customElements.define('stage-helper', StageHelper);
```

- [ ] **Step 2: Commit**

```bash
git -C D:/cedartoy add web/js/components/stage-helper.js
git -C D:/cedartoy commit -m "feat(stage-helper): new custom element for per-stage helper bars"
```

---

## Task 2 — Wire `<stage-helper>` into all four stages

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/index.html`
- Modify: `web/js/app.js`

- [ ] **Step 1: Replace the stage-panels block in `web/index.html`**

Open `web/index.html`. Find:

```html
            <section class="config-editor-panel">
                <div id="stage-panels">
                    <div data-stage="project"><project-panel></project-panel></div>
                    <div data-stage="shader" hidden><config-editor></config-editor></div>
                    <div data-stage="output" hidden><output-panel></output-panel></div>
                    <div data-stage="render" hidden>
                        <div style="padding: 16px; color: #aaa;">
                            Use the Render panel at the bottom of the page to start your render.
                        </div>
                    </div>
                </div>
            </section>
```

Replace with:

```html
            <section class="config-editor-panel">
                <div id="stage-panels">
                    <div data-stage="project">
                        <stage-helper
                            title="Stage 1 · Project"
                            subtitle="Load a folder produced by MusiCue's Send to CedarToy. CedarToy reads the bundle, links audio, and shows you what's inside before you commit to a render."></stage-helper>
                        <project-panel></project-panel>
                    </div>
                    <div data-stage="shader" hidden>
                        <stage-helper
                            title="Stage 2 · Shader"
                            subtitle="Pick a shader from the rail. Make this shader reactive ▸ copies a Claude-ready prompt that retrofits MusiCue uniforms (iBpm, iBeat, iEnergy…) onto it."></stage-helper>
                        <config-editor></config-editor>
                    </div>
                    <div data-stage="output" hidden>
                        <stage-helper
                            title="Stage 3 · Output"
                            subtitle="Pick a preset, set duration, glance at the estimate. The estimate sharpens after each real render of this shader."></stage-helper>
                        <output-panel></output-panel>
                    </div>
                    <div data-stage="render" hidden>
                        <stage-helper
                            title="Stage 4 · Render"
                            subtitle="Start Render below. Progress streams over WebSocket; completed renders list every emitted frame."></stage-helper>
                        <div style="padding: 16px; color: #aaa;">
                            Use the Render panel at the bottom of the page to start your render.
                        </div>
                    </div>
                </div>
            </section>
```

- [ ] **Step 2: Import the stage-helper module**

Open `web/js/app.js`. Find the block of component imports near the top. After:

```javascript
import './components/stage-rail.js?v=1';
```

add:

```javascript
import './components/stage-helper.js?v=1';
```

- [ ] **Step 3: Bump app.js cache-bust**

In `web/index.html`, change:

```html
<script type="module" src="/js/app.js?v=6"></script>
```

to:

```html
<script type="module" src="/js/app.js?v=7"></script>
```

- [ ] **Step 4: Commit**

```bash
git -C D:/cedartoy add web/index.html web/js/app.js
git -C D:/cedartoy commit -m "feat(ui): add stage-helper bar to all four stages

Each stage gets one <stage-helper title subtitle> placed as a sibling
above its content panel. Same shape, same place, on every stage so
the user has a stable place to look for guidance."
```

---

## Task 3 — Rewrite `<output-panel>` as 2×2 grid with tooltips

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/output-panel.js`
- Modify: `web/js/app.js`

- [ ] **Step 1: Replace the file**

Replace the entire contents of `web/js/components/output-panel.js` with:

```javascript
class OutputPanel extends HTMLElement {
    constructor() {
        super();
        this.config = {};
    }

    connectedCallback() {
        // Seed from config-editor's persisted config so the fields show prior values.
        const ce = document.querySelector('config-editor');
        if (ce && ce.config) {
            this.config = { ...ce.config };
        }
        document.addEventListener('config-change', (e) => {
            this.config = { ...e.detail };
            this._syncFields();
            this._refreshEstimate();
        });
        this.render();
        this.attachEventListeners();
        this._refreshEstimate();
    }

    async _refreshEstimate() {
        if (this._estimateTimer) clearTimeout(this._estimateTimer);
        this._estimateTimer = setTimeout(async () => {
            const cfg = this.config;
            const out = this.querySelector('#render-estimate');
            if (!out) return;
            if (!cfg.shader || !cfg.width || !cfg.height || !cfg.fps) {
                out.textContent = 'Estimate: pick a shader and resolution.';
                return;
            }
            const basename = (cfg.shader.split(/[\\/]/).pop() || '').replace(/\.glsl$/, '');
            const body = {
                shader_basename: basename,
                width: cfg.width, height: cfg.height,
                fps: cfg.fps, duration_sec: cfg.duration_sec || 10,
                tile_count: (cfg.tiles_x || 1) * (cfg.tiles_y || 1),
                ss_scale: cfg.ss_scale || 1.0,
                format: cfg.default_output_format || 'png',
                bit_depth: this._bitDepthInt(cfg.default_bit_depth),
            };
            try {
                const r = await fetch('/api/render/estimate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!r.ok) {
                    const detail = await r.json().catch(() => ({}));
                    throw new Error(detail.detail || `HTTP ${r.status}`);
                }
                this._renderEstimate(await r.json());
            } catch (err) {
                out.textContent = `Estimate failed: ${err.message}`;
            }
        }, 250);
    }

    _bitDepthInt(s) {
        if (s === '16f') return 16;
        if (s === '32f') return 32;
        return 8;
    }

    _renderEstimate(e) {
        const out = this.querySelector('#render-estimate');
        if (!out) return;
        const dt = (e.total_seconds / 60).toFixed(1);
        const sz = (e.output_bytes / (1024 ** 3)).toFixed(1);
        const hint = e.history_hit ? '' : ' (no prior render data)';
        const warn = (e.exceeds_time_threshold_1h || e.exceeds_size_threshold_50gb)
            ? ' ⚠ over budget' : '';
        out.innerHTML =
            `Estimate: ${e.frame_time_sec.toFixed(1)} s/frame · ` +
            `${e.total_frames} frames · ~${dt} min · ${sz} GB${warn}` +
            `<span style="color:#666;">${hint}</span>`;
    }

    render() {
        const preset = this.config.camera_mode || 'equirect';
        const bitDepth = String(this.config.default_bit_depth || '8');
        this.innerHTML = `
            <div class="output-panel">
                <div class="output-grid">

                    <div class="output-card">
                        <div class="output-card-title">Geometry</div>
                        <div class="output-row">
                            <label title="Spherical output unwraps the shader onto a 2:1 rectangle for VR / dome. Flat 16:9 is a quick preview only.">Preset</label>
                            <select id="output-preset" title="Spherical presets (equirect / LL180) are the production-quality options for CedarToy.">
                                <option value="equirect" ${preset==='equirect'?'selected':''}>Equirectangular 2:1</option>
                                <option value="ll180" ${preset==='ll180'?'selected':''}>LL180 dome</option>
                                <option value="2d" ${preset==='2d'?'selected':''}>Flat 16:9 (preview)</option>
                            </select>
                            <button class="btn btn-secondary" id="apply-preset"
                                    style="padding:2px 8px;font-size:11px;"
                                    title="Apply this preset's recommended resolution (e.g. 8192×4096 for equirect).">Apply preset</button>
                        </div>
                        <div class="output-row">
                            <label title="Output resolution in pixels. Equirect → 8192×4096 is a common stage; LL180 → 4096×4096.">Resolution</label>
                            <input id="out-width" type="number" value="${this.config.width||1920}" min="64" max="32768" title="Width in pixels.">
                            <span style="color:#666;">×</span>
                            <input id="out-height" type="number" value="${this.config.height||1080}" min="64" max="32768" title="Height in pixels.">
                        </div>
                        <div class="output-row">
                            <label title="Camera tilt for spherical projection, in degrees. 0° = horizon centered.">Tilt</label>
                            <input id="out-tilt" type="number" min="0" max="90" value="${this.config.camera_tilt_deg||0}" title="Camera tilt in degrees (0–90).">
                            <span style="color:#666;">°</span>
                        </div>
                    </div>

                    <div class="output-card">
                        <div class="output-card-title">Time</div>
                        <div class="output-row">
                            <label title="Frames per second. 60 is common for smooth motion; 24 for cinematic feel.">FPS</label>
                            <input id="out-fps" type="number" value="${this.config.fps||60}" min="1" max="240" title="Frames per second.">
                        </div>
                        <div class="output-row">
                            <label title="Render duration in seconds. Total frames = FPS × Duration.">Duration</label>
                            <input id="out-duration" type="number" step="0.1" value="${this.config.duration_sec||10}" min="0.05" title="Render duration in seconds.">
                            <span style="color:#666;">s</span>
                        </div>
                    </div>

                    <div class="output-card">
                        <div class="output-card-title">Quality</div>
                        <div class="output-row">
                            <label title="Render each pixel at N× resolution then downsample. 2 quadruples render cost but greatly reduces aliasing.">Supersample</label>
                            <input id="out-ss" type="number" min="1" max="4" step="0.5" value="${this.config.ss_scale||1.0}" title="Supersampling scale (1 = off, 2 = 4× cost).">
                        </div>
                        <div class="output-row">
                            <label title="Number of sub-frames per output frame (motion blur). ≥ 2 enables motion blur; cost scales linearly.">Temporal</label>
                            <input id="out-temporal" type="number" min="1" max="64" value="${this.config.temporal_samples||1}" title="Temporal samples per frame (1 = off, ≥ 2 = motion blur).">
                        </div>
                        <div class="output-row">
                            <label title="Shutter angle 0–1. Only used when Temporal ≥ 2. 0.5 = 180° shutter (filmic default).">Shutter</label>
                            <input id="out-shutter" type="number" min="0" max="1" step="0.1" value="${this.config.shutter ?? 0.5}" title="Shutter angle (0–1). Used with Temporal ≥ 2.">
                        </div>
                        <div class="output-row">
                            <label title="Split rendering into tiles to fit huge frames in GPU memory. Total frames in the job = tiles_x × tiles_y × time_frames.">Tiling</label>
                            <input id="out-tiles-x" type="number" min="1" max="64" value="${this.config.tiles_x||1}" title="Horizontal tiles.">
                            <span style="color:#666;">×</span>
                            <input id="out-tiles-y" type="number" min="1" max="64" value="${this.config.tiles_y||1}" title="Vertical tiles.">
                        </div>
                    </div>

                    <div class="output-card">
                        <div class="output-card-title">File</div>
                        <div class="output-row">
                            <label title="Output image format. PNG is lossless 8-bit/16-bit; EXR carries 16- or 32-bit float for HDR pipelines.">Format</label>
                            <select id="out-format" title="PNG for delivery; EXR for HDR / compositing.">
                                <option value="png" ${this.config.default_output_format==='png'?'selected':''}>PNG</option>
                                <option value="exr" ${this.config.default_output_format==='exr'?'selected':''}>EXR</option>
                            </select>
                        </div>
                        <div class="output-row">
                            <label title="Color depth per channel. 8-bit suits PNG; 16-bit / 32-bit float require EXR.">Bit depth</label>
                            <select id="out-bit-depth" title="8-bit (PNG) / 16-bit float (EXR) / 32-bit float (EXR).">
                                <option value="8" ${bitDepth==='8'?'selected':''}>8-bit</option>
                                <option value="16f" ${bitDepth==='16f'?'selected':''}>16-bit float</option>
                                <option value="32f" ${bitDepth==='32f'?'selected':''}>32-bit float</option>
                            </select>
                        </div>
                    </div>

                </div>

                <div id="render-estimate" class="output-estimate">Estimate: pick a shader and resolution.</div>
            </div>
        `;
    }

    _syncFields() {
        // Update displayed values without rerendering (preserves focus).
        const set = (sel, val) => {
            const el = this.querySelector(sel);
            if (el && el.value != val) el.value = val;
        };
        set('#out-width', this.config.width || 1920);
        set('#out-height', this.config.height || 1080);
        set('#out-fps', this.config.fps || 60);
        set('#out-duration', this.config.duration_sec || 10);
        set('#out-tiles-x', this.config.tiles_x || 1);
        set('#out-tiles-y', this.config.tiles_y || 1);
        set('#out-tilt', this.config.camera_tilt_deg || 0);
        set('#out-ss', this.config.ss_scale || 1.0);
        set('#out-temporal', this.config.temporal_samples || 1);
        set('#out-shutter', this.config.shutter ?? 0.5);
        set('#out-format', this.config.default_output_format || 'png');
        set('#out-bit-depth', String(this.config.default_bit_depth || '8'));
        set('#output-preset', this.config.camera_mode || 'equirect');
    }

    attachEventListeners() {
        this.querySelector('#apply-preset')?.addEventListener('click', () => {
            const p = this.querySelector('#output-preset').value;
            const w = this.querySelector('#out-width');
            const h = this.querySelector('#out-height');
            if (p === 'equirect') { w.value = 8192; h.value = 4096; }
            else if (p === 'll180') { w.value = 4096; h.value = 4096; }
            else if (p === '2d') { w.value = 1920; h.value = 1080; }
            this._fire();
        });
        ['#output-preset', '#out-width', '#out-height', '#out-fps',
         '#out-duration', '#out-tiles-x', '#out-tiles-y', '#out-tilt',
         '#out-ss', '#out-temporal', '#out-shutter',
         '#out-format', '#out-bit-depth'].forEach(sel => {
            this.querySelector(sel)?.addEventListener('change', () => this._fire());
        });
    }

    _fire() {
        this._refreshEstimate();
        const update = {
            camera_mode: this.querySelector('#output-preset').value,
            width: parseInt(this.querySelector('#out-width').value),
            height: parseInt(this.querySelector('#out-height').value),
            fps: parseInt(this.querySelector('#out-fps').value),
            duration_sec: parseFloat(this.querySelector('#out-duration').value),
            tiles_x: parseInt(this.querySelector('#out-tiles-x').value),
            tiles_y: parseInt(this.querySelector('#out-tiles-y').value),
            camera_tilt_deg: parseInt(this.querySelector('#out-tilt').value),
            ss_scale: parseFloat(this.querySelector('#out-ss').value),
            temporal_samples: parseInt(this.querySelector('#out-temporal').value),
            shutter: parseFloat(this.querySelector('#out-shutter').value),
            default_output_format: this.querySelector('#out-format').value,
            default_bit_depth: this.querySelector('#out-bit-depth').value,
        };
        const ce = document.querySelector('config-editor');
        if (ce && ce.config) {
            Object.assign(ce.config, update);
            if (typeof ce.saveToLocalStorage === 'function') ce.saveToLocalStorage();
            document.dispatchEvent(new CustomEvent('config-change', { detail: ce.config }));
        } else {
            Object.assign(this.config, update);
            this.dispatchEvent(new CustomEvent('config-change', {
                detail: this.config, bubbles: true,
            }));
        }
    }
}

customElements.define('output-panel', OutputPanel);
```

Changes vs. prior:
- Removed top-level `<h3>Output</h3>` (stage-helper covers that now).
- Removed flow of `<label>` + inline `<input>` siblings; replaced with `.output-grid` → 4× `.output-card` → multiple `.output-row` per card.
- Added `title=""` tooltip to every label, select, and input.
- Renamed `#render-estimate`'s parent class to `.output-estimate` for pinned-bottom styling.

- [ ] **Step 2: Bump cache-bust**

Open `web/js/app.js`. Change:

```javascript
import './components/output-panel.js?v=2';
```

to:

```javascript
import './components/output-panel.js?v=3';
```

Then in `web/index.html` change `app.js?v=7` to `app.js?v=8`.

- [ ] **Step 3: Commit**

```bash
git -C D:/cedartoy add web/js/components/output-panel.js web/js/app.js web/index.html
git -C D:/cedartoy commit -m "refactor(output-panel): 2x2 grouped grid with tooltips

Four cards group fields by concern (Geometry / Time / Quality / File).
Every input has a title= tooltip describing what it does. Estimate
pinned at the bottom. Header text moves to <stage-helper>."
```

---

## Task 4 — CSS for stage-helper + output grid

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/css/components.css`

- [ ] **Step 1: Append the new rules**

Open `web/css/components.css`. Find the existing `/* Output panel */` block (it currently has loose styling for the old layout). Replace it with:

```css
/* Output panel — 2x2 grid by concern */
.output-panel { padding: 12px; }
.output-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}
.output-card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    padding: 10px;
}
.output-card-title {
    font-size: 10px;
    color: #888;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.output-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
    font-size: 12px;
}
.output-row:last-child { margin-bottom: 0; }
.output-row label {
    flex: 0 0 92px;
    color: #aaa;
    margin: 0;
    cursor: help;
}
.output-row input[type="number"],
.output-row select {
    background: #0f0f0f;
    color: #eee;
    border: 1px solid #2a2a2a;
    border-radius: 3px;
    padding: 3px 6px;
    font-size: 12px;
    max-width: 100px;
}
.output-row select { max-width: 160px; }
.output-estimate {
    margin-top: 12px;
    padding: 8px 10px;
    background: #2a2a1a;
    border-radius: 4px;
    font-family: monospace;
    font-size: 12px;
    color: #cca;
}

/* Stage helper bar */
stage-helper { display: block; }
.stage-helper {
    background: #1a2a3a;
    padding: 8px 14px;
    border-radius: 3px;
    margin: 0 12px 8px 12px;
    font-size: 12px;
    color: #cce;
    line-height: 1.5;
}
.stage-helper strong {
    color: #fff;
    margin-right: 10px;
}
.stage-helper span {
    color: #889;
}
```

This **replaces** the old `.output-panel` block in the file (the one with loose `label`/`input` rules that no longer applies). Search for the existing `/* Output panel */` comment and replace through to the next top-level comment.

- [ ] **Step 2: Commit**

```bash
git -C D:/cedartoy add web/css/components.css
git -C D:/cedartoy commit -m "style(ui): output-panel grid + stage-helper bar styling

Replaces the old loose label/input flow with a 2x2 grid layout
(.output-grid → .output-card → .output-row). Adds .stage-helper for
the per-stage title + subtitle bar."
```

---

## Task 5 — Browser smoke + push

**Repo:** `D:\cedartoy`

- [ ] **Step 1: Manual browser smoke test**

If not running, start the UI:

```bash
python -m cedartoy.cli ui
```

Open `http://localhost:8080` (hard-reload with Ctrl+Shift+R or use a fresh query string like `?cb=plan-d`). Verify:

- Stage 1 (Project) shows a helper bar at top: **Stage 1 · Project** + subtitle about loading a MusiCue folder.
- Click stage rail "2. Shader" → helper bar updates to **Stage 2 · Shader** + subtitle about reactive shaders.
- Click "3. Output" → helper bar shows **Stage 3 · Output**, content below renders as **four cards in a 2×2 grid** with Geometry / Time / Quality / File headers, fields inside each.
- Hover any output input/label → tooltip appears with a real description (e.g. "Number of sub-frames per output frame (motion blur)…").
- Hit "Apply preset" with Equirectangular selected → resolution fills to 8192×4096; estimate updates.
- Click "4. Render" → helper bar shows **Stage 4 · Render** + subtitle.
- All four stage panels switch cleanly when clicking the rail.

If anything looks off (overlap, missing helper, broken grid), iterate on the CSS in Task 4 and bump the cache-bust again.

- [ ] **Step 2: Push**

```bash
git -C D:/cedartoy push origin main
```

Expected: push succeeds.

---

## Self-review checklist

- [x] **Spec coverage:**
  - § 7.4 `<output-panel>` rewrite — 2×2 grid, pinned estimate, tooltips → Tasks 3, 4.
  - § 7.6 `<stage-helper>` new custom element → Task 1.
  - § 11 Plan D scope — output grid + stage-helper + tooltips → this plan.
- [x] **Placeholder scan:** every step contains literal code or shell commands.
- [x] **Type consistency:** `<stage-helper>` attribute names (`title`, `subtitle`) match between component (T1), index.html (T2), and CSS (T4). Output card class names (`.output-grid`, `.output-card`, `.output-card-title`, `.output-row`, `.output-estimate`) consistent between output-panel.js (T3) and components.css (T4).
- [x] **Scope:** 5 tasks, single repo, ~30 min. Layout-only — no backend, no new state.
