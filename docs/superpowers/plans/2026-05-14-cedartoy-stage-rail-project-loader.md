# CedarToy Stage Rail + Project Loader Implementation Plan (B-1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-page config form with a 4-stage rail (Project → Shader → Output → Render) and add a project-loader that resolves any file inside a portable folder produced by MusiCue's `send-to-cedartoy`.

**Architecture:** A new pure `cedartoy/project.py` module resolves any file/folder path to a `CedarToyProject` dataclass with validated audio/bundle/stems/manifest. A new `POST /api/project/load` endpoint surfaces it to the web UI. The existing single `config-editor` component is decomposed into per-stage panels mounted under a new `stage-rail` component. The render pipeline (`RenderJob`, `Renderer`) is unchanged — this is front-end reorganization + one new backend endpoint.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, vanilla JS web components, existing CSS.

**Spec:** `docs/superpowers/specs/2026-05-14-musicue-cedartoy-holistic-design.md` (§ Part B, stages [1]–[3]).

---

## File map

**Create:**
- `cedartoy/project.py` — `load_project()`, `CedarToyProject` dataclass.
- `cedartoy/server/api/project.py` — `POST /api/project/load` router.
- `web/js/components/stage-rail.js` — top stage navigation.
- `web/js/components/project-panel.js` — stage [1] body.
- `web/js/components/output-panel.js` — stage [3] body (spherical-first output preset).
- `tests/test_project_loader.py` — loader unit tests.
- `tests/test_project_route.py` — HTTP tests.

**Modify:**
- `web/js/components/config-editor.js` — shrink: shader params only; audio/output fields move into per-stage panels.
- `web/index.html` — mount stage rail, restructure layout.
- `web/css/components.css` — stage-rail + panel styles.
- `cedartoy/server/app.py` — register project router.

---

## Task 1: `CedarToyProject` dataclass + `discover_audio_in_folder` helper

**Files:**
- Create: `cedartoy/project.py`
- Create: `tests/test_project_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_loader.py
"""Unit tests for the CedarToy project-folder loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cedartoy.project import (
    CedarToyProject,
    discover_audio_in_folder,
    STEM_NAMES,
)


def test_discover_audio_finds_song_wav(tmp_path):
    (tmp_path / "song.wav").write_bytes(b"")
    assert discover_audio_in_folder(tmp_path) == tmp_path / "song.wav"


def test_discover_audio_returns_none_when_missing(tmp_path):
    assert discover_audio_in_folder(tmp_path) is None


def test_discover_audio_prefers_song_wav_over_other_wavs(tmp_path):
    (tmp_path / "other.wav").write_bytes(b"")
    (tmp_path / "song.wav").write_bytes(b"")
    assert discover_audio_in_folder(tmp_path) == tmp_path / "song.wav"


def test_discover_audio_falls_back_to_first_wav(tmp_path):
    (tmp_path / "track.wav").write_bytes(b"")
    assert discover_audio_in_folder(tmp_path) == tmp_path / "track.wav"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project_loader.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# cedartoy/project.py
"""Resolve a portable CedarToy project folder produced by MusiCue.

A project folder is the unit of portability — see the umbrella spec at
docs/superpowers/specs/2026-05-14-musicue-cedartoy-holistic-design.md.
Layout::

    <project>/
      song.wav                  audio
      song.musicue.json         bundle (optional in legacy folders)
      manifest.json             cedartoy-project/1 schema (optional)
      stems/                    drums.wav / bass.wav / vocals.wav / other.wav (optional)

load_project() accepts any path inside such a folder (the folder, the
audio file, the bundle, or a stem) and returns a CedarToyProject.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

STEM_NAMES = ("drums", "bass", "vocals", "other")


@dataclass
class CedarToyProject:
    folder: Path
    audio_path: Path | None
    bundle_path: Path | None
    stems_paths: dict[str, Path] = field(default_factory=dict)
    manifest: dict | None = None
    bundle_sha_matches_audio: bool | None = None
    warnings: list[str] = field(default_factory=list)


def discover_audio_in_folder(folder: Path) -> Path | None:
    """Find the canonical audio file in a project folder.

    Prefers song.wav. Falls back to the first .wav by name.
    """
    folder = Path(folder)
    song = folder / "song.wav"
    if song.exists():
        return song
    wavs = sorted(folder.glob("*.wav"))
    return wavs[0] if wavs else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project_loader.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/project.py tests/test_project_loader.py
git commit -m "feat(project): CedarToyProject dataclass + audio discovery helper"
```

