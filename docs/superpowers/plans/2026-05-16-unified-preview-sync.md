# Plan B — Unified preview-sync

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hit play once and have audio + cue-scrubber playhead + shader animation all advance in lockstep against the project's audio — no second "Choose File", no second playhead.

**Architecture:** Audio is the master clock. A new `<transport-strip>` owns the `<audio>` element bound to `/api/project/audio`, drives a single `transport-frame` event each rAF, and feeds three subscribers: preview-panel (sets `renderer.currentTime`), cue-scrubber (moves playhead, updates readout), and itself (emits FFT for raw-mode shaders). Cue-scrubber loses click-to-seek ownership and gains a waveform underlay. Preview-panel loses its own play/pause/seek controls and becomes a pure canvas + camera widget. The legacy `audio-viz` component is deleted.

**Tech Stack:** FastAPI (Range-aware `FileResponse`), Python (`numpy`/`soundfile` for waveform peaks), vanilla JS custom elements, Web Audio API (`MediaElementAudioSourceNode` + `AnalyserNode`), Playwright for the smoke test.

**Spec:** `docs/superpowers/specs/2026-05-16-cedartoy-ux-sync-pass.md` §§ 4.2, 6.1, 7.1-7.3, 8.A-B, 9, 10, 11 (Plan B).

---

## File structure

```
Server (Python / FastAPI)
├── cedartoy/server/api/project.py    [modify] + GET /audio (Range), + GET /waveform, +audio_url in load
└── tests/test_project_route.py       [modify] new tests for /audio, /waveform, audio_url

Web (vanilla JS components, in web/js/components/)
├── transport-strip.js                [new]   master clock + audio + FFT + readout
├── cue-scrubber.js                   [rewrite] waveform underlay, playhead, transport events, no readout
├── preview-panel.js                  [rewrite] pure canvas + camera; lose transport
├── audio-viz.js                      [delete]
├── ../app.js                         [modify] imports, event wiring, cache-bust
└── ../../index.html                  [modify] swap <audio-viz> for <transport-strip>
└── ../../css/components.css          [modify] .transport-strip styling

Tests
└── tests/web/test_sync_workflow.py   [new]   Playwright E2E for Plan B's slice
```

The cue-scrubber and transport-strip are siblings under `.preview-panel-wrapper`. They communicate purely through events (`transport-frame`, `transport-seek`, `project-loaded`) — neither holds a reference to the other. Preview-panel does the same. This keeps each unit independently testable and replaceable.

---

## Task 1 — `GET /api/project/audio` with Range support

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `cedartoy/server/api/project.py`
- Test: `tests/test_project_route.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_project_route.py`:

```python
def test_project_audio_returns_wav_bytes(client, tmp_path):
    """GET /api/project/audio?path=<song.wav> streams the file."""
    folder = tmp_path / "song"
    audio = _seed(folder)
    resp = client.get("/api/project/audio", params={"path": str(audio)})
    assert resp.status_code == 200
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers.get("content-type", "").startswith("audio/")
    assert len(resp.content) == audio.stat().st_size


def test_project_audio_supports_range_request(client, tmp_path):
    """Range: bytes=0-99 returns 206 with the first 100 bytes."""
    folder = tmp_path / "song"
    audio = _seed(folder)
    resp = client.get(
        "/api/project/audio",
        params={"path": str(audio)},
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert len(resp.content) == 100


def test_project_audio_404_when_missing(client, tmp_path):
    resp = client.get("/api/project/audio", params={"path": str(tmp_path / "nope.wav")})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest D:/cedartoy/tests/test_project_route.py -k project_audio -v`
Expected: 3 FAIL with 404 (route not registered).

- [ ] **Step 3: Add the endpoint**

Open `cedartoy/server/api/project.py`. Add at the top of the imports:

```python
from fastapi.responses import FileResponse
```

Add after the existing `project_bundle` function:

```python
@router.get("/audio")
def project_audio(path: str):
    """Stream the project's audio file with Range support.

    The browser's <audio> element uses Range to seek without re-downloading
    the whole song. FileResponse handles Range/206 natively in Starlette.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    media_type = "audio/wav" if p.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(p, media_type=media_type, headers={"Accept-Ranges": "bytes"})
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_project_route.py -k project_audio -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git -C D:/cedartoy add cedartoy/server/api/project.py tests/test_project_route.py
git -C D:/cedartoy commit -m "feat(api): GET /api/project/audio streams project wav with Range support"
```

---

## Task 2 — `GET /api/project/waveform`

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `cedartoy/server/api/project.py`
- Test: `tests/test_project_route.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_project_route.py`:

```python
def test_project_waveform_returns_peaks(client, tmp_path):
    """GET /api/project/waveform?path=<song.wav>&n=64 returns 64 peak floats."""
    folder = tmp_path / "song"
    audio = _seed(folder)
    resp = client.get(
        "/api/project/waveform",
        params={"path": str(audio), "n": 64},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "peaks" in body
    assert isinstance(body["peaks"], list)
    assert len(body["peaks"]) == 64
    # Silent wav -> all zeros, but the type contract still holds:
    for v in body["peaks"]:
        assert isinstance(v, (int, float))
        assert -1.0 <= v <= 1.0


def test_project_waveform_404_when_missing(client, tmp_path):
    resp = client.get(
        "/api/project/waveform",
        params={"path": str(tmp_path / "nope.wav"), "n": 64},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest D:/cedartoy/tests/test_project_route.py -k project_waveform -v`
Expected: 2 FAIL with 404 (route not registered).

- [ ] **Step 3: Add the endpoint**

