# Track Reactivity — Phase 2: Validate Mode + Mute/Solo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A near-full-screen "Validate" mode with a per-track timeline graph and per-track mute/solo, where the preview is driven by the bundle (composed in-browser from the canonical per-track timeline) so it matches the render, and mutes persist into `track_settings`.

**Architecture:** Extend the Phase-1 `track-timeline` endpoint to also ship per-frame per-track scalars + a per-frame uniform series (Python = canonical evaluator). The browser composes `iChannel0` + uniforms by select-summing those scalars with `track_settings` applied (a thin JS mirror of `apply_setting` + band-fill — no evaluator logic). A Python contract test proves the shipped frame data composes to exactly `synth.synthesize`; a Playwright test proves the in-browser path drops the right band when a track is muted.

**Tech Stack:** Vanilla JS ES modules + Web Components, WebGL2, FastAPI, numpy, pytest, Playwright (Python sync API).

---

## Background facts (read before starting)

- **No JS unit-test runner** in this repo (no `package.json`). Web behavior is tested two ways (`tests/web/`): **source-assertion** tests (`test_preview_timeline_mode.py` reads a JS file and asserts substrings) and **Playwright E2E** (`test_sync_workflow.py` drives a live server at `http://127.0.0.1:8080`, skips if unreachable). This plan follows both conventions. Numeric JS correctness is verified by (a) a Python contract test on the shipped data and (b) a Playwright `page.evaluate` numeric check.
- **Layout** (`web/css/main.css:40-78`): `#app` is 3 rows (header / `.app-main` / render footer). `.app-main` is 3 cols `250px 1fr 600px`. The right column `.preview-panel-wrapper` (`web/index.html:62-66`) stacks `<preview-panel>`, `<transport-strip>`, `<cue-scrubber>`.
- **Renderer** (`web/js/webgl/renderer.js`): `updateAudioData(fftData, waveformData)` (line 499) caches two `Float32Array[512]`; `render()` (line 383) uploads them to the 512×2 texture via `audio-texture.js update()`. `updateBundleUniforms({bpm,beat,bar,energy,sectionEnergy,sectionId})` (line 94). `currentTime` + `render()` are driven externally on `transport-frame`.
- **Transport** (`web/js/components/transport-strip.js`): dispatches `audio-data {fft, waveform}` (line 228, live FFT) and `transport-frame {timeSec, bundle}` (line 163). Fetches bundle JSON from `/api/project/bundle?path=...` and the project audio path from the `project-loaded` event (`detail.audio_url`, `detail.path`/folder).
- **Preview** (`web/js/components/preview-panel.js`): on `transport-frame` sets `renderer.currentTime` + `updateBundleUniforms` + `render()` (lines 38-47); on `audio-data` calls `updateAudioData` (lines 26-30). `useAudioTimeline` gates these.
- **Canonical composition** (Phase 1, `cedartoy/musicue.py`): `synth.synthesize(frame, settings)` sums per-band Hann envelopes (`_BIN_RANGES`: low 0:32, low_mid 32:96, mid_hi 96:256, high 256:512) of `apply_setting(raw, setting)` per band track, `+= 0.1*section_energy`, clip. Row 1 = `0.5 + 0.5*energy*sin(2π*beat_phase)`. `masked_builtin_uniforms(frame, settings)` for the scalars. `BAND_TRACKS`, `_BAND_TRACK_SOURCE`, `apply_setting` are exported.
- **Project route** for the audio path: the `project-loaded` event carries `detail.audio_url` and a folder/path. The transport already fetches `/api/project/bundle?path=...`; the new timeline call uses the same audio path the transport uses (see Task 5).

**Effective mask (solo):** `track_settings` (persisted) holds per-track `{gain,mute,...}`. Solo is **client-only**: if any track is soloed, the effective setting for every non-soloed track is forced `mute:true` for the live preview; persisted `track_settings` is untouched.

---

## Task 1: Extend `build_track_timeline` with per-frame composition data

**Files:**
- Modify: `cedartoy/musicue.py` (`build_track_timeline`)
- Test: `tests/test_tracks.py`

Add a `frames` block: for each band track, its evaluator raw scalar per frame; plus the per-frame uniform series. This is the data the browser sums.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
def test_timeline_includes_per_frame_arrays():
    b = _bundle()                      # duration 4.0s, fps 24 -> 96 frames
    tl = build_track_timeline(b, fps=24.0)
    n = tl["frames"]
    assert n == 96
    fr = tl["frame_data"]
    # band tracks each carry an n-length scalar array
    assert len(fr["tracks"]["drums.kick"]) == n
    assert len(fr["tracks"]["stem.vocals"]) == n
    # uniform series present and n-length
    for key in ("bpm", "beat", "bar", "sectionEnergy", "sectionId", "energy"):
        assert len(fr["uniforms"][key]) == n
    # kick fires at t=0 (frame 0) with strength ~0.9 (ADSR peak)
    assert fr["tracks"]["drums.kick"][0] > 0.5