---

## Task 2: `load_project()` — folder + audio + bundle + manifest

**Files:**
- Modify: `cedartoy/project.py`
- Modify: `tests/test_project_loader.py`

- [ ] **Step 1: Add the failing test**

Append:

```python
def _write_silent_wav(path: Path) -> None:
    import numpy as np
    import soundfile as sf
    sf.write(str(path), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")


def _seed_minimal_project(folder: Path, *, with_bundle=True, with_manifest=True,
                          bundle_sha: str | None = None) -> Path:
    """Create a minimal folder layout matching the MusiCue export contract."""
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "song.wav"
    _write_silent_wav(audio)
    if with_bundle:
        from cedartoy.project import compute_audio_sha256
        sha = bundle_sha or compute_audio_sha256(audio)
        (folder / "song.musicue.json").write_text(json.dumps({
            "schema_version": "1.0",
            "source_sha256": sha,
            "duration_sec": 0.25,
            "fps": 24.0,
            "tempo": {"bpm_global": 120.0},
            "beats": [],
            "sections": [],
            "drums": {},
            "midi": {},
            "midi_energy": {},
            "stems_energy": {},
            "global_energy": {"hop_sec": 0.04, "values": []},
            "cuesheet": {"schema_version": "1.0", "source_sha256": sha,
                         "grammar": "concert_visuals", "duration_sec": 0.25},
        }))
    if with_manifest:
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "cedartoy-project/1",
            "audio_filename": "song.wav",
            "original_audio": "song.wav",
            "grammar": "concert_visuals",
            "musicue_version": "0.4.1-test",
            "exported_at": "2026-05-14T00:00:00Z",
        }))
    return audio


def test_load_project_resolves_folder(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "my_song"
    _seed_minimal_project(folder)
    proj = load_project(folder)
    assert proj.folder == folder
    assert proj.audio_path == folder / "song.wav"
    assert proj.bundle_path == folder / "song.musicue.json"
    assert proj.manifest is not None
    assert proj.manifest["grammar"] == "concert_visuals"
    assert proj.bundle_sha_matches_audio is True


def test_load_project_resolves_audio_file_path(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "my_song"
    _seed_minimal_project(folder)
    proj = load_project(folder / "song.wav")
    assert proj.folder == folder
    assert proj.audio_path == folder / "song.wav"


def test_load_project_resolves_bundle_file_path(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "my_song"
    _seed_minimal_project(folder)
    proj = load_project(folder / "song.musicue.json")
    assert proj.folder == folder
    assert proj.bundle_path == folder / "song.musicue.json"


def test_load_project_legacy_folder_without_manifest(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "legacy"
    _seed_minimal_project(folder, with_manifest=False)
    proj = load_project(folder)
    assert proj.manifest is None
    assert proj.audio_path is not None
    assert proj.bundle_path is not None  # still loads


def test_load_project_audio_only(tmp_path):
    """Folder with audio but no bundle — raw-FFT-mode fallback."""
    from cedartoy.project import load_project
    folder = tmp_path / "audio_only"
    _seed_minimal_project(folder, with_bundle=False, with_manifest=False)
    proj = load_project(folder)
    assert proj.audio_path is not None
    assert proj.bundle_path is None
    assert proj.bundle_sha_matches_audio is None


def test_load_project_warns_on_sha_mismatch(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "mismatch"
    _seed_minimal_project(folder, bundle_sha="0" * 64)
    proj = load_project(folder)
    assert proj.bundle_sha_matches_audio is False
    assert any("sha" in w.lower() for w in proj.warnings)


def test_load_project_includes_stems(tmp_path):
    from cedartoy.project import load_project
    folder = tmp_path / "with_stems"
    _seed_minimal_project(folder)
    (folder / "stems").mkdir()
    for name in ("drums", "bass", "vocals", "other"):
        _write_silent_wav(folder / "stems" / f"{name}.wav")
    proj = load_project(folder)
    assert set(proj.stems_paths) == {"drums", "bass", "vocals", "other"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_project_loader.py -v`