In `cedartoy/server/api/project.py`, after `project_audio`, add:

```python
@router.get("/waveform")
def project_waveform(path: str, n: int = 1000) -> dict:
    """Return `n` peak values (range -1.0..1.0) sampled across the audio file.

    Used by transport-strip to paint the waveform underlay. The wav is read
    fresh each call (no global state) — cheap for typical 3-5 minute songs.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    import numpy as np
    import soundfile as sf
    data, _ = sf.read(str(p), always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)  # downmix to mono
    if len(data) == 0:
        return {"peaks": [0.0] * n}
    bucket = max(1, len(data) // n)
    peaks = []
    for i in range(n):
        start = i * bucket
        end = min(start + bucket, len(data))
        chunk = data[start:end]
        peaks.append(float(np.max(np.abs(chunk))) if len(chunk) else 0.0)
    return {"peaks": peaks}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_project_route.py -k project_waveform -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git -C D:/cedartoy add cedartoy/server/api/project.py tests/test_project_route.py
git -C D:/cedartoy commit -m "feat(api): GET /api/project/waveform returns N peaks for transport-strip"
```

---

## Task 3 — `audio_url` in project-load response

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `cedartoy/server/api/project.py`
- Test: `tests/test_project_route.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_project_route.py`:

```python
def test_project_load_includes_audio_url(client, tmp_path):
    """The load response includes a browser-fetchable URL for the audio."""
    folder = tmp_path / "song"
    audio = _seed(folder)
    resp = client.post("/api/project/load", json={"path": str(folder)})
    body = resp.json()
    assert resp.status_code == 200
    assert body["audio_url"] == f"/api/project/audio?path={audio}"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest D:/cedartoy/tests/test_project_route.py::test_project_load_includes_audio_url -v`
Expected: FAIL with `KeyError: 'audio_url'`.

- [ ] **Step 3: Add audio_url to the load response**

In `cedartoy/server/api/project.py`, the `project_load` function:

```python
@router.post("/load")
def project_load(body: ProjectLoadRequest) -> dict:
    p = Path(body.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {p}")
    proj = load_project(p)
    audio_url = (
        f"/api/project/audio?path={proj.audio_path}"
        if proj.audio_path else None
    )
    return {
        "folder": str(proj.folder),
        "audio_path": str(proj.audio_path) if proj.audio_path else None,
        "audio_url": audio_url,
        "bundle_path": str(proj.bundle_path) if proj.bundle_path else None,
        "stems_paths": {k: str(v) for k, v in proj.stems_paths.items()},
        "manifest": proj.manifest,
        "bundle_sha_matches_audio": proj.bundle_sha_matches_audio,
        "warnings": proj.warnings,
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_project_route.py -v`
Expected: all tests in this file PASS (no regression on the existing ones).

- [ ] **Step 5: Commit**

```bash
git -C D:/cedartoy add cedartoy/server/api/project.py tests/test_project_route.py
git -C D:/cedartoy commit -m "feat(api): project-load response includes audio_url for transport-strip"
```

---

## Task 4 — Cue-scrubber rewrite (waveform underlay + playhead + transport events)

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/cue-scrubber.js`

- [ ] **Step 1: Rewrite the file**

Replace the entire contents of `web/js/components/cue-scrubber.js` with:

```javascript
class CueScrubber extends HTMLElement {
    constructor() {
        super();
        this.bundle = null;
        this.peaks = null;          // array of 1000 floats from /api/project/waveform
        this.durationSec = 0;
        this._currentTime = 0;
    }

    connectedCallback() {
        document.addEventListener('project-loaded', (e) => {
            this.bundle = null;
            this.peaks = null;
            this.durationSec = 0;
            if (e.detail) {
                if (e.detail.bundle_path) this._loadBundle(e.detail.bundle_path);
                if (e.detail.audio_path)  this._loadPeaks(e.detail.audio_path);
            }
            this.render();
        });
        document.addEventListener('transport-frame', (e) => {
            this._currentTime = e.detail.timeSec || 0;
            this._updatePlayhead();
        });
        this.render();
    }