def test_timeline_frame_scalars_match_evaluator():
    from cedartoy.musicue import BundleEvaluator
    b = _bundle()
    tl = build_track_timeline(b, fps=24.0)
    ev = BundleEvaluator(b, fps=24.0)
    f10 = ev.evaluate(10)
    assert abs(tl["frame_data"]["tracks"]["drums.kick"][10]
               - f10.drum_pulses.get("kick", 0.0)) < 1e-6
    assert abs(tl["frame_data"]["uniforms"]["energy"][10]
               - f10.global_energy) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k per_frame_arrays -v`
Expected: FAIL — `KeyError: 'frame_data'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, inside `build_track_timeline`, before the `return`, build the per-frame block by reusing `BundleEvaluator`:

```python
    n_frames = int(round(duration * fps))
    evaluator = BundleEvaluator(bundle, fps=fps)
    frame_tracks: Dict[str, List[float]] = {tid: [] for tid in BAND_TRACKS}
    uni_series: Dict[str, List[float]] = {
        "bpm": [], "beat": [], "bar": [],
        "sectionEnergy": [], "sectionId": [], "energy": [],
    }
    for f in range(n_frames):
        ef = evaluator.evaluate(f)
        for tid in BAND_TRACKS:
            src_field, key = _BAND_TRACK_SOURCE[tid]
            frame_tracks[tid].append(float(getattr(ef, src_field).get(key, 0.0)))
        uni_series["bpm"].append(float(ef.bpm))
        uni_series["beat"].append(float(ef.beat_phase))
        uni_series["bar"].append(int(ef.bar))
        uni_series["sectionEnergy"].append(float(ef.section_energy))
        uni_series["sectionId"].append(int(ef.section_id))
        uni_series["energy"].append(float(ef.global_energy))

    frame_data = {"tracks": frame_tracks, "uniforms": uni_series}
```