Expected: 6 new tests FAIL (`compute_audio_sha256` / `load_project` not defined).

- [ ] **Step 3: Implement the loader**

Append to `cedartoy/project.py`:

```python
import hashlib
import json
import logging

_logger = logging.getLogger(__name__)


def compute_audio_sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def _resolve_folder(target: Path) -> Path:
    """Treat target as the project folder if it's a directory; else its parent."""
    target = Path(target).resolve()
    return target if target.is_dir() else target.parent


def load_project(target: Path) -> CedarToyProject:
    """Resolve any path inside a project folder to a CedarToyProject.

    Accepts a folder, an audio file, a bundle file, or a stem file. Walks
    up to the containing folder, locates audio/bundle/manifest/stems, and
    cross-checks the bundle sha against the audio.
    """
    folder = _resolve_folder(Path(target))
    warnings: list[str] = []

    audio_path = discover_audio_in_folder(folder)
    bundle_path = folder / "song.musicue.json"
    if not bundle_path.exists():
        bundle_path = None

    manifest: dict | None = None
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            warnings.append(f"manifest.json unreadable: {e}")
            manifest = None

    stems_paths: dict[str, Path] = {}
    stems_dir = folder / "stems"
    if stems_dir.is_dir():
        for name in STEM_NAMES:
            p = stems_dir / f"{name}.wav"
            if p.exists():
                stems_paths[name] = p

    sha_match: bool | None = None
    if audio_path is not None and bundle_path is not None:
        try:
            audio_sha = compute_audio_sha256(audio_path)
            bundle_doc = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle_sha = bundle_doc.get("source_sha256")
            sha_match = audio_sha == bundle_sha
            if not sha_match:
                warnings.append(
                    f"bundle source_sha256 ({bundle_sha[:12]}…) does not "
                    f"match audio sha ({audio_sha[:12]}…); using anyway"
                )
        except Exception as e:
            warnings.append(f"sha check failed: {e}")

    return CedarToyProject(
        folder=folder,
        audio_path=audio_path,
        bundle_path=bundle_path,
        stems_paths=stems_paths,
        manifest=manifest,
        bundle_sha_matches_audio=sha_match,
        warnings=warnings,
    )
```

- [ ] **Step 4: Run all loader tests**

Run: `pytest tests/test_project_loader.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/project.py tests/test_project_loader.py
git commit -m "feat(project): load_project() resolves project folder from any inside file"
```

---

## Task 3: `POST /api/project/load` endpoint

**Files:**
- Create: `cedartoy/server/api/project.py`
- Create: `tests/test_project_route.py`
- Modify: `cedartoy/server/app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_route.py
"""HTTP tests for the project-load endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def _seed(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "song.wav"
    sf.write(str(audio), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    from cedartoy.project import compute_audio_sha256
    sha = compute_audio_sha256(audio)
    (folder / "song.musicue.json").write_text(json.dumps({
        "schema_version": "1.0", "source_sha256": sha, "duration_sec": 0.25,
        "fps": 24.0, "tempo": {"bpm_global": 120.0}, "beats": [],
        "sections": [], "drums": {}, "midi": {}, "midi_energy": {},
        "stems_energy": {}, "global_energy": {"hop_sec": 0.04, "values": []},
        "cuesheet": {"schema_version": "1.0", "source_sha256": sha,
                     "grammar": "concert_visuals", "duration_sec": 0.25},
    }))
    (folder / "manifest.json").write_text(json.dumps({
        "schema": "cedartoy-project/1", "audio_filename": "song.wav",
        "original_audio": "song.wav", "grammar": "concert_visuals",
        "musicue_version": "0.4.1-test", "exported_at": "2026-05-14T00:00:00Z",
    }))
    return audio


def test_project_load_returns_project(client, tmp_path):
    folder = tmp_path / "song"
    _seed(folder)
    resp = client.post("/api/project/load", json={"path": str(folder)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["folder"] == str(folder.resolve())
    assert body["audio_path"].endswith("song.wav")
    assert body["bundle_path"].endswith("song.musicue.json")
    assert body["manifest"]["grammar"] == "concert_visuals"
    assert body["bundle_sha_matches_audio"] is True
    assert body["warnings"] == []


def test_project_load_404_when_path_missing(client, tmp_path):
    resp = client.post("/api/project/load",
                       json={"path": str(tmp_path / "nope")})
    assert resp.status_code == 404


def test_project_load_resolves_audio_path(client, tmp_path):
    folder = tmp_path / "song"
    audio = _seed(folder)
    resp = client.post("/api/project/load", json={"path": str(audio)})
    assert resp.status_code == 200
    assert resp.json()["folder"] == str(folder.resolve())
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_project_route.py -v`
Expected: 405 / 404 — route not registered.