    async _loadBundle(path) {
        try {
            const r = await fetch(`/api/project/bundle?path=${encodeURIComponent(path)}`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            this.bundle = await r.json();
            this.durationSec = this.bundle.duration_sec || 0;
            this.render();
            this._attachClickHandler();
        } catch (e) {
            console.error('cue-scrubber bundle load failed', e);
            this.bundle = null;
            this.render();
        }
    }

    async _loadPeaks(audioPath) {
        try {
            const r = await fetch(`/api/project/waveform?path=${encodeURIComponent(audioPath)}&n=1000`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const body = await r.json();
            this.peaks = body.peaks;
            // If duration wasn't set by bundle (raw-FFT mode), defer; transport-frame
            // events still drive a relative playhead if duration is wired elsewhere.
            this.render();
            this._attachClickHandler();
        } catch (e) {
            console.error('cue-scrubber peaks load failed', e);
            this.peaks = null;
            this.render();
        }
    }

    render() {
        const haveData = (this.bundle && this.durationSec > 0) || (this.peaks && this.peaks.length);
        if (!haveData) {
            this.innerHTML = `<div class="cue-scrubber-empty">No project loaded.</div>`;
            return;
        }
        const W = 1200, H = 100;
        const dur = this.durationSec || 1;
        const t2x = (t) => (t / dur) * W;

        // Waveform underlay (peaks mirrored above and below the centerline).
        let wave = '';
        if (this.peaks && this.peaks.length) {
            const N = this.peaks.length;
            const pts = [];
            for (let i = 0; i < N; i++) {
                const x = (i / (N - 1)) * W;
                const v = Math.max(0, Math.min(1, this.peaks[i] || 0));
                pts.push(`${x.toFixed(1)},${(50 - v * 35).toFixed(1)}`);
            }
            for (let i = N - 1; i >= 0; i--) {
                const x = (i / (N - 1)) * W;
                const v = Math.max(0, Math.min(1, this.peaks[i] || 0));
                pts.push(`${x.toFixed(1)},${(50 + v * 35).toFixed(1)}`);
            }
            wave = `<polygon points="${pts.join(' ')}" fill="#2d4a3a" stroke="none"/>`;
        }

        const sectionBlocks = (this.bundle?.sections || []).map((s, i) => {
            const x = t2x(s.start), w = t2x(s.end) - x;
            const fill = i % 2 === 0 ? '#2a2a2a' : '#333';
            return `<rect x="${x}" y="0" width="${Math.max(0, w)}" height="20" fill="${fill}" opacity="0.85"/>
                    <text x="${x + 4}" y="14" fill="#aaa" font-size="10" pointer-events="none">${this._escape(s.label || '')}</text>`;
        }).join('');

        const beatTicks = (this.bundle?.beats || []).map((b) => {
            const x = t2x(b.t);
            const tall = b.is_downbeat ? 18 : 10;
            return `<line x1="${x}" y1="20" x2="${x}" y2="${20 + tall}" stroke="#666" stroke-width="${b.is_downbeat ? 1.5 : 0.5}"/>`;
        }).join('');

        const kicks = ((this.bundle?.drums || {}).kick || []).map((d) => {
            const x = t2x(d.t);
            return `<circle cx="${x}" cy="55" r="2" fill="#e88"/>`;
        }).join('');

        // Energy curve overlay (only when bundle present).
        const energy = this.bundle?.global_energy;
        let energyPath = '';
        if (energy && energy.values && energy.values.length > 1 && energy.hop_sec > 0) {
            const pts = energy.values.map((v, i) => {
                const t = i * energy.hop_sec;
                return `${t2x(t).toFixed(1)},${(92 - v * 30).toFixed(1)}`;
            }).join(' ');
            energyPath = `<polyline points="${pts}" stroke="#7ec97e" stroke-width="1" fill="none"/>`;
        }

        const playheadX = t2x(this._currentTime);

        this.innerHTML = `
            <div class="cue-scrubber-host">
                <svg class="cue-scrubber-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
                    ${wave}
                    ${sectionBlocks}
                    ${beatTicks}
                    ${kicks}
                    ${energyPath}
                    <line id="cue-playhead" x1="${playheadX}" y1="0" x2="${playheadX}" y2="${H}" stroke="#e94560" stroke-width="2"/>
                    <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" id="scrub-hit"/>
                </svg>
            </div>
        `;
        this._attachClickHandler();
    }

    _updatePlayhead() {
        const line = this.querySelector('#cue-playhead');
        if (!line || !this.durationSec) return;
        const x = (this._currentTime / this.durationSec) * 1200;
        line.setAttribute('x1', x);
        line.setAttribute('x2', x);
    }

    _attachClickHandler() {
        const hit = this.querySelector('#scrub-hit');
        if (!hit) return;
        hit.onclick = (e) => {
            const rect = hit.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const t = (x / rect.width) * (this.durationSec || 1);
            document.dispatchEvent(new CustomEvent('transport-seek', { detail: { t } }));
        };
    }

    _escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }
}

customElements.define('cue-scrubber', CueScrubber);
```

Changes vs. prior:
- Added `_loadPeaks()` + waveform polygon layer.
- Added `#cue-playhead` line driven by `transport-frame` (was `preview-frame`).
- Click dispatches `transport-seek` on `document` (was `scrubber-seek` on `this`).
- Removed the `cue-scrubber-readout` div + `_updateReadout()` — readout moves to `transport-strip`.

- [ ] **Step 2: Commit**

```bash
git -C D:/cedartoy add web/js/components/cue-scrubber.js
git -C D:/cedartoy commit -m "refactor(cue-scrubber): waveform underlay, playhead line, transport events

Subscribes to project-loaded for both bundle and waveform peaks (new
/api/project/waveform endpoint). Subscribes to transport-frame to move
a single shared playhead line. Click emits transport-seek for the
transport-strip to consume. Readout moves to transport-strip."
```

---

## Task 5 — Transport-strip skeleton

**Repo:** `D:\cedartoy`

**Files:**
- Create: `web/js/components/transport-strip.js`

- [ ] **Step 1: Create the file**

Create `web/js/components/transport-strip.js` with:

```javascript
class TransportStrip extends HTMLElement {
    constructor() {
        super();
        this.audio = null;        // HTMLAudioElement
        this.duration = 0;
        this._rafId = null;
        this._fft = new Float32Array(512);
        this._wave = new Float32Array(512);
        this._analyser = null;
        this._audioCtx = null;
    }

    connectedCallback() {
        this.render();
        this._attachListeners();
        document.addEventListener('project-loaded', (e) => this._onProjectLoaded(e.detail));
        document.addEventListener('transport-seek', (e) => this._seek(e.detail.t));
    }

    render() {
        this.innerHTML = `
            <div class="transport-strip">
                <button class="btn btn-primary" id="ts-play" disabled>▶</button>
                <span id="ts-time" style="font-family:monospace;font-size:12px;color:#aaa;width:90px;">--:-- / --:--</span>
                <span id="ts-readout" style="flex:1;color:#888;font-family:monospace;font-size:11px;text-align:right;">iBpm — iBeat — iBar — iEnergy — iSectionEnergy —</span>
            </div>
        `;
    }

    _attachListeners() {
        this.querySelector('#ts-play').addEventListener('click', () => this._togglePlay());
    }

    _onProjectLoaded(detail) {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        if (this.audio) { this.audio.pause(); this.audio = null; }
        if (this._audioCtx) { this._audioCtx.close(); this._audioCtx = null; this._analyser = null; }
        if (!detail || !detail.audio_url) {
            this.querySelector('#ts-play').disabled = true;
            this.querySelector('#ts-play').title = 'No audio in project';
            return;
        }
        this.audio = new Audio(detail.audio_url);
        this.audio.preload = 'auto';
        this.audio.addEventListener('loadedmetadata', () => {
            this.duration = this.audio.duration;
            this._updateTime(0);
            const btn = this.querySelector('#ts-play');
            btn.disabled = false;
            btn.title = '';
        });
        this.audio.addEventListener('ended', () => this._pause());
        this._updateBundleReadout(detail);
    }

    async _togglePlay() {
        if (!this.audio) return;
        if (this.audio.paused) await this._play();
        else this._pause();
    }

    async _play() {
        if (!this.audio) return;
        await this.audio.play();
        this.querySelector('#ts-play').textContent = '⏸';
        this._loop();
    }

    _pause() {
        if (!this.audio) return;
        this.audio.pause();
        this.querySelector('#ts-play').textContent = '▶';
        if (this._rafId) cancelAnimationFrame(this._rafId);
        this._rafId = null;
    }

    _seek(t) {
        if (!this.audio) return;
        const clamped = Math.max(0, Math.min(this.duration || t, t));
        this.audio.currentTime = clamped;
        this._tick();  // immediate playhead update even if paused
    }

    _loop() {
        this._tick();
        this._rafId = requestAnimationFrame(() => this._loop());
    }

    _tick() {
        const t = this.audio ? this.audio.currentTime : 0;
        this._updateTime(t);
        document.dispatchEvent(new CustomEvent('transport-frame', { detail: { timeSec: t } }));
    }

    _updateTime(t) {
        const fmt = (s) => {
            const m = Math.floor(s / 60), ss = Math.floor(s % 60);
            return `${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
        };
        this.querySelector('#ts-time').textContent = `${fmt(t)} / ${fmt(this.duration || 0)}`;
    }

    _updateBundleReadout(detail) {
        // Placeholder; filled in by Task 7 when bundle is wired.
        this.querySelector('#ts-readout').textContent =
            'iBpm — iBeat — iBar — iEnergy — iSectionEnergy —';
    }
}

