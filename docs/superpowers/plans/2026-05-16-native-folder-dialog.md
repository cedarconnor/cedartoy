# Plan C — Native folder dialog

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the paste-a-path text input on Stage 1 with a native OS folder picker dialog (Browse… button), so the user can navigate to a CedarToy project folder visually instead of typing/pasting a path.

**Architecture:** Add a new server endpoint `POST /api/dialog/pick-folder` that opens a native OS folder picker using Python's stdlib `tkinter.filedialog.askdirectory`. The dialog runs in a worker thread (FastAPI's default for sync routes), so it blocks only that request — the rest of the server stays responsive. The browser's `project-panel` gains a Browse… button that posts to the endpoint, fills the input with the returned absolute path, and triggers the existing Load Project flow. The text input stays — pasting and keyboard workflows aren't taken away.

**Tech Stack:** Python stdlib `tkinter` (no new dependency), FastAPI, vanilla JS custom elements.

**Spec:** `docs/superpowers/specs/2026-05-16-cedartoy-ux-sync-pass.md` §§ 6.2, 7.5, 9 (the "Native dialog unavailable" row), 11 (Plan C).

---

## File structure

```
Server (Python / FastAPI)
├── cedartoy/server/api/dialog.py        [new]   POST /pick-folder using tkinter
├── cedartoy/server/app.py               [modify] include dialog.router under /api/dialog
└── tests/test_dialog_route.py           [new]   happy / cancel / 503 via mocked tkinter

Web (vanilla JS components, in web/js/components/)
├── project-panel.js                     [modify] + Browse… button, +disabled-on-503 path
├── ../app.js                            [modify] bump project-panel cache-bust, bump index.html
└── ../../index.html                     [modify] bump app.js cache-bust
```

The dialog endpoint is pure isolation: it knows nothing about projects, manifests, or shas — it just returns the chosen path or `null` on cancel. The browser is responsible for calling `/api/project/load` after a successful pick.

---

## Task 1 — `POST /api/dialog/pick-folder` server endpoint

**Repo:** `D:\cedartoy`

**Files:**
- Create: `cedartoy/server/api/dialog.py`
- Modify: `cedartoy/server/app.py`
- Create: `tests/test_dialog_route.py`

- [ ] **Step 1: Add failing tests via mocked tkinter**

Create `tests/test_dialog_route.py` with:

```python
"""HTTP tests for POST /api/dialog/pick-folder. tkinter is mocked so the
test suite doesn't pop a real dialog (and runs in headless CI)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_pick_folder_returns_chosen_path(client, tmp_path):
    chosen = str(tmp_path)
    with patch("cedartoy.server.api.dialog._ask_directory", return_value=chosen):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 200
    assert resp.json() == {"path": chosen}


def test_pick_folder_returns_null_path_when_user_cancels(client):
    # tkinter returns "" (empty string) when the user cancels.
    with patch("cedartoy.server.api.dialog._ask_directory", return_value=""):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 200
    assert resp.json() == {"path": None}


def test_pick_folder_accepts_initial_dir(client, tmp_path):
    chosen = str(tmp_path / "deeper")
    with patch("cedartoy.server.api.dialog._ask_directory", return_value=chosen) as m:
        resp = client.post(
            "/api/dialog/pick-folder",
            json={"initial_dir": str(tmp_path)},
        )
    assert resp.status_code == 200
    assert resp.json() == {"path": chosen}
    # _ask_directory was called with the requested initial dir
    m.assert_called_once_with(initial_dir=str(tmp_path))


def test_pick_folder_503_when_no_display(client):
    # tkinter raises TclError when there's no display. We surface 503.
    import tkinter as tk
    with patch(
        "cedartoy.server.api.dialog._ask_directory",
        side_effect=tk.TclError("no display name and no $DISPLAY environment variable"),
    ):
        resp = client.post("/api/dialog/pick-folder", json={})
    assert resp.status_code == 503
    assert "display" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest D:/cedartoy/tests/test_dialog_route.py -v`