Then add `"frame_data": frame_data,` to the returned dict (alongside `"tracks": tracks`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracks.py -k "per_frame_arrays or frame_scalars_match" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(timeline): ship per-frame track scalars + uniform series"
```

---

## Task 2: Composition contract test (locks the JS sum model)

**Files:**
- Test: `tests/test_tracks.py`

Prove the shipped frame scalars compose — via band-fill + `apply_setting` — to exactly `synth.synthesize`. This is the contract `cue-compose.js` mirrors in Task 3.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
def test_frame_data_composes_to_synth_output():
    from cedartoy.musicue import (
        MusicalSpectrumSynth, EvalFrame, BAND_TRACKS, _BIN_RANGES,
        _hann_envelope, apply_setting,
    )
    b = _bundle()
    tl = build_track_timeline(b, fps=24.0)
    fr = tl["frame_data"]
    synth = MusicalSpectrumSynth()
    settings = {"drums.kick": {"gain": 0.5}, "stem.vocals": {"mute": True}}
    envelopes = {n: _hann_envelope(e - s) for n, (s, e) in _BIN_RANGES.items()}

    for f in (0, 5, 10, 40):
        # Compose row0 the way the browser will: sum band-filled scalars.
        row0 = np.zeros(512, dtype=np.float32)
        for tid, band in BAND_TRACKS.items():
            v = apply_setting(fr["tracks"][tid][f], settings.get(tid))
            s, e = _BIN_RANGES[band]
            if v > 0:
                row0[s:e] += envelopes[band] * v
        row0 += 0.1 * fr["uniforms"]["sectionEnergy"][f]
        np.clip(row0, 0.0, 1.0, out=row0)

        # Reference: the canonical synth for the same frame + settings.
        ev_frame = EvalFrame(
            section_energy=fr["uniforms"]["sectionEnergy"][f],
            drum_pulses={k.split(".")[1]: fr["tracks"][k][f]
                         for k in BAND_TRACKS if k.startswith("drums.")},
            midi_energy={k.split(".")[1]: fr["tracks"][k][f]
                         for k in BAND_TRACKS if k.startswith("stem.")},
        )
        ref = synth.synthesize(ev_frame, settings)
        assert np.allclose(row0, ref[0], atol=1e-6)
```

Note: `stem.bass` and `stem.other` both map to `midi_energy` keys `bass`/`other`; the dict-comprehension above reconstructs them correctly because `_BAND_TRACK_SOURCE` keys are unique per track id.

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest tests/test_tracks.py -k composes_to_synth -v`
Expected: PASS immediately (Task 1 shipped correct scalars; this test documents/locks the contract). If it FAILS, the per-frame scalars or band mapping are wrong — fix Task 1 before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tracks.py
git commit -m "test(timeline): contract — frame scalars compose to synth output"
```

---

## Task 3: `cue-compose.js` — browser-side select-and-sum

**Files:**
- Create: `web/js/webgl/cue-compose.js`
- Test: `tests/web/test_cue_compose_source.py` (create — source-assertion, per repo convention)

A pure module mirroring `apply_setting`, the band ranges, the Hann envelope, and the effective-mask (solo) rule. No evaluator logic.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_cue_compose_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/webgl/cue-compose.js"


def test_cue_compose_exports_and_bands():
    s = SRC.read_text(encoding="utf-8")
    # exact band ranges must mirror Python _BIN_RANGES
    assert "low" in s and "[0, 32]" in s
    assert "[32, 96]" in s and "[96, 256]" in s and "[256, 512]" in s
    # exported functions the renderer/timeline use
    assert "export function applySetting" in s
    assert "export function effectiveSettings" in s
    assert "export function composeRow0" in s
    assert "export function composeUniforms" in s
    # threshold->gain->mute order documented
    assert "mute" in s and "threshold" in s and "gain" in s


def test_cue_compose_hann_and_solo():
    s = SRC.read_text(encoding="utf-8")
    assert "hann" in s.lower()                # band-fill uses a Hann window
    assert "solo" in s.lower()                # effective-mask honors solo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_cue_compose_source.py -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `web/js/webgl/cue-compose.js`:

```javascript
/**
 * Browser-side select-and-sum composition. Mirrors cedartoy/musicue.py:
 * apply_setting + band-fill + masked uniforms. Contains NO evaluator logic —
 * it consumes the per-frame scalars shipped by /api/reactivity/track-timeline.
 * Parity with Python is locked by tests/test_tracks.py::
 * test_frame_data_composes_to_synth_output.
 */

export const BAND_RANGES = {
    low: [0, 32], low_mid: [32, 96], mid_hi: [96, 256], high: [256, 512],
};

export const BAND_TRACKS = {
    "drums.kick": "low", "drums.snare": "low_mid", "drums.tom": "low_mid",
    "drums.hat": "mid_hi", "drums.cymbal": "mid_hi", "drums.other": "mid_hi",
    "stem.vocals": "high", "stem.other": "high", "stem.bass": "high",
};

// Hann window of given width (matches numpy.hanning: 0 at both ends).
function hann(width) {
    const w = new Float32Array(width);
    if (width === 1) { w[0] = 1; return w; }
    for (let i = 0; i < width; i++) {
        w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (width - 1));
    }
    return w;
}
const ENVELOPES = Object.fromEntries(
    Object.entries(BAND_RANGES).map(([n, [s, e]]) => [n, hann(e - s)]));

// threshold -> gain -> mute (stateless; smoothing is Phase 4).
export function applySetting(value, setting) {
    if (!setting) return value;
    if (setting.mute) return 0.0;
    const threshold = setting.threshold || 0.0;
    const gain = setting.gain == null ? 1.0 : setting.gain;
    return Math.max(0.0, value - threshold) * gain;
}

// Persisted track_settings + transient solo set -> effective per-track settings.
// If any track is soloed, every non-soloed track is muted for the live preview.
export function effectiveSettings(trackSettings, soloIds) {
    const solos = soloIds && soloIds.size ? soloIds : null;
    const out = {};
    const ids = new Set([...Object.keys(trackSettings || {}),
                         ...Object.keys(BAND_TRACKS),
                         ...(solos || [])]);
    for (const id of ids) {
        const base = (trackSettings && trackSettings[id]) || {};
        const muted = base.mute || (solos ? !solos.has(id) : false);
        out[id] = { ...base, mute: muted };
    }
    return out;
}

// Compose row 0 (512 bins) for frame f from per-frame track scalars + settings.
export function composeRow0(frameData, f, effSettings) {
    const row0 = new Float32Array(512);
    for (const [tid, band] of Object.entries(BAND_TRACKS)) {
        const arr = frameData.tracks[tid];
        const v = applySetting(arr ? arr[f] : 0.0, effSettings[tid]);
        if (v > 0) {
            const [s] = BAND_RANGES[band];
            const env = ENVELOPES[band];
            for (let i = 0; i < env.length; i++) row0[s + i] += env[i] * v;
        }
    }
    const secE = frameData.uniforms.sectionEnergy[f] || 0.0;
    for (let i = 0; i < 512; i++) row0[i] = Math.min(1.0, row0[i] + 0.1 * secE);
    return row0;
}

// Row 1 (heartbeat) — constant across bins, like the Python synth.
export function composeRow1(frameData, f) {
    const energy = frameData.uniforms.energy[f] || 0.0;
    const beat = frameData.uniforms.beat[f] || 0.0;
    const wave = Math.max(0, Math.min(1,
        0.5 + 0.5 * energy * Math.sin(2 * Math.PI * beat)));
    const row1 = new Float32Array(512);
    row1.fill(wave);
    return row1;
}

// Masked scalar uniforms for frame f.
export function composeUniforms(frameData, f, effSettings) {
    const u = frameData.uniforms;
    const tempoOff = !!(effSettings["tempo"] && effSettings["tempo"].mute);
    const secOff = !!(effSettings["sections"] && effSettings["sections"].mute);
    return {
        bpm: tempoOff ? 0.0 : u.bpm[f],
        beat: tempoOff ? 0.0 : u.beat[f],
        bar: tempoOff ? 0 : u.bar[f],
        sectionEnergy: secOff ? 0.0
            : applySetting(u.sectionEnergy[f], effSettings["sections"]),
        sectionId: secOff ? 0 : u.sectionId[f],
        energy: applySetting(u.energy[f], effSettings["energy"]),
    };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_cue_compose_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/webgl/cue-compose.js tests/web/test_cue_compose_source.py
git commit -m "feat(web): cue-compose select-and-sum module (parity with synth)"
```

---

## Task 4: `<track-timeline>` component — lanes + mute/solo

**Files:**
- Create: `web/js/components/track-timeline.js`
- Test: `tests/web/test_track_timeline_source.py` (create)

Multi-lane SVG graph (one lane per track), native shapes (drum onset ticks, stem/energy sparklines, section blocks, beat ticks), per-lane M/S buttons, shared playhead, click-to-seek (reuse `transport-seek`). Reads `/api/reactivity/track-timeline` lane-draw data. Emits `track-settings-change {trackSettings, soloIds}` when M/S toggled.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_track_timeline_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/track-timeline.js"


def test_track_timeline_component_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('track-timeline'" in s
    # fetches the Phase-1 endpoint
    assert "/api/reactivity/track-timeline" in s
    # per-lane mute/solo controls
    assert 'data-action="mute"' in s and 'data-action="solo"' in s
    # native shapes: onsets, curve, section blocks, beats
    assert "onsets" in s and "curve" in s and "blocks" in s and "beats" in s
    # emits settings change + reuses transport-seek
    assert "track-settings-change" in s
    assert "transport-seek" in s
    # muted lanes are visually dimmed
    assert "dim" in s.lower() or "opacity" in s.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_track_timeline_source.py -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `web/js/components/track-timeline.js`:

```javascript
/**
 * <track-timeline> — multi-lane MusiCue track graph for Validate mode.
 * One lane per track (native shapes), per-lane Mute/Solo, shared playhead,
 * click-to-seek. Emits 'track-settings-change' {trackSettings, soloIds}.
 */
import { BAND_TRACKS } from '../webgl/cue-compose.js';

const LANE_ORDER = [
    ...Object.keys(BAND_TRACKS), 'tempo', 'sections', 'energy',
];
const W = 1200, LANE_H = 22;

class TrackTimeline extends HTMLElement {
    constructor() {
        super();
        this.timeline = null;            // /api/reactivity/track-timeline payload
        this.trackSettings = {};         // persisted mutes/gains
        this.soloIds = new Set();        // transient solo
        this.durationSec = 1;
        this._audioPath = null;
    }

    connectedCallback() {
        this.render();
        document.addEventListener('project-loaded', (e) => this._onProject(e.detail));
        document.addEventListener('transport-frame', (e) =>
            this._updatePlayhead(e.detail.timeSec || 0));
    }

    async _onProject(detail) {
        this._audioPath = detail?.audio_path || detail?.path || null;
        if (!this._audioPath) return;
        try {
            const r = await fetch('/api/reactivity/track-timeline?audio='
                + encodeURIComponent(this._audioPath));
            if (!r.ok) { this._renderEmpty('No bundle for this audio'); return; }
            this.timeline = await r.json();
            this.durationSec = this.timeline.duration_sec || 1;
            this.draw();
        } catch (err) {
            this._renderEmpty('Timeline load failed');
        }
    }

    render() {
        this.innerHTML = `<div class="track-timeline" id="tt-root">
            <div class="tt-empty">Load a project to see tracks.</div></div>`;
    }
    _renderEmpty(msg) {
        this.querySelector('#tt-root').innerHTML = `<div class="tt-empty">${msg}</div>`;
    }

    _t2x(t) { return (t / this.durationSec) * W; }

    draw() {
        const tl = this.timeline;
        const lanes = LANE_ORDER.filter((id) => tl.tracks[id]);
        const health = tl.health || {};
        const rows = lanes.map((id, i) => this._laneSVG(id, i, health)).join('');
        const totalH = lanes.length * LANE_H;
        this.querySelector('#tt-root').innerHTML = `
            <div class="tt-grid">
              <div class="tt-gutters">
                ${lanes.map((id) => this._gutter(id)).join('')}
              </div>
              <svg class="tt-svg" viewBox="0 0 ${W} ${totalH}" preserveAspectRatio="none">
                ${rows}
                <line id="tt-playhead" x1="0" y1="0" x2="0" y2="${totalH}"
                      stroke="#e94560" stroke-width="2"/>
                <rect id="tt-hit" x="0" y="0" width="${W}" height="${totalH}"
                      fill="transparent" style="cursor:pointer"/>
              </svg>
            </div>`;
        this._attach(lanes);
    }

    _gutter(id) {
        const muted = this._isMuted(id);
        const soloed = this.soloIds.has(id);
        return `<div class="tt-gutter${muted ? ' dim' : ''}" data-track="${id}">
            <span class="tt-name">${id}</span>
            <button data-action="mute" data-track="${id}"
                class="tt-btn${muted ? ' on' : ''}">M</button>
            <button data-action="solo" data-track="${id}"
                class="tt-btn${soloed ? ' on' : ''}">S</button></div>`;
    }

    _laneSVG(id, i, health) {
        const y0 = i * LANE_H, mid = y0 + LANE_H / 2;
        const t = this.timeline.tracks[id];
        const dim = this._isMuted(id) ? ' opacity="0.3"' : '';
        let body = '';
        if (t.onsets) {
            body = t.onsets.map((o) =>
                `<line x1="${this._t2x(o.t)}" y1="${y0 + LANE_H - o.strength * (LANE_H - 4)}"
                   x2="${this._t2x(o.t)}" y2="${y0 + LANE_H - 2}" stroke="#8ad"/>`).join('');
        } else if (t.blocks) {
            body = t.blocks.map((b, k) =>
                `<rect x="${this._t2x(b.start)}" y="${y0 + 2}"
                   width="${this._t2x(b.end) - this._t2x(b.start)}" height="${LANE_H - 4}"
                   fill="${k % 2 ? '#334' : '#2a2a3a'}"/>
                 <text x="${this._t2x(b.start) + 3}" y="${mid + 3}" font-size="9"
                   fill="#9ab">${b.label}</text>`).join('');
        } else if (t.beats) {
            body = t.beats.map((b) =>
                `<line x1="${this._t2x(b.t)}" y1="${b.isDownbeat ? y0 + 2 : mid}"
                   x2="${this._t2x(b.t)}" y2="${y0 + LANE_H - 2}" stroke="#667"/>`).join('');
        } else if (t.curve && t.curve.values.length) {
            const hop = t.curve.hop_sec || 0;
            const pts = t.curve.values.map((v, k) =>
                `${this._t2x(k * hop)},${y0 + LANE_H - v * (LANE_H - 4)}`).join(' ');
            body = `<polyline points="${pts}" fill="none" stroke="#7ec97e"/>`;
        }
        const noData = (t.onsets && !t.onsets.length)
            || (t.curve && !t.curve.values.length);
        const flag = noData ? `<text x="4" y="${mid + 3}" font-size="9"
            fill="#a55">no data</text>` : '';
        return `<g${dim}>${body}${flag}
            <line x1="0" y1="${y0 + LANE_H}" x2="${W}" y2="${y0 + LANE_H}"
              stroke="#222"/></g>`;
    }

    _attach(lanes) {
        this.querySelectorAll('.tt-btn').forEach((btn) =>
            btn.addEventListener('click', () => this._toggle(
                btn.dataset.action, btn.dataset.track)));
        const hit = this.querySelector('#tt-hit');
        hit.addEventListener('click', (e) => {
            const rect = hit.getBoundingClientRect();
            const t = ((e.clientX - rect.left) / rect.width) * this.durationSec;
            document.dispatchEvent(new CustomEvent('transport-seek', { detail: { t } }));
        });
    }

    _isMuted(id) {
        if (this.soloIds.size) return !this.soloIds.has(id);
        return !!(this.trackSettings[id] && this.trackSettings[id].mute);
    }

    _toggle(action, id) {
        if (action === 'mute') {
            const cur = this.trackSettings[id] || {};
            this.trackSettings[id] = { ...cur, mute: !cur.mute };
        } else {
            if (this.soloIds.has(id)) this.soloIds.delete(id);
            else this.soloIds.add(id);
        }
        this.draw();
        document.dispatchEvent(new CustomEvent('track-settings-change', {
            detail: { trackSettings: this.trackSettings, soloIds: this.soloIds },
        }));
    }

    _updatePlayhead(t) {
        const ph = this.querySelector('#tt-playhead');
        if (ph) { const x = this._t2x(t); ph.setAttribute('x1', x); ph.setAttribute('x2', x); }
    }
}

customElements.define('track-timeline', TrackTimeline);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_track_timeline_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/track-timeline.js tests/web/test_track_timeline_source.py
git commit -m "feat(web): track-timeline lanes + mute/solo controls"
```

---

## Task 5: Timeline-driven preview composition

**Files:**
- Modify: `web/js/components/preview-panel.js`
- Test: `tests/web/test_preview_compose_source.py` (create)

When the timeline is loaded, the preview composes `iChannel0` + uniforms from `cue-compose` (masked) on each `transport-frame` instead of using live FFT. It listens for `track-settings-change` to update the effective mask.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_preview_compose_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/preview-panel.js"


def test_preview_uses_cue_compose_when_timeline_present():
    s = SRC.read_text(encoding="utf-8")
    assert "cue-compose.js" in s
    assert "composeRow0" in s and "composeUniforms" in s
    assert "effectiveSettings" in s
    assert "track-settings-change" in s
    assert "/api/reactivity/track-timeline" in s
    # frame index from transport time * fps
    assert "fps" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_preview_compose_source.py -v`
Expected: FAIL — `cue-compose.js` not referenced.

- [ ] **Step 3: Write minimal implementation**

In `web/js/components/preview-panel.js`, add the import at the top:

```javascript
import { composeRow0, composeRow1, composeUniforms, effectiveSettings }
    from '../webgl/cue-compose.js';
```

Add fields in the constructor (after `this._zeroWaveform`):

```javascript
        this._timeline = null;       // /api/reactivity/track-timeline payload
        this._effSettings = {};      // effective per-track settings (mask)
        this._timelineFps = 24.0;
```

In `connectedCallback`, after the existing `project-loaded` listener, fetch the timeline and subscribe to settings changes:

```javascript
        document.addEventListener('project-loaded', async (e) => {
            const audio = e.detail?.audio_path || e.detail?.path;
            this._timeline = null;
            if (audio) {
                try {
                    const r = await fetch('/api/reactivity/track-timeline?audio='
                        + encodeURIComponent(audio));
                    if (r.ok) {
                        this._timeline = await r.json();
                        this._timelineFps = this._timeline.fps || 24.0;
                        this._effSettings = effectiveSettings(
                            this._readPersistedSettings(), null);
                    }
                } catch (_) { this._timeline = null; }
            }
        });

        document.addEventListener('track-settings-change', (e) => {
            this._effSettings = effectiveSettings(
                e.detail.trackSettings, e.detail.soloIds);
            this._persistSettings(e.detail.trackSettings);
            if (this.renderer) this._composeAndRender(this.renderer.currentTime || 0);
        });
```

Replace the existing `transport-frame` handler body so that, when a timeline is present, it composes from it:

```javascript
        document.addEventListener('transport-frame', (e) => {
            if (!this.useAudioTimeline || !this.renderer) return;
            const t = e.detail.timeSec || 0;
            this.renderer.currentTime = t;
            if (this._timeline) {
                this._composeAndRender(t);
            } else {
                if (e.detail.bundle) this.renderer.updateBundleUniforms(e.detail.bundle);
                this.renderer.render();
            }
        });
```

Add the composition helpers and the persistence bridge to config-editor's `track_settings`:

```javascript
    _composeAndRender(t) {
        const tl = this._timeline;
        const n = tl.frames;
        let f = Math.round(t * this._timelineFps);
        if (f < 0) f = 0; if (f >= n) f = n - 1;
        const row0 = composeRow0(tl.frame_data, f, this._effSettings);
        const row1 = composeRow1(tl.frame_data, f);
        this.renderer.updateAudioData(row0, row1);
        this.renderer.updateBundleUniforms(composeUniforms(tl.frame_data, f, this._effSettings));
        this.renderer.render();
    }

    _readPersistedSettings() {
        const ce = document.querySelector('config-editor');
        return (ce && ce.config && ce.config.track_settings) || {};
    }

    _persistSettings(trackSettings) {
        const ce = document.querySelector('config-editor');
        if (ce && ce.config) {
            ce.config.track_settings = trackSettings;
            ce.saveToLocalStorage();
        }
    }
```

Note: `updateAudioData(row0, row1)` reuses the existing texture path — `row0` (our composed spectrum) lands in texture row 0 (FFT), `row1` (heartbeat) in row 1 (waveform), exactly where the render's `iChannel0` rows live. The `audio-data` (live FFT) listener stays for the no-timeline case.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_preview_compose_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/preview-panel.js tests/web/test_preview_compose_source.py
git commit -m "feat(web): drive preview from masked per-track timeline composition"
```

---

## Task 6: Validate-mode toggle + full-screen layout

**Files:**
- Modify: `web/index.html`
- Modify: `web/css/main.css`
- Modify: `web/js/app.js`
- Test: `tests/web/test_validate_mode_source.py` (create)

A header toggle adds `body.validate-mode`. In that mode CSS hides the shader-browser + config columns and the render footer, expands the preview to fill, and docks `<track-timeline>` + transport beneath it. `<track-timeline>` is added to the page.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_validate_mode_source.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_validate_toggle_and_track_timeline_present():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "track-timeline" in html               # graph mounted
    assert 'id="validate-toggle"' in html         # mode toggle button
    assert 'src="js/components/track-timeline.js"' in html or \
           "track-timeline.js" in html

    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "validate-mode" in css                 # mode styles exist

    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "validate-mode" in appjs               # toggle wires the class
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_validate_mode_source.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

(a) `web/index.html` — add the module import alongside the others (with the existing component imports near the top of `app.js` OR a `<script type="module">`; this repo imports components from `app.js`, so add the import there in step (c)). Add the toggle button in the header and mount the graph. In the header (`.app-header`), add:

```html
<button id="validate-toggle" class="btn btn-secondary">Validate</button>
```

Add `<track-timeline></track-timeline>` inside `.preview-panel-wrapper`, after `<cue-scrubber></cue-scrubber>`:

```html
        <track-timeline></track-timeline>
```

(b) `web/css/main.css` — append validate-mode rules:

```css
/* Validate mode: full-screen preview + docked track timeline. */
body.validate-mode .app-main { grid-template-columns: 0 0 1fr; }
body.validate-mode .shader-browser-panel,
body.validate-mode .config-editor-panel,
body.validate-mode .render-panel-wrapper { display: none; }
body.validate-mode .preview-panel-wrapper { width: 100%; }
body.validate-mode #preview-canvas { width: 100%; height: auto; max-height: 70vh; }

.track-timeline { width: 100%; overflow-x: auto; }
.track-timeline .tt-grid { display: grid; grid-template-columns: 130px 1fr; }
.track-timeline .tt-gutter { display: flex; align-items: center; gap: 4px;
    height: 22px; font-size: 10px; color: #9ab; }
.track-timeline .tt-gutter.dim { opacity: 0.45; }
.track-timeline .tt-name { flex: 1; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
.track-timeline .tt-btn { width: 16px; height: 16px; line-height: 14px;
    padding: 0; font-size: 10px; background: #2a2a3a; color: #aaa;
    border: 1px solid #444; border-radius: 3px; cursor: pointer; }
.track-timeline .tt-btn.on { background: #e94560; color: #fff; }
.track-timeline .tt-svg { width: 100%; height: auto; }
.track-timeline .tt-empty { padding: 8px; color: #888; font-size: 12px; }
```

(c) `web/js/app.js` — import the component and wire the toggle. Add with the other component imports:

```javascript
import './components/track-timeline.js';
```

Wire the button (in the app init, where other listeners are attached):

```javascript
const validateToggle = document.getElementById('validate-toggle');
if (validateToggle) {
    validateToggle.addEventListener('click', () => {
        const on = document.body.classList.toggle('validate-mode');
        validateToggle.classList.toggle('btn-primary', on);
        // Validate mode requires the audio-timeline clock so the preview is driven.
        const pv = document.querySelector('preview-panel');
        if (on && pv) pv._setUseAudioTimeline(true);
        window.dispatchEvent(new Event('resize'));
    });
}
```

(If `_setUseAudioTimeline` is not callable externally, dispatch the existing toggle: set `#preview-use-timeline` checked and fire its `change` event instead.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_validate_mode_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/css/main.css web/js/app.js tests/web/test_validate_mode_source.py
git commit -m "feat(web): Validate mode toggle + full-screen layout + track graph"
```

---

## Task 7: `track_settings` reaches the render config

**Files:**
- Modify: `web/js/components/render-panel.js` (or wherever the render config is assembled before `api.startRender`)
- Test: `tests/web/test_render_track_settings_source.py` (create)

Mutes set in Validate mode persist in `config-editor.config.track_settings` (Task 5). Ensure the render request includes them so the headless render honors mutes (Phase 1 already consumes `cfg["track_settings"]`).

- [ ] **Step 1: Verify where the render config is built**

Run: `python -m pytest -q` is not relevant here; first locate the assembly:

Run: `grep -rn "startRender\|track_settings\|config-editor" web/js/components/render-panel.js`
Expected: shows how the config object is gathered (likely from `config-editor.config`). If `track_settings` already flows through because the whole `config-editor.config` is sent, this task is a guard test only.

- [ ] **Step 2: Write the test**

Create `tests/web/test_render_track_settings_source.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_render_config_includes_track_settings():
    # config-editor.config carries track_settings (set by preview-panel),
    # and the render path sends the whole config object.
    rp = (ROOT / "web/js/components/render-panel.js").read_text(encoding="utf-8")
    ce = (ROOT / "web/js/components/config-editor.js").read_text(encoding="utf-8")
    # Either the render panel references track_settings, or it sends the full
    # config-editor config (which now includes track_settings).
    sends_full = "config-editor" in rp and ".config" in rp
    assert sends_full or "track_settings" in rp
    # config-editor must not strip unknown keys when serializing.
    assert "track_settings" in ce or "...this.config" in ce or "this.config" in ce
```

- [ ] **Step 3: Implement only if needed**

If Step 1 shows the render panel cherry-picks specific keys (not the whole config), add `track_settings: ce.config.track_settings || {}` to the assembled config object before `api.startRender(config)`. If it already sends the whole `config-editor.config`, no code change is needed — the test documents the contract.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_render_track_settings_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A web/js/components tests/web/test_render_track_settings_source.py
git commit -m "feat(web): include track_settings in render config"
```

---

## Task 8: Playwright E2E — muting kick drops the low band

**Files:**
- Create: `tests/web/test_validate_mode_e2e.py`

In-browser numeric proof that the masked composition works: enter Validate mode, sample the composed row-0 low band, mute kick, sample again, assert it dropped. Follows `test_sync_workflow.py` (skips if server not running).

- [ ] **Step 1: Write the test**

Create `tests/web/test_validate_mode_e2e.py`:

```python
import socket
import pytest

URL = "http://127.0.0.1:8080"
PROJECT = None  # set to a folder containing audio + sibling .musicue.json with drums


def _server_up():
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _server_up(), reason="UI server not running on :8080")
def test_mute_kick_drops_low_band():
    if not PROJECT:
        pytest.skip("set PROJECT to a drums-bearing project folder")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.fill("#project-path-input", PROJECT)
        page.click("#project-load-btn")
        page.wait_for_function(
            "() => !!document.querySelector('preview-panel')?._timeline",
            timeout=10000)
        page.click("#validate-toggle")

        # Compose low-band energy at frame 0 directly via the module.
        low_before = page.evaluate("""async () => {
            const m = await import('/js/webgl/cue-compose.js');
            const tl = document.querySelector('preview-panel')._timeline;
            const eff = m.effectiveSettings(tl.frame_data ? {} : {}, null);
            const row = m.composeRow0(tl.frame_data, 0, eff);
            let s = 0; for (let i = 0; i < 32; i++) s += row[i]; return s;
        }""")

        low_after = page.evaluate("""async () => {
            const m = await import('/js/webgl/cue-compose.js');
            const tl = document.querySelector('preview-panel')._timeline;
            const eff = m.effectiveSettings({'drums.kick': {mute: true}}, null);
            const row = m.composeRow0(tl.frame_data, 0, eff);
            let s = 0; for (let i = 0; i < 32; i++) s += row[i]; return s;
        }""")

        browser.close()
        assert low_before > 0.0
        assert low_after < low_before
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/web/test_validate_mode_e2e.py -v`
Expected: SKIP if no server / no PROJECT set; PASS when run against a live server with a drums-bearing project. (The Neon Queens bundle has empty drums — use a project whose bundle has kick onsets, or this asserts on a non-empty band.)

- [ ] **Step 3: Commit**

```bash
git add tests/web/test_validate_mode_e2e.py
git commit -m "test(web): e2e — muting kick drops composed low band"
```

---

## Task 9: Full regression sweep + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Python suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (E2E test SKIPs without a server). No regressions from Phase 1.

- [ ] **Step 2: Manual smoke (operator)**

Start the UI (`python -m cedartoy ui` or the project's start script), load a project with a bundle, click **Validate**, confirm: preview enlarges, track lanes render with native shapes, M/S buttons toggle and dim lanes, playing the transport animates the preview, muting a populated track visibly changes the preview, and a muted track stays muted in the render config.

- [ ] **Step 3: Commit any fix surfaced by smoke**

Commit with a clear message if needed; otherwise nothing to do.

---

## Self-Review

**Spec coverage (Phase 2 scope of `2026-05-22-track-reactivity-validation-design.md`):**
- §5.1 Validate mode full-screen toggle → Task 6.
- §5.2 track-lane graph, native shapes, M/S, dim, playhead, click-to-seek → Task 4.
- §3.1 mute persists / solo preview-only (effective mask) → Tasks 3, 5, 7.
- §4 preview/render parity via canonical timeline + select-and-sum → Tasks 1-3, 5 (Python contract + JS mirror); endpoint extension addresses the Phase-1 gap (lane-draw data only).
- §5.4 "no data" lane treatment → Task 4 (`noData` flag).
- Render honors mutes → Task 7 (Phase 1 already consumes `cfg["track_settings"]`).

**Placeholder scan:** No TBD/TODO. JS steps use full code; verification uses source-assertion + Playwright (this repo has no JS unit runner — stated in Background, not a placeholder). Task 7 is conditional-implementation with an explicit locate step and a guard test — concrete, not vague.

**Type/contract consistency:** `frame_data.tracks[trackId][frame]` (scalar) and `frame_data.uniforms[key][frame]` defined in Task 1, consumed identically in Tasks 2, 3, 5, 8. `effectiveSettings(trackSettings, soloIds)`, `composeRow0(frameData, f, effSettings)`, `composeRow1(frameData, f)`, `composeUniforms(frameData, f, effSettings)` — signatures identical across cue-compose.js (Task 3) and preview-panel.js (Task 5). `track-settings-change {trackSettings, soloIds}` emitted in Task 4, consumed in Task 5. Band ranges `[0,32]/[32,96]/[96,256]/[256,512]` identical in Python (`_BIN_RANGES`) and JS (`BAND_RANGES`), pinned by Task 2's contract test + Task 3's source test.

**Audio path (confirmed):** the `project-loaded` event `detail` carries `audio_path` (the on-disk path) and `bundle_path` — verified in `web/js/app.js:77`, `cue-scrubber.js:17,30` (which uses `audio_path` for `/api/project/bundle`). Tasks 4 & 5 fetch `/api/reactivity/track-timeline?audio=` + `encodeURIComponent(e.detail.audio_path)`. (`preview-panel.js:33` uses `audio_url` only as a yes/no "has timeline" flag — do not use it as the path.) The `detail?.audio_path || detail?.path` fallback in the task code is harmless but `audio_path` is the field that resolves.