customElements.define('transport-strip', TransportStrip);
```

- [ ] **Step 2: Commit**

```bash
git -C D:/cedartoy add web/js/components/transport-strip.js
git -C D:/cedartoy commit -m "feat(transport-strip): skeleton component owning audio playback + clock

Wraps <audio src=/api/project/audio>. Listens to project-loaded to bind
the source, emits transport-frame on every rAF while playing, listens
to transport-seek to drive audio.currentTime. Bundle readout placeholder
for Task 7 to fill in."
```

---

## Task 6 — Wire transport-strip into the page

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/index.html`
- Modify: `web/js/app.js`
- Modify: `web/css/components.css`

- [ ] **Step 1: Swap `<audio-viz>` for `<transport-strip>`**

Open `web/index.html`. Find:

```html
            <section class="preview-panel-wrapper">
                <preview-panel></preview-panel>
                <cue-scrubber></cue-scrubber>
                <audio-viz></audio-viz>
            </section>
```

Replace with:

```html
            <section class="preview-panel-wrapper">
                <preview-panel></preview-panel>
                <transport-strip></transport-strip>
                <cue-scrubber></cue-scrubber>
            </section>
```

(transport-strip sits *above* cue-scrubber because it owns the play button + time + readout, while cue-scrubber is the visualization rail.)

- [ ] **Step 2: Update imports in app.js**

Open `web/js/app.js`. Find:

```javascript
import './components/audio-viz.js?v=2';
```

Replace with:

```javascript
import './components/transport-strip.js?v=1';
```

Also bump the cue-scrubber cache-bust:

```javascript
import './components/cue-scrubber.js?v=3';
```

- [ ] **Step 3: Add CSS for the new transport strip**

Open `web/css/components.css`. Append at the end:

```css
/* Transport strip */
transport-strip { display: block; }
.transport-strip {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    background: #1f1f1f;
    border-bottom: 1px solid #2a2a2a;
}
.transport-strip #ts-play {
    padding: 2px 14px;
    font-size: 14px;
}
.transport-strip #ts-play:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
```

- [ ] **Step 4: Commit**

```bash
git -C D:/cedartoy add web/index.html web/js/app.js web/css/components.css
git -C D:/cedartoy commit -m "feat(ui): wire transport-strip into preview wrapper, bump cache-bust"
```

---

## Task 7 — Transport-strip: bundle readout + FFT emission

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/transport-strip.js`

- [ ] **Step 1: Add bundle-aware readout + Web Audio analyser**

Open `web/js/components/transport-strip.js`. Add a `bundle` instance variable, load it on `project-loaded`, compute the readout each `_tick()`, and wire up FFT analyser when audio starts. Replace the file contents with:

```javascript
class TransportStrip extends HTMLElement {
    constructor() {
        super();
        this.audio = null;
        this.duration = 0;
        this.bundle = null;
        this._rafId = null;
        this._fft = new Uint8Array(512);
        this._wave = new Uint8Array(512);
        this._analyser = null;
        this._audioCtx = null;
    }