- [ ] **Step 3: Implement the router**

```python
# cedartoy/server/api/project.py
"""Project-load endpoint: resolves any path inside a project folder."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cedartoy.project import load_project

router = APIRouter()


class ProjectLoadRequest(BaseModel):
    path: str = Field(..., description="Folder, audio, bundle, or stem path.")


@router.post("/load")
def project_load(body: ProjectLoadRequest) -> dict:
    p = Path(body.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {p}")
    proj = load_project(p)
    return {
        "folder": str(proj.folder),
        "audio_path": str(proj.audio_path) if proj.audio_path else None,
        "bundle_path": str(proj.bundle_path) if proj.bundle_path else None,
        "stems_paths": {k: str(v) for k, v in proj.stems_paths.items()},
        "manifest": proj.manifest,
        "bundle_sha_matches_audio": proj.bundle_sha_matches_audio,
        "warnings": proj.warnings,
    }
```

In `cedartoy/server/app.py`, register the router under `/api/project`:

```python
from .api import project as project_routes
app.include_router(project_routes.router, prefix="/api/project", tags=["project"])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_project_route.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/server/api/project.py cedartoy/server/app.py tests/test_project_route.py
git commit -m "feat(api): POST /api/project/load resolves project folder"
```

---

## Task 4: Stage rail component (UI shell only — empty stage panels)

**Files:**
- Create: `web/js/components/stage-rail.js`
- Modify: `web/index.html`
- Modify: `web/css/components.css`

- [ ] **Step 1: Write the stage rail**

```javascript
// web/js/components/stage-rail.js
class StageRail extends HTMLElement {
    constructor() {
        super();
        this.activeStage = 'project';
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
    }

    render() {
        const stages = [
            { id: 'project', label: '1. Project' },
            { id: 'shader',  label: '2. Shader' },
            { id: 'output',  label: '3. Output' },
            { id: 'render',  label: '4. Render' },
        ];
        this.innerHTML = `
            <nav class="stage-rail">
                ${stages.map(s => `
                    <button class="stage-rail-item ${s.id === this.activeStage ? 'active' : ''}"
                            data-stage="${s.id}">${s.label}</button>
                    <span class="stage-rail-sep">›</span>
                `).join('').replace(/<span class="stage-rail-sep">›<\/span>$/, '')}
            </nav>
        `;
    }

    attachEventListeners() {
        this.querySelectorAll('.stage-rail-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.activeStage = e.target.dataset.stage;
                this.render();
                this.attachEventListeners();
                this.dispatchEvent(new CustomEvent('stage-change', {
                    detail: { stage: this.activeStage }, bubbles: true,
                }));
            });
        });
    }
}

customElements.define('stage-rail', StageRail);
```

- [ ] **Step 2: Add CSS**

Append to `web/css/components.css`:

```css
.stage-rail {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 8px 16px;
    background: #1a1a1a;
    border-bottom: 1px solid #333;
}
.stage-rail-item {
    background: transparent;
    color: #888;
    border: 1px solid transparent;
    padding: 6px 14px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
}
.stage-rail-item.active {
    color: #fff;
    border-color: #555;
    background: #2a2a2a;
}
.stage-rail-item:hover:not(.active) { color: #ccc; }
.stage-rail-sep { color: #555; padding: 0 2px; }
```

- [ ] **Step 3: Wire into `web/index.html`**

Insert `<stage-rail></stage-rail>` immediately above `<main class="app-main">` (around line 23):

```html
<stage-rail></stage-rail>
<main class="app-main">
```

And include the script (the existing `app.js` module loads components — append the new component import there, or add a `<script>` tag).

- [ ] **Step 4: Smoke**

