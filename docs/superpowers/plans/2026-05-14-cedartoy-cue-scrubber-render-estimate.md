# CedarToy Cue Scrubber + Render Estimate Implementation Plan (B-2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cue-scrubber timeline below the preview that visualizes the bundle's sections, beats, drum onsets, and energy curve, plus a render-budget estimate in stage [3] with a confirm-modal guardrail when long renders are kicked off.

**Architecture:** A new pure `cedartoy/render_estimate.py` computes frame time and output size from a moving-average history file. A new `web/js/components/cue-scrubber.js` reads the bundle JSON (already loaded via project-panel in Plan B-1) and renders an SVG timeline with click-to-jump. The render budget number flows from a small `/api/render/estimate` endpoint into the existing output-panel placeholder. The render-job initiation path (`/api/render/start` or equivalent) gains a confirm-modal step on the front-end when the estimate exceeds thresholds.

**Tech Stack:** Python 3.11, FastAPI, vanilla JS web components, SVG rendering, JSON history file in `~/.cedartoy/render_history.json`.

**Spec:** `docs/superpowers/specs/2026-05-14-musicue-cedartoy-holistic-design.md` (§ Part B — stage [3] estimate, cue scrubber, render-budget guardrail).

**Depends on:** Plan B-1 (project loader supplies the bundle path and `project-loaded` event).

---

## File map

**Create:**
- `cedartoy/render_estimate.py` — pure math + history file IO.
- `cedartoy/server/api/estimate.py` — `POST /api/render/estimate` router.
- `web/js/components/cue-scrubber.js` — SVG timeline component.
- `tests/test_render_estimate.py` — math + threshold + history.
- `tests/test_estimate_route.py` — HTTP.

**Modify:**
- `cedartoy/server/app.py` — register estimate router.
- `web/js/components/output-panel.js` — replace `#render-estimate` placeholder with live estimate.
- `web/js/components/render-panel.js` — add confirm-modal when estimate exceeds threshold.
- `web/js/components/preview-panel.js` — mount `<cue-scrubber>` below the canvas.
- `web/css/components.css` — scrubber styles.

---

## Task 1: `RenderEstimate` math (pure)

