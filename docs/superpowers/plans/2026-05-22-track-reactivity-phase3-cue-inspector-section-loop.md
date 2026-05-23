# Track Reactivity — Phase 3: Cue Inspector + Section Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A playhead **cue inspector** showing the masked values actually driving the shader (section, bar/beat, the six uniforms, per-track effective values, bundle mode), plus a **section loop** that repeats the section under the playhead for fast verification of key moments.

**Architecture:** The preview already composes masked uniforms + per-track values each frame (Phase 2). It now also emits a `cue-frame` event carrying that masked snapshot; `<cue-inspector>` is a pure view of it. Section loop lives in `transport-strip` (which owns the bundle's section boundaries): a `loop-toggle` event sets/clears a loop region around the current section, the RAF tick wraps playback at the region end, and `loop-region-change` lets the UI reflect state.

**Tech Stack:** Vanilla JS ES modules + Web Components, FastAPI, pytest, Playwright (Python sync API).

---

## Background facts (read before starting)

- **Test project with real drums:** `D:\MusiCue\exports\hair dye` (audio `song.wav` + sibling `song.musicue.json`, schema 1.1, drums: kick 84 / hat 94 / snare 7, duration 138.2s). Use this for manual smoke and the E2E `PROJECT`. (The `audio_data/Neon Queens` sample has empty drums.)
- **Preview composition (Phase 2, `web/js/components/preview-panel.js`):** `_composeAndRender(t)` computes `f = round(t * this._timelineFps)`, `composeRow0/Row1`, and `composeUniforms(tl.frame_data, f, this._effSettings)`; `this._timeline` is the `/api/reactivity/track-timeline` payload (has `frame_data.tracks[trackId][f]`, `frame_data.uniforms.{bpm,beat,bar,sectionEnergy,sectionId,energy}[f]`, and `tracks.sections.blocks[]` with `{start,end,label,energyRank}`). `this._effSettings` is the effective per-track settings (post solo/mute).
- **`applySetting`** is exported from `web/js/webgl/cue-compose.js` — reuse it for per-track effective values; do not reimplement.
- **Transport (`web/js/components/transport-strip.js`):** `_tick()` (line 153) runs each RAF during play and calls `_emitCurrentFrame()`; `_seek(t)` (line 141) clamps + sets `this.audio.currentTime`; `this.bundle.sections` carry `{start,end,label,...}`; `_jumpSection(dir)` (line 47) already finds sections by time. `transport-strip.js` carries pre-existing WIP — snapshot it before editing (Task 3 Step 0).
- **Validate-mode layout (Phase 2, `web/css/main.css`):** `body.validate-mode` hides edit panels and expands the preview column (`.preview-panel-wrapper`). Components are imported in `web/js/app.js`; elements are placed in `web/index.html` inside `.preview-panel-wrapper`.
- **No JS unit runner** — verify via source-assertion tests (`tests/web/`) + the Playwright E2E. Composition parity is already locked by `tests/test_tracks.py`.

---

## Task 1: Preview emits a `cue-frame` snapshot each composed frame

**Files:**
- Modify: `web/js/components/preview-panel.js`
- Test: `tests/web/test_cue_frame_emit_source.py` (create)

`cue-frame` detail: `{ frame, timeSec, uniforms, trackValues, sectionLabel, bundleMode }` where `uniforms` is the masked `composeUniforms` output, `trackValues[trackId]` is the per-track effective scalar (`applySetting(raw, eff)`), `sectionLabel` is the block label containing `timeSec`, and `bundleMode` is `'cued'` (timeline present) or `'free'`.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_cue_frame_emit_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/preview-panel.js"


def test_preview_emits_cue_frame():
    s = SRC.read_text(encoding="utf-8")
    assert "cue-frame" in s                       # event name
    assert "trackValues" in s                     # per-track effective values
    assert "sectionLabel" in s                    # section label lookup
    assert "bundleMode" in s                      # cued vs free
    assert "applySetting" in s                    # reuses cue-compose, no reimpl
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_cue_frame_emit_source.py -v`
Expected: FAIL — `cue-frame` not present.

- [ ] **Step 3: Write minimal implementation**

In `web/js/components/preview-panel.js`, update the import to also pull `applySetting`:

```javascript
import { composeRow0, composeRow1, composeUniforms, effectiveSettings, applySetting }
    from '../webgl/cue-compose.js';
```

At the end of `_composeAndRender(t)` (after `this.renderer.render();`), emit the snapshot:

```javascript
        this._emitCueFrame(f, t);
```

Add the helper next to `_composeAndRender`:

```javascript
    _emitCueFrame(f, t) {
        const tl = this._timeline;
        const fd = tl.frame_data;
        const trackValues = {};
        for (const tid of Object.keys(fd.tracks)) {
            trackValues[tid] = applySetting(fd.tracks[tid][f], this._effSettings[tid]);
        }
        let sectionLabel = '—';
        const blocks = (tl.tracks.sections && tl.tracks.sections.blocks) || [];
        for (const b of blocks) {
            if (b.start <= t && t < b.end) { sectionLabel = b.label || '—'; break; }
        }
        document.dispatchEvent(new CustomEvent('cue-frame', { detail: {
            frame: f, timeSec: t, sectionLabel, bundleMode: 'cued',
            uniforms: composeUniforms(fd, f, this._effSettings),
            trackValues,
        }}));
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_cue_frame_emit_source.py tests/web/test_preview_compose_source.py tests/web/test_preview_timeline_mode.py -v`
Expected: PASS (new test + the two existing preview tests still green).

- [ ] **Step 5: Commit**

```bash
git add web/js/components/preview-panel.js tests/web/test_cue_frame_emit_source.py
git commit -m "feat(web): preview emits cue-frame snapshot (masked values)"
```

---

## Task 2: `<cue-inspector>` component + loop button

**Files:**
- Create: `web/js/components/cue-inspector.js`
- Modify: `web/index.html` (mount), `web/js/app.js` (import), `web/css/main.css` (styles)
- Test: `tests/web/test_cue_inspector_source.py` (create)

Renders the `cue-frame` snapshot and hosts a "🔁 Loop section" button that dispatches `loop-toggle`; reflects loop state from `loop-region-change`.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_cue_inspector_source.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web/js/components/cue-inspector.js"


def test_cue_inspector_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('cue-inspector'" in s
    assert "cue-frame" in s                       # consumes preview snapshot
    assert "loop-toggle" in s                     # dispatches loop request
    assert "loop-region-change" in s              # reflects loop state
    # shows the six uniforms + section + per-track values
    assert "iBpm" in s and "iEnergy" in s and "iSectionId" in s
    assert "trackValues" in s


def test_cue_inspector_mounted_and_imported():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "<cue-inspector>" in html
    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "cue-inspector.js" in appjs
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "cue-inspector" in css
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_cue_inspector_source.py -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `web/js/components/cue-inspector.js`:

```javascript
/**
 * <cue-inspector> — playhead debug stack for Validate mode. Pure view of the
 * preview's 'cue-frame' event (masked values actually driving the shader).
 * Hosts a section-loop toggle that delegates to transport-strip.
 */
class CueInspector extends HTMLElement {
    constructor() {
        super();
        this._looping = false;
    }

    connectedCallback() {
        this.render();
        document.addEventListener('cue-frame', (e) => this._onFrame(e.detail));
        document.addEventListener('loop-region-change', (e) =>
            this._setLoopState(!!e.detail));
        this.querySelector('#ci-loop').addEventListener('click', () =>
            document.dispatchEvent(new CustomEvent('loop-toggle')));
    }

    render() {
        this.innerHTML = `<div class="cue-inspector">
            <div class="ci-row ci-head">
                <span id="ci-section" class="ci-section">section —</span>
                <span id="ci-mode" class="ci-mode">—</span>
                <button id="ci-loop" class="btn btn-secondary ci-loop">🔁 Loop section</button>
            </div>
            <div id="ci-uniforms" class="ci-row ci-uniforms"></div>
            <div id="ci-tracks" class="ci-row ci-tracks"></div>
        </div>`;
    }

    _onFrame(d) {
        const u = d.uniforms || {};
        this.querySelector('#ci-section').textContent =
            `section ${d.sectionLabel} · bar ${u.bar} · beat ${(u.beat || 0).toFixed(2)}`;
        this.querySelector('#ci-mode').textContent = `mode ${d.bundleMode}`;
        this.querySelector('#ci-uniforms').textContent =
            `iBpm ${(u.bpm || 0).toFixed(0)} · iBeat ${(u.beat || 0).toFixed(2)} · ` +
            `iBar ${u.bar} · iSectionId ${u.sectionId} · ` +
            `iSectionEnergy ${(u.sectionEnergy || 0).toFixed(2)} · iEnergy ${(u.energy || 0).toFixed(2)}`;
        const tv = d.trackValues || {};
        this.querySelector('#ci-tracks').innerHTML = Object.keys(tv).map((k) => {
            const v = tv[k];
            const on = v > 0.001 ? ' ci-on' : '';
            return `<span class="ci-track${on}">${k.split('.').pop()} ${v.toFixed(2)}</span>`;
        }).join('');
    }

    _setLoopState(on) {
        this._looping = on;
        const btn = this.querySelector('#ci-loop');
        btn.classList.toggle('btn-primary', on);
        btn.textContent = on ? '🔁 Looping (clear)' : '🔁 Loop section';
    }
}

customElements.define('cue-inspector', CueInspector);
```

In `web/index.html`, mount it after `<track-timeline></track-timeline>`:

```html
                <cue-inspector></cue-inspector>
```

In `web/js/app.js`, add the import after the track-timeline import:

```javascript
import './components/cue-inspector.js?v=1';
```

In `web/css/main.css`, append:

```css
.cue-inspector { display: none; font-family: monospace; font-size: 11px;
    color: #9ab; padding: 6px 8px; gap: 4px; }
body.validate-mode .cue-inspector { display: flex; flex-direction: column; }
.cue-inspector .ci-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.cue-inspector .ci-section { color: #cde; font-weight: bold; }
.cue-inspector .ci-mode { color: #778; }
.cue-inspector .ci-loop { margin-left: auto; font-size: 11px; padding: 2px 8px; }
.cue-inspector .ci-track { color: #556; }
.cue-inspector .ci-track.ci-on { color: #7ec97e; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_cue_inspector_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/cue-inspector.js web/index.html web/js/app.js web/css/main.css tests/web/test_cue_inspector_source.py
git commit -m "feat(web): cue-inspector playhead debug stack + loop button"
```

---

## Task 3: Section loop in transport-strip

**Files:**
- Modify: `web/js/components/transport-strip.js`
- Test: `tests/web/test_section_loop_source.py` (create)

`loop-toggle` sets the loop region to the section containing the playhead (or clears it); `_tick()` wraps `audio.currentTime` to the region start at the end; `loop-region-change` reports the region (or `null`).

- [ ] **Step 0: Snapshot pre-existing WIP (avoid contaminating feature commits)**

Run: `git status --short web/js/components/transport-strip.js`
If it shows ` M`, snapshot it first:

```bash
git add web/js/components/transport-strip.js
git commit -m "chore(wip): snapshot pre-existing transport-strip edits"
```

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_section_loop_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/transport-strip.js"


def test_transport_section_loop_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "loop-toggle" in s                     # listens for the toggle
    assert "loop-region-change" in s              # reports loop state
    assert "_loopRegion" in s                     # holds the region
    # tick wraps playback at region end
    assert "currentTime" in s and ".end" in s and ".start" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_section_loop_source.py -v`
Expected: FAIL — `loop-toggle` not present.

- [ ] **Step 3: Write minimal implementation**

In `web/js/components/transport-strip.js` constructor, add:

```javascript
        this._loopRegion = null;     // { start, end } in seconds, or null
```

In `connectedCallback`, add the listener (after the `transport-seek` listener):

```javascript
        document.addEventListener('loop-toggle', () => this._toggleLoop());
```

Add the two methods (e.g. after `_jumpSection`):

```javascript
    _toggleLoop() {
        if (this._loopRegion) {
            this._loopRegion = null;
        } else if (this.audio && this.bundle?.sections?.length) {
            const t = this.audio.currentTime;
            const sec = this.bundle.sections.find((s) => s.start <= t && t < s.end)
                || this.bundle.sections[0];
            this._loopRegion = { start: sec.start, end: sec.end };
        }
        document.dispatchEvent(new CustomEvent('loop-region-change',
            { detail: this._loopRegion }));
    }
```

In `_tick()`, wrap before emitting (so the wrapped time is what gets reported):

```javascript
    _tick() {
        if (this._loopRegion && this.audio
            && this.audio.currentTime >= this._loopRegion.end) {
            this.audio.currentTime = this._loopRegion.start;
        }
        this._emitAudioData();
        this._emitCurrentFrame();
    }
```

Clear the loop on project change — in `_onProjectLoaded`, after `this.bundle = null;`, add:

```javascript
        this._loopRegion = null;
        document.dispatchEvent(new CustomEvent('loop-region-change', { detail: null }));
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_section_loop_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/transport-strip.js tests/web/test_section_loop_source.py
git commit -m "feat(web): section loop in transport-strip"
```

---

## Task 4: Regression sweep + manual smoke (hair dye)

**Files:**
- Modify: `tests/web/test_validate_mode_e2e.py` (point `PROJECT` at the drums project)

- [ ] **Step 1: Point the E2E at the drums-bearing project**

In `tests/web/test_validate_mode_e2e.py`, set:

```python
PROJECT = r"D:\MusiCue\exports\hair dye"
```

- [ ] **Step 2: Full Python suite**

Run: `python -m pytest tests/ -q`
Expected: PASS; the E2E SKIPs unless a UI server is live on :8080.

- [ ] **Step 3: Manual smoke (operator)**

Start the UI, load `D:\MusiCue\exports\hair dye`, click **Validate**, then confirm:
- track lanes show real kick/hat/snare onsets (not "no data");
- the cue inspector updates section / bar / beat / the six uniforms / per-track values while playing;
- muting `drums.kick` drops its inspector value to 0.00 and visibly changes the preview;
- "🔁 Loop section" repeats the current section and the button reflects looping state; clicking again clears it.

- [ ] **Step 4: Commit**

```bash
git add tests/web/test_validate_mode_e2e.py
git commit -m "test(web): point validate E2E at drums-bearing project"
```

---

## Self-Review

**Spec coverage (Phase 3 scope of `2026-05-22-track-reactivity-validation-design.md`):**
- §5.3 cue inspector (section, bar/beat, per-track values, actual uniform values, bundle mode) → Tasks 1-2. Shows **masked** values (post mute/solo) because it consumes the preview's composed `cue-frame`.
- §5.5 section loop (loop the section under the playhead) → Tasks 2 (button) + 3 (transport logic).

**Placeholder scan:** No TBD/TODO. Every code step is complete. JS verification is source-assertion + Playwright + manual smoke (no JS unit runner — stated in Background, not a gap). Task 3 Step 0 is a conditional WIP-snapshot guard, concrete.

**Type/contract consistency:** `cue-frame` detail `{frame, timeSec, sectionLabel, bundleMode, uniforms, trackValues}` emitted in Task 1, consumed identically in Task 2. `loop-toggle` (no detail) dispatched in Task 2, handled in Task 3. `loop-region-change` detail is `{start, end}` or `null`, emitted in Task 3, consumed in Task 2 (`!!e.detail`). `applySetting(raw, setting)` reused from cue-compose.js (Phase 2) — same signature. Uniform keys (`bpm/beat/bar/sectionEnergy/sectionId/energy`) match `composeUniforms` output from Phase 2.

**Carry-over note:** the cue inspector only updates while the preview composes (i.e., a bundle/timeline is loaded and the transport is playing in Validate mode). With no timeline it stays at defaults — acceptable for Phase 3, since Validate mode requires a loaded project.