    connectedCallback() {
        this.render();
        this._attachListeners();
        document.addEventListener('project-loaded', (e) => this._onProjectLoaded(e.detail));
        document.addEventListener('transport-seek', (e) => this._seek(e.detail.t));
    }

    render() {
        this.innerHTML = `
            <div class="transport-strip">
                <button class="btn btn-primary" id="ts-play" disabled>▶</button>
                <span id="ts-time" style="font-family:monospace;font-size:12px;color:#aaa;width:90px;">--:-- / --:--</span>
                <span id="ts-readout" style="flex:1;color:#888;font-family:monospace;font-size:11px;text-align:right;">iBpm — iBeat — iBar — iEnergy — iSectionEnergy —</span>
            </div>
        `;
    }

    _attachListeners() {
        this.querySelector('#ts-play').addEventListener('click', () => this._togglePlay());
    }

    async _onProjectLoaded(detail) {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        if (this.audio) { this.audio.pause(); this.audio = null; }
        if (this._audioCtx) { try { await this._audioCtx.close(); } catch {} this._audioCtx = null; this._analyser = null; }
        this.bundle = null;

        if (!detail || !detail.audio_url) {
            this.querySelector('#ts-play').disabled = true;
            this.querySelector('#ts-play').title = 'No audio in project';
            this._renderReadout();
            return;
        }

        this.audio = new Audio(detail.audio_url);
        this.audio.crossOrigin = 'anonymous';
        this.audio.preload = 'auto';
        this.audio.addEventListener('loadedmetadata', () => {
            this.duration = this.audio.duration;
            this._updateTime(0);
            const btn = this.querySelector('#ts-play');
            btn.disabled = false;
            btn.title = '';
        });
        this.audio.addEventListener('ended', () => this._pause());

        if (detail.bundle_path) {
            try {
                const r = await fetch(`/api/project/bundle?path=${encodeURIComponent(detail.bundle_path)}`);
                if (r.ok) this.bundle = await r.json();
            } catch {}
        }
        this._renderReadout();
    }

    async _togglePlay() {
        if (!this.audio) return;
        if (this.audio.paused) await this._play();
        else this._pause();
    }

    async _play() {
        if (!this.audio) return;
        // Lazily create AudioContext on first play (browsers require a user gesture).
        if (!this._audioCtx) {
            this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const src = this._audioCtx.createMediaElementSource(this.audio);
            this._analyser = this._audioCtx.createAnalyser();
            this._analyser.fftSize = 1024;
            src.connect(this._analyser);
            this._analyser.connect(this._audioCtx.destination);
        }
        await this.audio.play();
        this.querySelector('#ts-play').textContent = '⏸';
        this._loop();
    }

    _pause() {
        if (!this.audio) return;
        this.audio.pause();
        this.querySelector('#ts-play').textContent = '▶';
        if (this._rafId) cancelAnimationFrame(this._rafId);
        this._rafId = null;
    }

    _seek(t) {
        if (!this.audio) return;
        const clamped = Math.max(0, Math.min(this.duration || t, t));
        this.audio.currentTime = clamped;
        this._tick();
    }

    _loop() {
        this._tick();
        this._rafId = requestAnimationFrame(() => this._loop());
    }

    _tick() {
        const t = this.audio ? this.audio.currentTime : 0;
        this._updateTime(t);
        this._emitAudioData();
        this._renderReadout(t);
        document.dispatchEvent(new CustomEvent('transport-frame', { detail: { timeSec: t } }));
    }

    _emitAudioData() {
        if (!this._analyser) return;
        this._analyser.getByteFrequencyData(this._fft);
        this._analyser.getByteTimeDomainData(this._wave);
        const fft = new Float32Array(512);
        const wave = new Float32Array(512);
        for (let i = 0; i < 512; i++) {
            fft[i] = (this._fft[i] || 0) / 255.0;
            wave[i] = ((this._wave[i] || 128) / 128.0) - 1.0;
        }
        document.dispatchEvent(new CustomEvent('audio-data', { detail: { fft, waveform: wave } }));
    }