**Files:**
- Create: `cedartoy/render_estimate.py`
- Create: `tests/test_render_estimate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render_estimate.py
"""Unit tests for render-budget estimation math."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cedartoy.render_estimate import (
    DEFAULT_FRAME_TIME_SEC,
    RenderEstimate,
    bytes_per_frame,
    estimate_render,
)


def test_bytes_per_frame_png_8bit():
    # 4 channels (RGBA) * 1 byte/channel * 1920 * 1080 ≈ 8.3 MB
    n = bytes_per_frame("png", 8, 1920, 1080)
    assert 8_000_000 < n < 9_000_000


def test_bytes_per_frame_exr_16f():
    # 4 channels * 2 bytes * 1920 * 1080 ≈ 16.6 MB
    n = bytes_per_frame("exr", 16, 1920, 1080)
    assert 16_000_000 < n < 17_000_000


def test_bytes_per_frame_exr_32f():
    n = bytes_per_frame("exr", 32, 1920, 1080)
    assert 33_000_000 < n < 34_000_000


def test_estimate_render_with_no_history_uses_default():
    est = estimate_render(
        shader_basename="auroras",
        width=1920, height=1080,
        fps=60, duration_sec=10.0,
        tile_count=1, ss_scale=1.0,
        format="png", bit_depth=8,
        history={},
    )
    assert est.frame_time_sec == pytest.approx(DEFAULT_FRAME_TIME_SEC)
    assert est.total_frames == 600
    assert est.total_seconds == pytest.approx(DEFAULT_FRAME_TIME_SEC * 600)
    assert est.output_bytes > 0


def test_estimate_render_uses_history_when_available():
    history = {
        "auroras::1920x1080": {"mean_frame_time": 0.5},
    }
    est = estimate_render(
        shader_basename="auroras",
        width=1920, height=1080,
        fps=30, duration_sec=10.0,
        tile_count=1, ss_scale=1.0,
        format="png", bit_depth=8,
        history=history,
    )
    assert est.frame_time_sec == pytest.approx(0.5)
    assert est.total_seconds == pytest.approx(0.5 * 300)


def test_estimate_render_scales_by_tile_count_and_ss():
    """Frame time ∝ tile_count × ss_scale²."""
    history = {"auroras::1920x1080": {"mean_frame_time": 1.0}}
    base = estimate_render(shader_basename="auroras", width=1920, height=1080,
                           fps=60, duration_sec=1.0, tile_count=1, ss_scale=1.0,
                           format="png", bit_depth=8, history=history)
    tiled = estimate_render(shader_basename="auroras", width=1920, height=1080,
                            fps=60, duration_sec=1.0, tile_count=4, ss_scale=2.0,
                            format="png", bit_depth=8, history=history)
    # 4 tiles * 2² ss = 16× factor.
    assert tiled.frame_time_sec == pytest.approx(base.frame_time_sec * 16)


def test_estimate_exceeds_thresholds():
    est = RenderEstimate(
        frame_time_sec=10.0, total_frames=600, total_seconds=6000.0,
        output_bytes=200 * 1024**3, history_hit=False,
    )
    assert est.exceeds_time_threshold(3600)
    assert est.exceeds_size_threshold(50 * 1024**3)
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_render_estimate.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# cedartoy/render_estimate.py
"""Pure render-budget estimation.

Frame time is sourced from a per-(shader, resolution) moving average
stored in ~/.cedartoy/render_history.json. With no history, falls back
to DEFAULT_FRAME_TIME_SEC. Scales the base time by tile_count × ss_scale².

Output size is exact: bytes_per_pixel × pixels × frames.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FRAME_TIME_SEC = 5.0  # conservative default with no prior history

HISTORY_PATH = Path.home() / ".cedartoy" / "render_history.json"

# (format, bit_depth) -> bytes per pixel (RGBA assumed everywhere).
_BPP: dict[tuple[str, int], int] = {
    ("png", 8): 4,
    ("png", 16): 8,
    ("exr", 16): 8,
    ("exr", 32): 16,
}


def bytes_per_frame(fmt: str, bit_depth: int, width: int, height: int) -> int:
    key = (fmt, bit_depth)
    if key not in _BPP:
        raise ValueError(f"unknown format/bit_depth: {key}; "
                         f"known: {sorted(_BPP)}")
    return _BPP[key] * width * height


@dataclass
class RenderEstimate:
    frame_time_sec: float
    total_frames: int
    total_seconds: float
    output_bytes: int
    history_hit: bool

    def exceeds_time_threshold(self, threshold_sec: float) -> bool:
        return self.total_seconds > threshold_sec

    def exceeds_size_threshold(self, threshold_bytes: int) -> bool:
        return self.output_bytes > threshold_bytes


def _history_key(shader_basename: str, width: int, height: int) -> str:
    return f"{shader_basename}::{width}x{height}"


def estimate_render(
    *,
    shader_basename: str,
    width: int,
    height: int,
    fps: float,
    duration_sec: float,
    tile_count: int,
    ss_scale: float,
    format: str,
    bit_depth: int,
    history: dict | None = None,
) -> RenderEstimate:
    history = history if history is not None else {}
    key = _history_key(shader_basename, width, height)
    entry = history.get(key)
    if entry and "mean_frame_time" in entry:
        base_frame_time = float(entry["mean_frame_time"])
        hit = True
    else:
        base_frame_time = DEFAULT_FRAME_TIME_SEC
        hit = False

    frame_time = base_frame_time * tile_count * (ss_scale ** 2)
    total_frames = max(1, math.ceil(duration_sec * fps))
    total_seconds = frame_time * total_frames
    output_bytes = bytes_per_frame(format, bit_depth, width, height) * total_frames

    return RenderEstimate(
        frame_time_sec=frame_time,
        total_frames=total_frames,
        total_seconds=total_seconds,
        output_bytes=output_bytes,
        history_hit=hit,
    )


def load_history(path: Path = HISTORY_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_history(
    *,
    shader_basename: str,
    width: int,
    height: int,
    mean_frame_time: float,
    path: Path = HISTORY_PATH,
) -> None:
    """Update the moving average for (shader, resolution).

    Uses a simple exponential moving average with alpha=0.3 so a single
    outlier render doesn't dominate the estimate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    history = load_history(path)
    key = _history_key(shader_basename, width, height)
    prev = history.get(key, {}).get("mean_frame_time")
    if prev is None:
        new = mean_frame_time
    else:
        new = 0.7 * prev + 0.3 * mean_frame_time
    history[key] = {"mean_frame_time": new}
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_render_estimate.py -v`
Expected: All PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/render_estimate.py tests/test_render_estimate.py
git commit -m "feat(estimate): pure render-budget math + history file IO"
```

---

## Task 2: History file load/save round-trip test

**Files:**
- Modify: `tests/test_render_estimate.py`

- [ ] **Step 1: Add the test**

```python
def test_record_history_ema(tmp_path):
    from cedartoy.render_estimate import load_history, record_history, estimate_render
    p = tmp_path / "history.json"

    record_history(shader_basename="auroras", width=1920, height=1080,
                   mean_frame_time=10.0, path=p)
    record_history(shader_basename="auroras", width=1920, height=1080,
                   mean_frame_time=20.0, path=p)

    history = load_history(p)
    # EMA with alpha=0.3: 0.7*10 + 0.3*20 = 13.0
    assert history["auroras::1920x1080"]["mean_frame_time"] == pytest.approx(13.0)

    est = estimate_render(
        shader_basename="auroras", width=1920, height=1080,
        fps=60, duration_sec=10.0, tile_count=1, ss_scale=1.0,
        format="png", bit_depth=8, history=history,
    )
    assert est.frame_time_sec == pytest.approx(13.0)
    assert est.history_hit is True
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_render_estimate.py::test_record_history_ema -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_render_estimate.py
git commit -m "test(estimate): history file EMA round-trip"
```

---

## Task 3: `POST /api/render/estimate` endpoint

**Files:**
- Create: `cedartoy/server/api/estimate.py`
- Create: `tests/test_estimate_route.py`
- Modify: `cedartoy/server/app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_estimate_route.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_estimate_returns_payload(client):
    resp = client.post("/api/render/estimate", json={
        "shader_basename": "auroras",
        "width": 1920, "height": 1080,
        "fps": 60, "duration_sec": 10.0,
        "tile_count": 1, "ss_scale": 1.0,
        "format": "png", "bit_depth": 8,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_frames"] == 600
    assert body["total_seconds"] > 0
    assert body["output_bytes"] > 0
    assert body["history_hit"] is False
    assert body["exceeds_time_threshold_1h"] in (True, False)
    assert body["exceeds_size_threshold_50gb"] in (True, False)


def test_estimate_400_on_unknown_format(client):
    resp = client.post("/api/render/estimate", json={
        "shader_basename": "x", "width": 100, "height": 100,
        "fps": 60, "duration_sec": 1.0, "tile_count": 1, "ss_scale": 1.0,
        "format": "tiff", "bit_depth": 8,
    })
    assert resp.status_code == 400
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_estimate_route.py -v`
Expected: FAIL (404 or 405).

- [ ] **Step 3: Implement the router**

```python
# cedartoy/server/api/estimate.py
"""Render-budget estimate endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cedartoy.render_estimate import estimate_render, load_history

router = APIRouter()


class EstimateRequest(BaseModel):
    shader_basename: str
    width: int = Field(..., gt=0, le=32768)
    height: int = Field(..., gt=0, le=32768)
    fps: float = Field(..., gt=0, le=240)
    duration_sec: float = Field(..., gt=0)
    tile_count: int = Field(..., gt=0)
    ss_scale: float = Field(..., gt=0, le=8)
    format: str
    bit_depth: int


@router.post("/estimate")
def estimate(body: EstimateRequest) -> dict:
    try:
        est = estimate_render(
            shader_basename=body.shader_basename,
            width=body.width, height=body.height,
            fps=body.fps, duration_sec=body.duration_sec,
            tile_count=body.tile_count, ss_scale=body.ss_scale,
            format=body.format, bit_depth=body.bit_depth,
            history=load_history(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "frame_time_sec": est.frame_time_sec,
        "total_frames": est.total_frames,
        "total_seconds": est.total_seconds,
        "output_bytes": est.output_bytes,
        "history_hit": est.history_hit,
        "exceeds_time_threshold_1h": est.exceeds_time_threshold(3600),
        "exceeds_size_threshold_50gb": est.exceeds_size_threshold(50 * 1024**3),
    }
```

In `cedartoy/server/app.py`, register the router under `/api/render` (mounting alongside the existing `render` router is fine — different paths):

```python
from .api import estimate as estimate_routes
app.include_router(estimate_routes.router, prefix="/api/render", tags=["estimate"])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_estimate_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/server/api/estimate.py cedartoy/server/app.py tests/test_estimate_route.py
git commit -m "feat(api): POST /api/render/estimate"
```

---

## Task 4: Wire estimate into `output-panel.js`

**Files:**
- Modify: `web/js/components/output-panel.js`

- [ ] **Step 1: Replace the `#render-estimate` placeholder with live fetching**

In `output-panel.js`, after `this.config` updates, debounce a fetch to `/api/render/estimate` and render the result.

Add to the component class:

```javascript
async _refreshEstimate() {
    if (this._estimateTimer) clearTimeout(this._estimateTimer);
    this._estimateTimer = setTimeout(async () => {
        const cfg = this.config;
        if (!cfg.shader || !cfg.width || !cfg.height || !cfg.fps) {
            this.querySelector('#render-estimate').textContent =
                'Estimate: pick a shader and resolution.';
            return;
        }
        const body = {
            shader_basename: (cfg.shader.split(/[\\/]/).pop() || '').replace(/\.glsl$/, ''),
            width: cfg.width, height: cfg.height,
            fps: cfg.fps, duration_sec: cfg.duration_sec || 10,
            tile_count: (cfg.tiles_x || 1) * (cfg.tiles_y || 1),
            ss_scale: cfg.ss_scale || 1.0,
            format: cfg.default_output_format || 'png',
            bit_depth: cfg.default_bit_depth ? parseInt(cfg.default_bit_depth) : 8,
        };
        try {
            const r = await fetch('/api/render/estimate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const e = await r.json();
            this._renderEstimate(e);
        } catch (err) {
            this.querySelector('#render-estimate').textContent =
                `Estimate failed: ${err.message}`;
        }
    }, 250);
}

_renderEstimate(e) {
    const dt = (e.total_seconds / 60).toFixed(1);
    const sz = (e.output_bytes / (1024 ** 3)).toFixed(1);
    const hint = e.history_hit ? '' : ' (no prior render data)';
    const warn = (e.exceeds_time_threshold_1h || e.exceeds_size_threshold_50gb)
        ? ' ⚠' : '';
    this.querySelector('#render-estimate').innerHTML =
        `Estimate: ${e.frame_time_sec.toFixed(1)} s/frame · ` +
        `${e.total_frames} frames · ~${dt} min · ${sz} GB${warn}${hint}`;
}
```

Call `this._refreshEstimate()` at the end of `connectedCallback()` and inside `_fire()`. Also re-trigger when `config-change` from outside (shader path change in `config-editor`) fires:

```javascript
document.addEventListener('config-change', (e) => {
    this.config = e.detail;
    this._refreshEstimate();
});
```

- [ ] **Step 2: Smoke**

In the UI, pick a shader, change resolution / tiles / ss / fps; estimate updates within ~250ms each time.

- [ ] **Step 3: Commit**

```bash
git add web/js/components/output-panel.js
git commit -m "feat(ui): live render-budget estimate in output panel"
```

---

## Task 5: Confirm-modal guardrail in `render-panel.js`

**Files:**
- Modify: `web/js/components/render-panel.js`

- [ ] **Step 1: Add the gate before starting a render**

Find where `render-panel.js` calls the start-render API. Before issuing the call, fetch the estimate (same payload as task 4) and if either threshold is exceeded, show `confirm()` (or a custom modal). Skip the check if `localStorage.getItem('cedartoy_skip_render_guardrail') === '1'`.

```javascript
async _checkBudgetThenStart() {
    if (localStorage.getItem('cedartoy_skip_render_guardrail') === '1') {
        return this._startRenderImmediate();
    }
    // ... fetch estimate same payload as output-panel ...
    const r = await fetch('/api/render/estimate', { /* same body */ });
    const e = await r.json();
    if (e.exceeds_time_threshold_1h || e.exceeds_size_threshold_50gb) {
        const dt = (e.total_seconds / 60).toFixed(1);
        const sz = (e.output_bytes / (1024 ** 3)).toFixed(1);
        const ok = confirm(
            `This render will take ~${dt} minutes and produce ${sz} GB of output.\n\n` +
            `Continue?\n\n` +
            `(Tick "don't ask again" inside this dialog wording is TODO — for ` +
            `now, the threshold gate can be permanently disabled by setting ` +
            `localStorage cedartoy_skip_render_guardrail=1.)`
        );
        if (!ok) return;
    }
    return this._startRenderImmediate();
}
```

Rename the existing render-start handler to `_startRenderImmediate` and have the button call `_checkBudgetThenStart` instead.

- [ ] **Step 2: Smoke**

Set duration to 600s, resolution to 8192x4096, click Start Render — confirm modal appears with realistic numbers.

- [ ] **Step 3: Commit**

```bash
git add web/js/components/render-panel.js
git commit -m "feat(ui): render-budget guardrail confirm modal"
```

---

## Task 6: Cue scrubber component (SVG timeline)

**Files:**
- Create: `web/js/components/cue-scrubber.js`
- Modify: `web/js/components/preview-panel.js`
- Modify: `web/css/components.css`

- [ ] **Step 1: Write the component**

The scrubber listens for `project-loaded` (B-1) and renders an SVG with four lanes: section blocks, bar/beat grid, kick dots, energy curve. Click-to-jump emits `scrubber-seek` with a time-in-seconds detail.

```javascript
// web/js/components/cue-scrubber.js
class CueScrubber extends HTMLElement {
    constructor() {
        super();
        this.bundle = null;
        this.durationSec = 0;
    }

    connectedCallback() {
        document.addEventListener('project-loaded', (e) => {
            if (e.detail.bundle_path) {
                this._loadBundle(e.detail.bundle_path);
            } else {
                this.bundle = null;
                this.render();
            }
        });
        this.render();
    }

    async _loadBundle(path) {
        // The bundle path is server-local; expose it via /api/project/bundle?path=
        // (added below) or via a project-load response that already inlines the
        // bundle JSON. Simplest: have /api/project/load include a `bundle` field.
        try {
            const r = await fetch(`/api/project/bundle?path=${encodeURIComponent(path)}`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            this.bundle = await r.json();
            this.durationSec = this.bundle.duration_sec || 0;
            this.render();
        } catch (e) {
            console.error('cue-scrubber bundle load failed', e);
        }
    }

    render() {
        if (!this.bundle) {
            this.innerHTML = `<div class="cue-scrubber-empty">No bundle loaded.</div>`;
            return;
        }
        const W = 1200, H = 100;
        const t2x = (t) => (t / this.durationSec) * W;

        const sectionBlocks = (this.bundle.sections || []).map((s, i) => {
            const x = t2x(s.start), w = t2x(s.end) - x;
            const fill = i % 2 === 0 ? '#333' : '#3a3a3a';
            return `<rect x="${x}" y="0" width="${w}" height="20" fill="${fill}"/>
                    <text x="${x + 4}" y="14" fill="#aaa" font-size="10">${s.label}</text>`;
        }).join('');

        const beatTicks = (this.bundle.beats || []).map((b) => {
            const x = t2x(b.t);
            const tall = b.is_downbeat ? 18 : 10;
            return `<line x1="${x}" y1="20" x2="${x}" y2="${20 + tall}" stroke="#666" stroke-width="${b.is_downbeat ? 1.5 : 0.5}"/>`;
        }).join('');

        const kicks = (this.bundle.drums?.kick || []).map((d) => {
            const x = t2x(d.t);
            return `<circle cx="${x}" cy="50" r="2" fill="#e88"/>`;
        }).join('');

        const energy = this.bundle.global_energy;
        let energyPath = '';
        if (energy && energy.values && energy.values.length > 1) {
            const pts = energy.values.map((v, i) => {
                const t = i * energy.hop_sec;
                return `${t2x(t)},${90 - v * 30}`;
            }).join(' ');
            energyPath = `<polyline points="${pts}" stroke="#7ec97e" stroke-width="1" fill="none"/>`;
        }

        this.innerHTML = `
            <svg class="cue-scrubber-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
                ${sectionBlocks}
                ${beatTicks}
                ${kicks}
                ${energyPath}
                <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" id="scrub-hit"/>
            </svg>
        `;
        this.querySelector('#scrub-hit').addEventListener('click', (e) => {
            const rect = e.target.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const t = (x / rect.width) * this.durationSec;
            this.dispatchEvent(new CustomEvent('scrubber-seek', {
                detail: { t }, bubbles: true,
            }));
        });
    }
}

customElements.define('cue-scrubber', CueScrubber);
```

- [ ] **Step 2: Add the `GET /api/project/bundle?path=` endpoint**

In `cedartoy/server/api/project.py` (from Plan B-1), append:

```python
import json as _json

@router.get("/bundle")
def project_bundle(path: str) -> dict:
    """Return the bundle JSON at a server-local path."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="bundle not found")
    return _json.loads(p.read_text(encoding="utf-8"))
```

And add a test in `tests/test_project_route.py`:

```python
def test_project_bundle_returns_parsed_json(client, tmp_path):
    folder = tmp_path / "song"
    _seed(folder)
    bundle_path = folder / "song.musicue.json"
    resp = client.get("/api/project/bundle", params={"path": str(bundle_path)})
    assert resp.status_code == 200
    assert resp.json()["schema_version"] == "1.0"
```

- [ ] **Step 3: Mount the scrubber under the preview**

In `web/js/components/preview-panel.js` (or its template / index.html mount), add `<cue-scrubber></cue-scrubber>` directly below the canvas. Add a listener for `scrubber-seek` that calls the existing seek-to-time logic of the preview player.

- [ ] **Step 4: CSS**

```css
.cue-scrubber-svg {
    width: 100%; height: 100px;
    background: #1a1a1a;
    cursor: crosshair;
    display: block;
    margin-top: 4px;
}
.cue-scrubber-empty {
    padding: 10px; color: #666; font-size: 12px;
}
```

- [ ] **Step 5: Smoke**

Load a project with a bundle, verify the scrubber renders section bars, beat ticks, kick dots, and the energy curve; click somewhere on the timeline → preview jumps to that time (assuming the preview-panel seek wiring is in place).

- [ ] **Step 6: Commit**

```bash
git add web/js/components/cue-scrubber.js \
        web/js/components/preview-panel.js \
        cedartoy/server/api/project.py \
        tests/test_project_route.py \
        web/css/components.css
git commit -m "feat(ui): cue-scrubber timeline with click-to-seek"
```

---

## Task 7: Uniform read-out under the scrubber

**Files:**
- Modify: `web/js/components/cue-scrubber.js`

- [ ] **Step 1: Add a read-out element that updates per preview-frame**

```javascript
// In cue-scrubber.js render(), append after the SVG:
this.innerHTML += `
    <div class="cue-scrubber-readout" id="readout">
        iBpm — &nbsp; iBeat — &nbsp; iBar — &nbsp; iEnergy — &nbsp; iSectionEnergy —
    </div>
`;
```

Listen for `preview-frame` events emitted by `preview-panel.js` (or fall back to a `requestAnimationFrame` loop reading `preview-panel`'s current time):

```javascript
document.addEventListener('preview-frame', (e) => {
    const t = e.detail.timeSec;
    this._renderReadoutAt(t);
});

_renderReadoutAt(t) {
    if (!this.bundle) return;
    const bpm = this.bundle.tempo?.bpm_global ?? 0;
    const beats = this.bundle.beats || [];
    let beatPhase = 0, bar = 0;
    for (let i = 0; i < beats.length - 1; i++) {
        if (beats[i].t <= t && t < beats[i+1].t) {
            beatPhase = (t - beats[i].t) / (beats[i+1].t - beats[i].t);
            bar = beats[i].bar ?? 0;
            break;
        }
    }
    let energy = 0;
    const ge = this.bundle.global_energy;
    if (ge && ge.values && ge.hop_sec) {
        const idx = Math.min(Math.floor(t / ge.hop_sec), ge.values.length - 1);
        energy = ge.values[idx] ?? 0;
    }
    let sectionEnergy = 0;
    for (const s of (this.bundle.sections || [])) {
        if (s.start <= t && t < s.end) { sectionEnergy = s.energy_rank ?? 0; break; }
    }
    this.querySelector('#readout').textContent =
        `iBpm ${bpm.toFixed(0)}  iBeat ${beatPhase.toFixed(2)}  ` +
        `iBar ${bar}  iEnergy ${energy.toFixed(2)}  ` +
        `iSectionEnergy ${sectionEnergy.toFixed(2)}`;
}
```

If `preview-panel.js` doesn't already emit `preview-frame`, add it: emit on every render-loop tick with `{ timeSec: currentPlaybackTime }`.

- [ ] **Step 2: Smoke**

Play back the preview, verify the read-out updates live as the playhead moves.

- [ ] **Step 3: Commit**

```bash
git add web/js/components/cue-scrubber.js web/js/components/preview-panel.js
git commit -m "feat(ui): live uniform read-out under the cue scrubber"
```

---

## Task 8: Manual cross-app smoke + history-recording hook

**Files:**
- Modify: `cedartoy/server/api/render.py` (or wherever render-job completion lives)

- [ ] **Step 1: Hook history recording when a render job completes**

Find the function that finalizes a render job and add (at success):

```python
from cedartoy.render_estimate import record_history

# inside job-complete handler:
mean_frame_time = (total_seconds_elapsed) / max(1, job.frames_rendered)
record_history(
    shader_basename=Path(job.shader).stem,
    width=job.width, height=job.height,
    mean_frame_time=mean_frame_time,
)
```

If the codebase doesn't yet expose those values at job-completion time, surface them via the existing JobManager record fields — add a small `_record_run` helper invoked from the success branch.

- [ ] **Step 2: Manual smoke**

1. Run a 0.05s render of a known shader (e.g. `auroras`).
2. After it completes, inspect `~/.cedartoy/render_history.json` and confirm `mean_frame_time` is populated.
3. Re-open the UI; the output-panel estimate should now show real numbers (and "no prior render data" hint should disappear).

- [ ] **Step 3: Commit**

```bash
git add cedartoy/server/api/render.py
git commit -m "feat(estimate): record mean_frame_time per render for future estimates"
```

---

## Done

After Task 8:

- Cue scrubber renders sections/beats/kicks/energy from the loaded bundle.
- Click-to-seek + live uniform read-out makes "is the shader reacting where I expect?" answerable in seconds.
- `/api/render/estimate` powers a live estimate in stage [3] and gates long renders with a confirm modal.
- Completed renders feed history back into the estimator, sharpening future predictions.

Plan C (reactivity authoring) is independent of this work and can land before or after.