Run the dev server and open the page. Verify the rail appears, the active stage highlights, and clicking a stage emits `stage-change` (visible in console if you add a temporary listener).

- [ ] **Step 5: Commit**

```bash
git add web/js/components/stage-rail.js web/index.html web/css/components.css
git commit -m "feat(ui): stage rail shell with 4 stages"
```

---

## Task 5: Project panel (stage [1]) — folder drop + read-out

**Files:**
- Create: `web/js/components/project-panel.js`
- Modify: `web/index.html`

- [ ] **Step 1: Write the panel**

```javascript
// web/js/components/project-panel.js
import { api } from '../api.js';

class ProjectPanel extends HTMLElement {
    constructor() {
        super();
        this.project = null;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
    }

    render() {
        const p = this.project;
        const banner = p && p.bundle_sha_matches_audio === false
            ? `<div class="project-warning">Bundle sha does not match audio — re-export from MusiCue.</div>` : '';
        const audioRow = p && p.audio_path
            ? `<div class="project-row">✔ Audio: <code>${p.audio_path.split(/[\\/]/).pop()}</code></div>`
            : `<div class="project-row project-row-missing">No audio detected</div>`;
        const bundleRow = p && p.bundle_path
            ? `<div class="project-row">✔ Bundle: schema ${p.manifest ? p.manifest.grammar : 'unknown grammar'}</div>`
            : `<div class="project-row project-row-info">No bundle — raw FFT mode</div>`;
        const stemsRow = p && Object.keys(p.stems_paths || {}).length
            ? `<div class="project-row">✔ Stems: ${Object.keys(p.stems_paths).join(' / ')}</div>`
            : (p ? `<div class="project-row project-row-info">No stems</div>` : '');

        this.innerHTML = `
            <div class="project-panel">
                <h3>Project</h3>
                <input type="text" id="project-path-input"
                       placeholder="Paste a folder, audio, or bundle path…"
                       value="${p ? p.folder : ''}">
                <button id="project-load-btn">Load</button>
                ${banner}
                ${audioRow}
                ${bundleRow}
                ${stemsRow}
            </div>
        `;
    }

    attachEventListeners() {
        this.querySelector('#project-load-btn')?.addEventListener('click', async () => {
            const path = this.querySelector('#project-path-input').value.trim();
            if (!path) return;
            try {
                const resp = await fetch('/api/project/load', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path }),
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                this.project = await resp.json();
                this.render();
                this.attachEventListeners();
                this.dispatchEvent(new CustomEvent('project-loaded', {
                    detail: this.project, bubbles: true,
                }));
            } catch (e) {
                alert(`Failed to load project: ${e.message}`);
            }
        });
    }
}

customElements.define('project-panel', ProjectPanel);
```

- [ ] **Step 2: Add CSS**

Append:

```css
.project-panel { padding: 16px; }
.project-panel h3 { margin-top: 0; }
.project-panel input { width: 100%; padding: 6px; margin-bottom: 8px; }
.project-row { padding: 4px 0; font-family: monospace; font-size: 13px; }
.project-row-missing { color: #f88; }
.project-row-info { color: #888; }
.project-warning { background: #4a1a1a; color: #fcc; padding: 8px; border-radius: 4px; margin: 8px 0; }
```

- [ ] **Step 3: Mount it conditionally**

In `web/index.html`, replace the existing `<section class="config-editor-panel">` body with stage-conditional panels — a wrapper that shows/hides children based on which stage is active. Simplest approach: add a `<div id="stage-panels">` and let JS toggle visibility based on the `stage-change` event from the rail.

```html
<section class="config-editor-panel">
    <div id="stage-panels">
        <div data-stage="project"><project-panel></project-panel></div>
        <div data-stage="shader" hidden><config-editor></config-editor></div>
        <div data-stage="output" hidden><output-panel></output-panel></div>
        <div data-stage="render" hidden><!-- render-panel stays in footer --></div>
    </div>
</section>
```

In `web/js/app.js`, wire the visibility toggle:

```javascript
document.addEventListener('stage-change', (e) => {
    document.querySelectorAll('#stage-panels > div').forEach(d => {
        d.hidden = d.dataset.stage !== e.detail.stage;
    });
});
```

- [ ] **Step 4: Smoke**