Expected: 4 FAIL with `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Create the dialog router**

Create `cedartoy/server/api/dialog.py` with:

```python
"""Native OS folder picker, surfaced as POST /api/dialog/pick-folder.

The actual dialog runs in tkinter. tkinter is part of Python's stdlib so
no extra dependency is needed. FastAPI runs synchronous route handlers
in a worker thread, so the dialog blocks only this request — other
requests keep flowing.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class PickFolderRequest(BaseModel):
    initial_dir: str | None = Field(default=None)


def _ask_directory(*, initial_dir: str | None = None) -> str:
    """Open a native folder picker and return the chosen path.

    Returns "" when the user cancels (matching tkinter's contract).
    Raises tk.TclError when no display is available (headless / CI).
    Isolated as a module-level function so tests can mock it cleanly.
    """
    # tkinter requires a root window. Create + hide + destroy to avoid
    # leaving a leaked Tk instance behind.
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        result = filedialog.askdirectory(
            parent=root,
            title="Pick a CedarToy project folder",
            initialdir=initial_dir or None,
            mustexist=True,
        )
        return result or ""
    finally:
        root.destroy()


@router.post("/pick-folder")
def pick_folder(body: PickFolderRequest) -> dict:
    try:
        chosen = _ask_directory(initial_dir=body.initial_dir)
    except tk.TclError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Native dialog unavailable (no display): {e}",
        ) from e
    return {"path": chosen if chosen else None}
```

- [ ] **Step 4: Mount the router**

Open `cedartoy/server/app.py`. Find:

```python
from .api import shaders, config, audio, render, files, project, reactivity
```

Replace with:

```python
from .api import shaders, config, audio, render, files, project, reactivity, dialog
```

Find:

```python
app.include_router(reactivity.router, prefix="/api/reactivity", tags=["reactivity"])
```

Add after it:

```python
app.include_router(dialog.router, prefix="/api/dialog", tags=["dialog"])
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_dialog_route.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git -C D:/cedartoy add cedartoy/server/api/dialog.py cedartoy/server/app.py tests/test_dialog_route.py
git -C D:/cedartoy commit -m "feat(api): POST /api/dialog/pick-folder opens a native OS folder picker

Uses tkinter.filedialog.askdirectory (stdlib, no new dep). Returns
{path: '<abs>'} on pick, {path: null} on cancel, 503 when no display."
```

---

## Task 2 — Browse… button in project-panel

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/project-panel.js`
- Modify: `web/js/app.js`
- Modify: `web/index.html`

- [ ] **Step 1: Read the current project-panel render block**

Re-acquaint yourself with the structure — there's an existing text input (`#project-path-input`) and a Load button (`#project-load-btn`). The Browse button slots between them.

- [ ] **Step 2: Add the Browse button and its handler**

Open `web/js/components/project-panel.js`. Replace the `render()` method body's input + button block:

```javascript
            <input type="text" id="project-path-input"
                   placeholder="D:\\path\\to\\my_song\\"
                   value="${p ? this._escape(p.folder) : ''}">
            <button class="btn btn-primary" id="project-load-btn"
                    ${this.loading ? 'disabled' : ''}>
                ${this.loading ? 'Loading…' : 'Load Project'}
            </button>
```

with:

```javascript
            <input type="text" id="project-path-input"
                   placeholder="D:\\path\\to\\my_song\\"
                   value="${p ? this._escape(p.folder) : ''}">
            <div style="display:flex;gap:6px;margin-top:4px;">
                <button class="btn btn-secondary" id="project-browse-btn"
                        ${this.loading ? 'disabled' : ''}>
                    Browse…
                </button>
                <button class="btn btn-primary" id="project-load-btn"
                        ${this.loading ? 'disabled' : ''}>
                    ${this.loading ? 'Loading…' : 'Load Project'}
                </button>
            </div>
```

In `attachEventListeners()`, after the existing `#project-load-btn` click handler, add a Browse handler. Replace the entire `attachEventListeners()` method with:

```javascript
    attachEventListeners() {
        this.querySelector('#project-load-btn')?.addEventListener('click', async () => {
            const input = this.querySelector('#project-path-input');
            const path = input?.value.trim();
            if (!path) return;
            await this._loadProject(path);
        });

        this.querySelector('#project-browse-btn')?.addEventListener('click', async () => {
            const initial_dir = this.querySelector('#project-path-input')?.value.trim() || null;
            try {
                const resp = await fetch('/api/dialog/pick-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ initial_dir }),
                });
                if (resp.status === 503) {
                    this.error = 'Native folder picker unavailable on this server (no display). Type or paste a path instead.';
                    this.render();
                    this.attachEventListeners();
                    return;
                }
                if (!resp.ok) {
                    const detail = await resp.json().catch(() => ({}));
                    throw new Error(detail.detail || `HTTP ${resp.status}`);
                }
                const { path } = await resp.json();
                if (!path) return;  // user cancelled
                this.querySelector('#project-path-input').value = path;
                await this._loadProject(path);
            } catch (e) {
                this.error = `Folder picker failed: ${e.message}`;
                this.render();
                this.attachEventListeners();
            }
        });
    }

    async _loadProject(path) {
        this.loading = true;
        this.error = null;
        this.render();
        this.attachEventListeners();
        try {
            const resp = await fetch('/api/project/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            if (!resp.ok) {
                const detail = await resp.json().catch(() => ({}));
                throw new Error(detail.detail || `HTTP ${resp.status}`);
            }
            this.project = await resp.json();
            this.dispatchEvent(new CustomEvent('project-loaded', {
                detail: this.project, bubbles: true,
            }));
        } catch (e) {
            this.error = `Failed to load project: ${e.message}`;
        } finally {
            this.loading = false;
            this.render();
            this.attachEventListeners();
        }
    }```

Notice the `_loadProject` helper extracted from the original Load button handler — it's shared by both buttons now.

- [ ] **Step 3: Bump cache-busts**

In `web/js/app.js`, change:

```javascript
import './components/project-panel.js?v=2';
```

to:

```javascript
import './components/project-panel.js?v=3';
```

In `web/index.html`, change:

```html
<script type="module" src="/js/app.js?v=5"></script>
```

to:

```html
<script type="module" src="/js/app.js?v=6"></script>
```

- [ ] **Step 4: Manual browser smoke test**

Start the UI if it isn't running:

```bash
python -m cedartoy.cli ui
```

Open `http://localhost:8080`. On Stage 1:
- Confirm the **Browse…** button appears next to **Load Project**.
- Click Browse… → a native OS folder picker dialog appears.
- Pick `D:/temp/cedartoy_browser_test_export` → dialog closes, path appears in the input, project loads automatically.
- Click Browse… again, hit Cancel in the dialog → no path change, no error.
- Verify pasting a path into the input + clicking Load Project still works (unchanged behavior).

- [ ] **Step 5: Commit**

```bash
git -C D:/cedartoy add web/js/components/project-panel.js web/js/app.js web/index.html
git -C D:/cedartoy commit -m "feat(project-panel): Browse… button opens native folder dialog

Calls POST /api/dialog/pick-folder and, on a successful pick, fills the
text input and runs the existing load flow. Falls back gracefully when
the server is headless (503 → inline error message; user can still paste
a path). Extracts _loadProject helper shared by Browse and Load."
```

---

## Task 3 — Push CedarToy main

**Repo:** `D:\cedartoy`

- [ ] **Step 1: Push**

```bash
git -C D:/cedartoy push origin main
```

Expected: push succeeds.

---

## Self-review checklist

- [x] **Spec coverage:**
  - § 6.2 `POST /api/dialog/pick-folder` (initial_dir, 200 on pick/cancel, 503 on no display) → Task 1.
  - § 7.5 `<project-panel>` gains a Browse… button calling that endpoint, falls back to text input on failure → Task 2.
  - § 9 row "Native folder picker unavailable" → Task 2 (503 → inline error, text input stays usable).
  - § 11 Plan C → this plan.
- [x] **Placeholder scan:** Every step has the literal code or shell commands. No "similar to" or "TBD".
- [x] **Type consistency:** Request shape `{initial_dir: str | None}` consistent between server (Task 1) and JS caller (Task 2). Response shape `{path: str | null}` consistent. Helper function name `_ask_directory` consistent between implementation and test mock target.
- [x] **Scope:** 3 tasks (server + UI + push), single repo, ~20 min. Each task is one focused commit.