    _updateTime(t) {
        const fmt = (s) => {
            const m = Math.floor(s / 60), ss = Math.floor(s % 60);
            return `${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
        };
        this.querySelector('#ts-time').textContent = `${fmt(t)} / ${fmt(this.duration || 0)}`;
    }

    _renderReadout(t = 0) {
        const out = this.querySelector('#ts-readout');
        if (!out) return;
        if (!this.bundle) {
            out.textContent = 'iBpm — iBeat — iBar — iEnergy — iSectionEnergy —';
            return;
        }
        const b = this.bundle;
        const bpm = (b.tempo && b.tempo.bpm_global) || 0;
        let beatPhase = 0, bar = 0;
        const beats = b.beats || [];
        for (let i = 0; i < beats.length - 1; i++) {
            if (beats[i].t <= t && t < beats[i + 1].t) {
                const span = beats[i + 1].t - beats[i].t;
                beatPhase = span > 0 ? (t - beats[i].t) / span : 0;
                bar = beats[i].bar ?? 0;
                break;
            }
        }
        let energy = 0;
        const ge = b.global_energy;
        if (ge && ge.values && ge.hop_sec > 0) {
            const idx = Math.min(Math.floor(t / ge.hop_sec), ge.values.length - 1);
            if (idx >= 0) energy = ge.values[idx] ?? 0;
        }
        let sectionEnergy = 0, sectionLabel = '—';
        for (const s of (b.sections || [])) {
            if (s.start <= t && t < s.end) {
                sectionEnergy = s.energy_rank ?? 0;
                sectionLabel = s.label || '—';
                break;
            }
        }
        out.textContent =
            `iBpm ${bpm.toFixed(0)} · iBeat ${beatPhase.toFixed(2)} · iBar ${bar} · ` +
            `iEnergy ${energy.toFixed(2)} · iSectionEnergy ${sectionEnergy.toFixed(2)} · ${sectionLabel}`;
    }
}

customElements.define('transport-strip', TransportStrip);
```

- [ ] **Step 2: Bump cache-bust in app.js**

Open `web/js/app.js`. Change:

```javascript
import './components/transport-strip.js?v=1';
```

to:

```javascript
import './components/transport-strip.js?v=2';
```

- [ ] **Step 3: Commit**

```bash
git -C D:/cedartoy add web/js/components/transport-strip.js web/js/app.js
git -C D:/cedartoy commit -m "feat(transport-strip): bundle-aware readout + Web Audio FFT emission

Loads the bundle on project-loaded and computes iBpm/iBeat/iBar/iEnergy/
iSectionEnergy + section label each rAF tick. Creates an AudioContext on
first play (after user gesture) and emits audio-data with FFT + waveform
Float32Array(512) — same shape audio-viz used, so shaders reading raw
FFT keep working unchanged."
```

---

## Task 8 — Preview-panel rewrite (pure canvas + camera)

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/preview-panel.js`

- [ ] **Step 1: Replace the file**

Replace the entire contents of `web/js/components/preview-panel.js` with:

```javascript
import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js';

class PreviewPanel extends HTMLElement {
    constructor() {
        super();
        this.renderer = null;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();

        const canvas = this.querySelector('#preview-canvas');
        this.renderer = new ShaderRenderer(canvas);

        document.addEventListener('shader-select', async (e) => {
            await this.loadShader(e.detail.path);
        });

        document.addEventListener('audio-data', (e) => {
            if (this.renderer) {
                this.renderer.updateAudioData(e.detail.fft, e.detail.waveform);
            }
        });

        // Transport-strip drives time; preview-panel is a passive subscriber.
        document.addEventListener('transport-frame', (e) => {
            if (this.renderer) {
                this.renderer.currentTime = e.detail.timeSec || 0;
                this.renderer.render();
            }
        });

        document.addEventListener('config-change', (e) => {
            const config = e.detail;
            const modeMap = { '2d': 0, 'equirect': 1, 'll180': 2 };
            if (config.camera_mode && this.renderer) {
                const modeIndex = modeMap[config.camera_mode] ?? 0;
                this.renderer.cameraMode = modeIndex;
                const sel = this.querySelector('#camera-mode');
                if (sel) sel.value = modeIndex;
            }
            const tiltValue = config.camera_tilt_deg ?? config.camera_params?.tilt_deg;
            if (tiltValue !== undefined && this.renderer) {
                this.renderer.cameraTilt = tiltValue;
                const slider = this.querySelector('#camera-tilt');
                const disp = this.querySelector('#tilt-display');
                if (slider) slider.value = tiltValue;
                if (disp) disp.textContent = `${tiltValue}°`;
            }
            this.renderer.render();
        });
    }

    render() {
        this.innerHTML = `
            <div class="preview-container">
                <h3>Preview</h3>
                <div style="position: relative;">
                    <canvas id="preview-canvas" width="640" height="360"
                        style="width: 100%; background: #000; border-radius: 4px;"></canvas>
                    <div id="preview-error" style="display: none; position: absolute; top: 50%; left: 50%;
                        transform: translate(-50%, -50%); color: var(--error); font-weight: bold;">
                    </div>
                </div>
                <div class="camera-controls" style="margin-top: 8px; padding: 8px; background: var(--bg-secondary); border-radius: 4px;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                        <label style="font-size: 0.85rem; width: 100px;">Camera Mode:</label>
                        <select id="camera-mode" style="flex: 1; padding: 4px; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border); border-radius: 4px;">
                            <option value="0">2D Standard</option>
                            <option value="1">Equirectangular</option>
                            <option value="2">LL180 Dome</option>
                        </select>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <label style="font-size: 0.85rem; width: 100px;">Camera Tilt:</label>
                        <input type="range" id="camera-tilt" min="0" max="90" value="0" step="1"
                            style="flex: 1;">
                        <span id="tilt-display" style="font-size: 0.85rem; width: 40px;">0°</span>
                    </div>
                </div>
                <div style="margin-top: 8px; font-size: 0.8rem; color: var(--text-secondary);">
                    Note: Preview is single-pass only. Full multipass rendering in final output.
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        const cameraModeSelect = this.querySelector('#camera-mode');
        const cameraTiltSlider = this.querySelector('#camera-tilt');
        const tiltDisplay = this.querySelector('#tilt-display');

        cameraModeSelect.addEventListener('change', (e) => {
            const modeIndex = parseInt(e.target.value);
            if (this.renderer) {
                this.renderer.cameraMode = modeIndex;
                this.renderer.render();
            }
            const modeNames = ['2d', 'equirect', 'll180'];
            const ce = document.querySelector('config-editor');
            if (ce) {
                ce.config.camera_mode = modeNames[modeIndex];
                ce.saveToLocalStorage();
            }
        });

        cameraTiltSlider.addEventListener('input', (e) => {
            const tilt = parseFloat(e.target.value);
            tiltDisplay.textContent = `${tilt}°`;
            if (this.renderer) {
                this.renderer.cameraTilt = tilt;
                this.renderer.render();
            }
            const ce = document.querySelector('config-editor');
            if (ce) {
                ce.config.camera_tilt_deg = tilt;
                ce.saveToLocalStorage();
            }
        });
    }

    async loadShader(path) {
        try {
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.style.display = 'none';
            const shaderData = await api.getShader(path);
            this.renderer.compileShader(shaderData.source);
            this.renderer.render();
        } catch (err) {
            console.error('Failed to load shader:', err);
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.textContent = `Shader Error: ${err.message}`;
            errorDiv.style.display = 'block';
        }
    }
}

customElements.define('preview-panel', PreviewPanel);
```

Removed:
- `#play-btn`, `#time-slider`, `#time-display` (transport-strip owns these now).
- `togglePlay()`, `updateTimeDisplay()`, `formatTime()`, `_updateInterval`.
- The old `preview-frame` / `preview-play` / `preview-pause` / `preview-seek` / `scrubber-seek` event plumbing.
- `duration = 10.0` and the implicit playback loop. The renderer's internal `play()`/`pause()`/`startTime` are no longer used — `currentTime` is set directly from the transport frame.

- [ ] **Step 2: Bump cache-bust in app.js**

In `web/js/app.js`, change `preview-panel.js?v=3` to `preview-panel.js?v=4`.

- [ ] **Step 3: Commit**

```bash
git -C D:/cedartoy add web/js/components/preview-panel.js web/js/app.js
git -C D:/cedartoy commit -m "refactor(preview-panel): pure canvas + camera; transport-strip owns time

Drops play/pause/seek controls. Subscribes to transport-frame and sets
renderer.currentTime + renders each frame. The renderer's internal play
loop is no longer invoked from here; transport-strip drives ticks."
```

---

## Task 9 — Delete audio-viz

**Repo:** `D:\cedartoy`

**Files:**
- Delete: `web/js/components/audio-viz.js`

- [ ] **Step 1: Delete the file**

Run:

```bash
rm D:/cedartoy/web/js/components/audio-viz.js
```

- [ ] **Step 2: Verify no remaining references**

Run: `grep -rn "audio-viz\|AudioViz" D:/cedartoy/web/ D:/cedartoy/cedartoy/`
Expected: only matches inside `index.html`/`app.js` should already have been removed in Task 6. If `grep` returns nothing, you're clean. If it returns hits, remove them.

- [ ] **Step 3: Commit**

```bash
git -C D:/cedartoy add -A web/js/components/
git -C D:/cedartoy commit -m "chore(audio-viz): delete legacy component; transport-strip replaces it"
```

---

## Task 10 — Keyboard shortcuts on transport-strip

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/transport-strip.js`

- [ ] **Step 1: Add a global key listener (focus-aware)**

In `transport-strip.js`, inside `connectedCallback()`, after the existing `document.addEventListener('transport-seek', ...)` line, add:

```javascript
        document.addEventListener('keydown', (e) => this._onKey(e));
```

Then add this method on the class (anywhere alongside the others):

```javascript
    _onKey(e) {
        // Only when focus is on body or transport-strip itself — never in inputs/textareas.
        const t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
            return;
        }
        if (e.code === 'Space') {
            e.preventDefault();
            this._togglePlay();
        } else if (e.code === 'ArrowLeft') {
            e.preventDefault();
            this._seek((this.audio?.currentTime || 0) - 1);
        } else if (e.code === 'ArrowRight') {
            e.preventDefault();
            this._seek((this.audio?.currentTime || 0) + 1);
        } else if (e.code === 'BracketLeft') {
            e.preventDefault();
            this._jumpSection(-1);
        } else if (e.code === 'BracketRight') {
            e.preventDefault();
            this._jumpSection(+1);
        }
    }

    _jumpSection(dir) {
        if (!this.audio || !this.bundle?.sections?.length) return;
        const t = this.audio.currentTime;
        const starts = this.bundle.sections.map(s => s.start);
        let target = null;
        if (dir < 0) {
            // Previous section start, with a small epsilon so re-pressing [ jumps back.
            target = [...starts].reverse().find(s => s < t - 0.1) ?? 0;
        } else {
            target = starts.find(s => s > t + 0.1) ?? t;
        }
        this._seek(target);
    }
```

- [ ] **Step 2: Bump cache-bust in app.js**

In `web/js/app.js`, change `transport-strip.js?v=2` to `transport-strip.js?v=3`.

- [ ] **Step 3: Commit**

```bash
git -C D:/cedartoy add web/js/components/transport-strip.js web/js/app.js
git -C D:/cedartoy commit -m "feat(transport-strip): keyboard — Space toggle, arrows ±1s, brackets ±section"
```

---

## Task 11 — Playwright smoke test for unified sync

**Repo:** `D:\cedartoy`

**Files:**
- Create: `tests/web/test_sync_workflow.py`

- [ ] **Step 1: Create the test**

Create `tests/web/test_sync_workflow.py` with:

```python
"""Playwright smoke test for Plan B's unified preview-sync.

Walks: project load -> no audio-viz Choose-File input -> play ->
playhead moves -> click scrubber -> seek lands on audio + scrubber.
Requires a running CedarToy UI server on http://127.0.0.1:8080 and
a project folder at D:/temp/cedartoy_browser_test_export.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

PROJECT_PATH = "D:/temp/cedartoy_browser_test_export"
URL = "http://127.0.0.1:8080/"


pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright


def _skip_if_no_project():
    if not Path(PROJECT_PATH).exists():
        pytest.skip(f"Test project not at {PROJECT_PATH}")


def test_unified_sync_workflow():
    _skip_if_no_project()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")

        # 1) Load project.
        page.fill("#project-path-input", PROJECT_PATH)
        page.click("#project-load-btn")
        page.wait_for_function(
            "() => !!document.querySelector('transport-strip')?.audio",
            timeout=10000,
        )

        # 2) Legacy <audio-viz> must be gone.
        audio_viz_count = page.evaluate("document.querySelectorAll('audio-viz').length")
        assert audio_viz_count == 0, "audio-viz should be removed"

        # 3) Hit play (synthesize a click — Web Audio needs a user gesture).
        page.wait_for_function(
            "() => !document.querySelector('#ts-play').disabled",
            timeout=10000,
        )
        page.click("#ts-play")
        time.sleep(0.8)

        # 4) Playhead has moved.
        current_time = page.evaluate(
            "() => document.querySelector('transport-strip').audio.currentTime"
        )
        assert current_time > 0.2, f"transport-strip should advance audio currentTime, got {current_time}"

        # 5) Click cue-scrubber at ~50% (uses bounding rect on the SVG hit overlay).
        page.evaluate(
            """
            (() => {
              const hit = document.querySelector('#scrub-hit');
              const r = hit.getBoundingClientRect();
              const ev = new MouseEvent('click', {
                clientX: r.left + r.width * 0.5,
                clientY: r.top + r.height * 0.5,
                bubbles: true,
              });
              hit.dispatchEvent(ev);
            })();
            """
        )
        time.sleep(0.4)

        # 6) Audio currentTime jumped near 50% of duration.
        duration = page.evaluate("document.querySelector('transport-strip').audio.duration")
        seeked = page.evaluate("document.querySelector('transport-strip').audio.currentTime")
        assert abs(seeked - duration * 0.5) < max(0.5, duration * 0.05), (
            f"seek should land near 50%: duration={duration} seeked={seeked}"
        )

        browser.close()
```

- [ ] **Step 2: Start the UI server in the background**

```bash
python -m cedartoy.cli ui &
sleep 2
```

- [ ] **Step 3: Run the test**

Run: `python -m pytest D:/cedartoy/tests/web/test_sync_workflow.py -v`
Expected: PASS (or skip if `D:/temp/cedartoy_browser_test_export` doesn't exist).

If it fails: read the assertion that fired and iterate. Common gotchas: browsers block Web Audio until user gesture (the explicit `page.click` is the gesture); range-request quirks if `<audio>` is mid-load (the `wait_for_function` on `audio` instance covers that).

- [ ] **Step 4: Commit**

```bash
git -C D:/cedartoy add tests/web/test_sync_workflow.py
git -C D:/cedartoy commit -m "test(web): Playwright smoke for Plan B unified sync workflow

Verifies that loading a project arms transport-strip, that audio-viz is
gone, that hitting play advances audio time, and that clicking the cue
scrubber at 50% seeks the audio to ~50% of duration."
```

---

## Task 12 — Push CedarToy main

**Repo:** `D:\cedartoy`

- [ ] **Step 1: Push**

```bash
git -C D:/cedartoy push origin main
```

- [ ] **Step 2: Manual eyeball test in a real browser**

Open `http://localhost:8080`. Load `D:/temp/cedartoy_browser_test_export`. Confirm:
- `<audio-viz>` "Choose File" input is gone.
- The new transport strip appears between the canvas and the cue scrubber.
- Hitting ▶ plays audio + the cue-scrubber playhead moves + the shader animates.
- Clicking the cue-scrubber jumps audio and visuals together.
- Space toggles play/pause; arrows seek ±1s; `[` / `]` jump section starts.
- No console errors.

---

## Self-review checklist

- [x] **Spec coverage:**
  - § 4.2 single master clock → Tasks 5, 7 (transport-strip emits transport-frame; preview-panel + cue-scrubber subscribe).
  - § 6.1 `GET /api/project/audio` with Range → Task 1.
  - § 7.1 `<transport-strip>` (audio, FFT, readout) → Tasks 5, 7.
  - § 7.2 `<cue-scrubber>` rewrite (waveform underlay, playhead, transport-* events) → Task 4.
  - § 7.3 `<preview-panel>` rewrite (pure canvas) → Task 8.
  - § 8.A flow: project-loaded fans out to transport + scrubber → Tasks 3, 4, 5.
  - § 8.B flow: play → transport-frame → 3 subscribers → Tasks 5, 7, 8, 4.
  - § 9 row "No project loaded, hit play" → Task 5 (`disabled` button + tooltip).
  - § 9 row "Project loaded but bundle missing" → Task 4 (raw-FFT mode: waveform-only render, no section/beat layers).
  - § 9 row "Audio file missing" → Task 1 (404 from `/api/project/audio`).
  - § 9 row "Seek past audio end" → Task 5 (`_seek` clamps to `duration`).
  - § 9 row "Spacebar in input/textarea" → Task 10 (focus check).
  - § 9 row "Project loaded mid-playback" → Task 7 (`_onProjectLoaded` pauses, cancels rAF, resets state).
  - § 10 web Playwright test (Plan B slice) → Task 11.
  - § 11 Plan B scope → this plan.
- [x] **Placeholder scan:** every step has literal code/commands. No "similar to" cross-references.
- [x] **Type consistency:** event names (`transport-frame`, `transport-seek`, `audio-data`, `project-loaded`, `shader-select`, `config-change`) consistent across tasks 3-8. Bundle field names (`tempo.bpm_global`, `beats`, `sections`, `global_energy`, `drums.kick`) match between cue-scrubber (T4) and transport-strip readout (T7). `audio_url` consistent in T3, T5, T7, T11.
- [x] **Scope:** 12 tasks, single repo, single subsystem. Each task is one focused commit. No external dependencies beyond what's already installed.