Open the UI, type a project folder path from a previous MusiCue export into the project-panel input, click Load, verify rows light up correctly.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/project-panel.js web/index.html web/css/components.css web/js/app.js
git commit -m "feat(ui): project-panel for stage [1] with folder loading"
```

---

## Task 6: Output panel (stage [3]) — spherical-first presets + estimate placeholder

**Files:**
- Create: `web/js/components/output-panel.js`
- Modify: `web/index.html` (already references `<output-panel>`)

- [ ] **Step 1: Write the panel**

The output panel surfaces resolution, FPS, output preset (equirect / LL180 / flat), tiling, and format. It writes back into the same `config` object the existing `config-editor` already manages — coordinate via the existing `config-change` event.

```javascript
// web/js/components/output-panel.js
class OutputPanel extends HTMLElement {
    constructor() {
        super();
        this.config = window.cedartoyConfig || {};
    }

    connectedCallback() {
        document.addEventListener('config-change', (e) => {
            this.config = e.detail;
            this.render();
        });
        this.render();
        this.attachEventListeners();
    }

    render() {
        const preset = this.config.camera_mode || 'equirect';
        this.innerHTML = `
            <div class="output-panel">
                <h3>Output</h3>
                <label>Output preset</label>
                <select id="output-preset">
                    <option value="equirect" ${preset==='equirect'?'selected':''}>Equirectangular 2:1 (recommended)</option>
                    <option value="ll180" ${preset==='ll180'?'selected':''}>LL180 dome</option>
                    <option value="2d" ${preset==='2d'?'selected':''}>Flat 16:9 (preview / test only)</option>
                </select>

                <label>Resolution</label>
                <input id="out-width" type="number" value="${this.config.width||1920}">
                <span>x</span>
                <input id="out-height" type="number" value="${this.config.height||1080}">
                <button id="apply-preset">Apply preset</button>

                <label>FPS</label>
                <input id="out-fps" type="number" value="${this.config.fps||60}">

                <label>Tiling</label>
                <input id="out-tiles-x" type="number" min="1" value="${this.config.tiles_x||1}">
                <span>x</span>
                <input id="out-tiles-y" type="number" min="1" value="${this.config.tiles_y||1}">

                <label>Format</label>
                <select id="out-format">
                    <option value="png" ${this.config.default_output_format==='png'?'selected':''}>PNG 8-bit</option>
                    <option value="exr-16f">EXR 16-bit float</option>
                    <option value="exr-32f">EXR 32-bit float</option>
                </select>

                <div id="render-estimate" class="form-hint">Estimate: pending (Plan B-2)</div>
            </div>
        `;
    }

    attachEventListeners() {
        this.querySelector('#apply-preset')?.addEventListener('click', () => {
            const p = this.querySelector('#output-preset').value;
            if (p === 'equirect') {
                this.querySelector('#out-width').value = 8192;
                this.querySelector('#out-height').value = 4096;
            } else if (p === 'll180') {
                this.querySelector('#out-width').value = 4096;
                this.querySelector('#out-height').value = 4096;
            } else if (p === '2d') {
                this.querySelector('#out-width').value = 1920;
                this.querySelector('#out-height').value = 1080;
            }
            this._fire();
        });
        ['#output-preset', '#out-width', '#out-height', '#out-fps',
         '#out-tiles-x', '#out-tiles-y', '#out-format'].forEach(sel => {
            this.querySelector(sel)?.addEventListener('change', () => this._fire());
        });
    }

    _fire() {
        const update = {
            camera_mode: this.querySelector('#output-preset').value,
            width: parseInt(this.querySelector('#out-width').value),
            height: parseInt(this.querySelector('#out-height').value),
            fps: parseInt(this.querySelector('#out-fps').value),
            tiles_x: parseInt(this.querySelector('#out-tiles-x').value),
            tiles_y: parseInt(this.querySelector('#out-tiles-y').value),
            default_output_format: this.querySelector('#out-format').value,
        };
        Object.assign(this.config, update);
        this.dispatchEvent(new CustomEvent('config-change', {
            detail: this.config, bubbles: true,
        }));
    }
}

customElements.define('output-panel', OutputPanel);
```

- [ ] **Step 2: Smoke**

Load the UI, switch to stage [3], pick the equirect preset, click Apply preset, verify the width/height jump to 8192x4096.

- [ ] **Step 3: Commit**

```bash
git add web/js/components/output-panel.js
git commit -m "feat(ui): output-panel with spherical-first presets"
```

---

## Task 7: Shrink `config-editor.js` — remove audio/bundle/output fields now owned by stage panels

**Files:**
- Modify: `web/js/components/config-editor.js`

The `Audio & MusiCue Bundle` section moves into `project-panel.js` (which will own bundle wiring once it auto-feeds the bundle path into render jobs — see follow-up). The Output Format and Tiling sections move into `output-panel.js`. Width/Height/FPS/Camera Mode/Camera Tilt move into `output-panel.js`. Shader path + dynamic shader parameters stay in `config-editor.js`.

- [ ] **Step 1: Remove the migrated sections**

Delete the following from `config-editor.js` `render()`:

- `Output Directory` form-group → keep (rendering output dir is render-job specific)
- `Width`, `Height`, `FPS`, `Duration`, `Camera Mode`, `Camera Tilt` form-groups → delete (now in `output-panel`)
- `Tiling (High-Res)` section → delete (now in `output-panel`)
- `Quality` section → delete (now in `output-panel`)
- `Audio & MusiCue Bundle` section → delete (now in `project-panel`)
- `Output Format` section → delete (now in `output-panel`)

Leave: the shader path field, shader parameters container, output directory, and the Export button.

- [ ] **Step 2: Add a project-loaded listener**

When `project-panel` fires `project-loaded`, automatically populate `this.config.audio_path` and `this.config.bundle_path` so the render job picks them up without manual paste:

```javascript
document.addEventListener('project-loaded', (e) => {
    this.config.audio_path = e.detail.audio_path;
    this.config.bundle_path = e.detail.bundle_path;
    this.saveToLocalStorage();
});
```

- [ ] **Step 3: Smoke**

Verify the UI still renders, that switching stages shows different fields, and that loading a project in stage [1] makes the audio show up downstream in render jobs.

- [ ] **Step 4: Commit**

```bash
git add web/js/components/config-editor.js
git commit -m "refactor(ui): shrink config-editor; fields moved to stage panels"
```

---

## Task 8: End-to-end smoke test

**Files:**
- Modify: `tests/test_project_route.py`

- [ ] **Step 1: Add the integration test**

```python
def test_project_load_for_send_to_cedartoy_folder(client, tmp_path):
    """Verify CedarToy reads a folder produced by MusiCue's send-to-cedartoy."""
    # Seed a folder using the same layout MusiCue would emit.
    folder = tmp_path / "exported"
    _seed(folder)
    (folder / "stems").mkdir()
    for n in ("drums", "bass", "vocals", "other"):
        sf.write(str(folder / "stems" / f"{n}.wav"),
                 np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")

    resp = client.post("/api/project/load", json={"path": str(folder)})
    body = resp.json()
    assert resp.status_code == 200
    assert set(body["stems_paths"]) == {"drums", "bass", "vocals", "other"}
    assert body["manifest"]["grammar"] == "concert_visuals"
```

- [ ] **Step 2: Run all project tests**

Run: `pytest tests/test_project_loader.py tests/test_project_route.py -v`
Expected: ALL PASS.

- [ ] **Step 3: Manual cross-app smoke**

In a terminal:

```bash
# Produce a portable folder via MusiCue.
musicue send-to-cedartoy <song.wav> --output exports/test_song

# Launch CedarToy.
python -m cedartoy.cli ui

# In the browser: stage [1], paste `exports/test_song`, click Load.
# Verify all three rows green; switch to stage [3] and pick equirect.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_project_route.py
git commit -m "test(project): end-to-end load of a send-to-cedartoy folder"
```

---

## Done

After Task 8 the stage rail UI is shippable:

- `cedartoy/project.py` + `POST /api/project/load` resolve any path inside a MusiCue export folder.
- Stage rail UI (Project → Shader → Output → Render) replaces the single-page form.
- The Output panel surfaces spherical presets (equirect / LL180 / flat) as first-class options.
- Plan B-2 (cue scrubber + render estimate) lands next; the `#render-estimate` placeholder in `output-panel.js` is its drop-in point.
- Plan C (reactivity prompt button) lands in stage [2].
