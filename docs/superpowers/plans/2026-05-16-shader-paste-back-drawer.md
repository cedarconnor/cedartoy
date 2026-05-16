# Plan E — Shader paste-back drawer + Claude fix-it loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Claude round-trip — let the user paste Claude's reply into a drawer in Stage 2, hit Apply, and see the new `_reactive.glsl` running in the preview. When compilation fails, the same drawer surfaces the WebGL error log and a "Copy fix-it prompt" button to feed the error back to Claude.

**Architecture:** A new `<shader-reactivity-drawer>` lives in Stage 2 next to the existing "Make this shader reactive ▸" button. It owns three things: (1) a textarea for Claude's full reply, (2) an Apply button that POSTs to a new `/api/shader/apply` endpoint (atomic-rename write of `<name>_reactive.glsl`), and (3) a Copy-fix-it button that calls `GET /api/reactivity/fixit-prompt` when compilation fails. Preview-panel emits a new `shader-compile-result` event after every WebGL compile, capturing concatenated vertex+fragment+link logs from `gl.getShaderInfoLog()` / `gl.getProgramInfoLog()`. The drawer listens for that event and flips between idle / clean / error states.

**Tech Stack:** FastAPI, vanilla JS custom elements, WebGL2's `gl.getShaderInfoLog()` / `gl.getProgramInfoLog()`, native clipboard API.

**Spec:** `docs/superpowers/specs/2026-05-16-cedartoy-ux-sync-pass.md` §§ 6.3, 6.4, 7.3 (preview-panel's new event), 7.7 (drawer), 8.C (apply flow), 9 (error rows), 11 (Plan E).

---

## File structure

```
Server (Python / FastAPI)
├── cedartoy/server/api/shader.py        [new]   POST /api/shader/apply (atomic-rename)
├── cedartoy/server/api/reactivity.py    [modify] + GET /api/reactivity/fixit-prompt
├── cedartoy/reactivity.py               [modify] + build_fixit_prompt(...)
├── cedartoy/server/app.py               [modify] include shader_apply router
└── tests/
    ├── test_shader_apply_route.py       [new]   sibling/overwrite/atomicity/400 tests
    ├── test_reactivity_module.py        [modify] + build_fixit_prompt tests
    └── test_reactivity_route.py         [modify] + fixit-prompt endpoint tests

Web (web/js/components/)
├── shader-reactivity-drawer.js          [new]   textarea + Apply + fix-it button + state
├── preview-panel.js                     [modify] emit shader-compile-result on every compile
├── ../app.js                            [modify] import drawer; bump cache-busts
└── ../../index.html                     [modify] add <shader-reactivity-drawer> inside Stage 2

Web (web/css/components.css)
└── components.css                       [modify] .reactivity-drawer styles
```

The drawer is the only new UI surface. It doesn't subclass or share state with config-editor — they're peers in Stage 2 that communicate only through DOM events (`shader-select`, `shader-compile-result`). This keeps both files small and replaceable.

---

## Task 1 — Server: `POST /api/shader/apply` with atomic-rename

**Repo:** `D:\cedartoy`

**Files:**
- Create: `cedartoy/server/api/shader_apply.py`
- Modify: `cedartoy/server/app.py`
- Create: `tests/test_shader_apply_route.py`

**Note on filename:** `shader.py` would collide with the existing `shaders.py` module on case-sensitive filesystems, and `shaders.py` already owns `/api/shaders/*`. Mounting the new endpoint at `/api/shader` (singular) avoids both clashes.

- [ ] **Step 1: Add failing tests**

Create `tests/test_shader_apply_route.py` with:

```python
"""HTTP tests for POST /api/shader/apply."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


# Shaders live in <repo>/shaders. Tests work against a temp shader so we
# don't leave files behind in the real shader directory.
SHADERS_DIR = Path(__file__).resolve().parent.parent / "shaders"


@pytest.fixture
def temp_shader():
    """Create a temp <name>.glsl in shaders/ and clean it + its _reactive sibling on teardown."""
    base_name = "test_apply_temp"
    base_path = SHADERS_DIR / f"{base_name}.glsl"
    base_path.write_text("// original\nvoid main() { gl_FragColor = vec4(1.0); }\n", encoding="utf-8")
    sibling = SHADERS_DIR / f"{base_name}_reactive.glsl"
    yield base_name, base_path, sibling
    base_path.unlink(missing_ok=True)
    sibling.unlink(missing_ok=True)


def test_shader_apply_sibling_writes_reactive_glsl(client, temp_shader):
    base_name, base_path, sibling = temp_shader
    glsl = "// reactive\nuniform float iEnergy;\nvoid main() {}\n"
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": glsl,
        "mode": "sibling",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["path"].endswith(f"{base_name}_reactive.glsl")
    assert sibling.read_text(encoding="utf-8") == glsl
    # Original untouched.
    assert "// original" in base_path.read_text(encoding="utf-8")


def test_shader_apply_overwrite_replaces_original(client, temp_shader):
    base_name, base_path, sibling = temp_shader
    glsl = "// overwritten\nvoid main() {}\n"
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": glsl,
        "mode": "overwrite",
    })
    assert resp.status_code == 200
    assert base_path.read_text(encoding="utf-8") == glsl
    assert not sibling.exists()


def test_shader_apply_rejects_empty_glsl(client, temp_shader):
    base_name, _, _ = temp_shader
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": "",
        "mode": "sibling",
    })
    assert resp.status_code == 400


def test_shader_apply_rejects_invalid_mode(client, temp_shader):
    base_name, _, _ = temp_shader
    resp = client.post("/api/shader/apply", json={
        "base": f"{base_name}.glsl",
        "glsl": "void main(){}",
        "mode": "explode",
    })
    assert resp.status_code in (400, 422)  # Pydantic returns 422 on enum violation


def test_shader_apply_404_when_base_missing(client):
    resp = client.post("/api/shader/apply", json={
        "base": "definitely_does_not_exist_5b8a.glsl",
        "glsl": "void main(){}",
        "mode": "sibling",
    })
    assert resp.status_code == 404


def test_shader_apply_rejects_path_traversal(client, temp_shader):
    """A base outside shaders/ via traversal must be rejected."""
    resp = client.post("/api/shader/apply", json={
        "base": "../etc/passwd",
        "glsl": "void main(){}",
        "mode": "sibling",
    })
    assert resp.status_code in (400, 403, 404)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest D:/cedartoy/tests/test_shader_apply_route.py -v`
Expected: 6 FAIL with 404 / route-not-found (endpoint doesn't exist yet).

- [ ] **Step 3: Create the endpoint module**

Create `cedartoy/server/api/shader_apply.py` with:

```python
"""POST /api/shader/apply — writes Claude's GLSL output to a shader file.

Atomic-rename pattern: write to a temp file in the same directory, then
os.replace() over the target. A failure mid-write leaves no half-baked
shader for the preview to compile against.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

SHADERS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "shaders"


class ApplyRequest(BaseModel):
    base: str = Field(..., description="Original shader filename (e.g. 'phantom_mode.glsl').")
    glsl: str = Field(..., description="Full GLSL source to write.")
    mode: Literal["sibling", "overwrite"] = "sibling"


def _atomic_write(target: Path, content: str) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".cedartoy-apply-", suffix=".glsl", dir=str(target.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


@router.post("/apply")
def shader_apply(body: ApplyRequest) -> dict:
    if not body.glsl.strip():
        raise HTTPException(status_code=400, detail="glsl is empty")

    # Resolve `base` and refuse to escape the shaders directory.
    candidate = (SHADERS_DIR / body.base).resolve()
    try:
        candidate.relative_to(SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="base outside shaders directory")

    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"base shader not found: {body.base}")

    if body.mode == "sibling":
        target = candidate.with_name(f"{candidate.stem}_reactive.glsl")
    else:
        target = candidate

    _atomic_write(target, body.glsl)
    # Return the path relative to the shaders/ dir (consumed by the browser).
    rel = target.relative_to(SHADERS_DIR.resolve()).as_posix()
    return {"path": f"shaders/{rel}"}
```

- [ ] **Step 4: Mount the router**

Open `cedartoy/server/app.py`. Find:

```python
from .api import shaders, config, audio, render, files, project, reactivity, dialog
```

Replace with:

```python
from .api import shaders, config, audio, render, files, project, reactivity, dialog
from .api import shader_apply
```

Then add after the existing `app.include_router(dialog.router, ...)` line:

```python
app.include_router(shader_apply.router, prefix="/api/shader", tags=["shader"])
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_shader_apply_route.py -v`
Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git -C D:/cedartoy add cedartoy/server/api/shader_apply.py cedartoy/server/app.py tests/test_shader_apply_route.py
git -C D:/cedartoy commit -m "feat(api): POST /api/shader/apply writes GLSL atomically

Sibling mode writes <base>_reactive.glsl (default; original untouched).
Overwrite mode replaces the original (caller's responsibility to gate
behind a confirm). Path-traversal rejected. Atomic-rename via temp file
+ os.replace() so a partial write never lands in shaders/."
```

---

## Task 2 — Server: `build_fixit_prompt()`

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `cedartoy/reactivity.py`
- Modify: `tests/test_reactivity_module.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_reactivity_module.py`:

```python
def test_build_fixit_prompt_contains_all_sections():
    """Fix-it prompt bundles original + broken + GL log + cookbook + directive."""
    from cedartoy.reactivity import build_fixit_prompt

    out = build_fixit_prompt(
        broken_glsl="void main(){iKick;}",       # the broken attempt
        gl_log="ERROR: 0:1: 'iKick' : undeclared identifier",
        original_glsl="void main(){gl_FragColor=vec4(1.0);}",
        cookbook="# Reactivity Cookbook\nkick_pulse_camera: …",
    )
    assert "iKick" in out
    assert "undeclared identifier" in out
    assert "gl_FragColor=vec4(1.0)" in out
    assert "kick_pulse_camera" in out
    assert "fix the compile error" in out.lower()
    # Sections are clearly delimited so Claude can parse them.
    assert "## Original shader" in out
    assert "## Broken attempt" in out
    assert "## Compile error" in out
    assert "## Reactivity cookbook" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest D:/cedartoy/tests/test_reactivity_module.py::test_build_fixit_prompt_contains_all_sections -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the function**

Open `cedartoy/reactivity.py`. Append after `build_reactivity_prompt`:

```python
def build_fixit_prompt(
    *,
    broken_glsl: str,
    gl_log: str,
    original_glsl: str,
    cookbook: str,
) -> str:
    """Build a Claude-ready prompt asking it to fix a broken reactive variant.

    The shape mirrors build_reactivity_prompt: clearly-labeled sections so
    Claude can return a single fenced GLSL block. The directive is explicit
    about preserving the prior reactivity goals so iterations don't regress.
    """
    return (
        "You wrote a reactive variant of a CedarToy GLSL shader, but it "
        "failed to compile in WebGL2. Fix the compile error while preserving "
        "the reactivity goals from the previous prompt.\n\n"
        "## Original shader\n```glsl\n"
        f"{original_glsl}\n```\n\n"
        "## Broken attempt\n```glsl\n"
        f"{broken_glsl}\n```\n\n"
        "## Compile error\n```\n"
        f"{gl_log}\n```\n\n"
        "## Reactivity cookbook\n"
        f"{cookbook}\n\n"
        "## Instructions\n"
        "- Return ONE fenced ```glsl block containing the corrected shader.\n"
        "- Keep the structure of the original; only fix the bug introduced "
        "by the reactive retrofit.\n"
        "- Preserve every reactivity idiom from the broken attempt that "
        "wasn't the actual source of the error.\n"
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_reactivity_module.py -v`
Expected: PASS (new test + all existing tests in file).

- [ ] **Step 5: Commit**

```bash
git -C D:/cedartoy add cedartoy/reactivity.py tests/test_reactivity_module.py
git -C D:/cedartoy commit -m "feat(reactivity): build_fixit_prompt() bundles broken GLSL + GL log

Mirrors build_reactivity_prompt's shape — labeled markdown sections so
Claude can parse them and return a single fenced GLSL block. The
directive explicitly preserves the prior reactivity goals so iterations
don't regress while fixing the compile error."
```

---

## Task 3 — Server: `GET /api/reactivity/fixit-prompt`

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `cedartoy/server/api/reactivity.py`
- Modify: `tests/test_reactivity_route.py`

- [ ] **Step 1: Inspect the existing prompt endpoint for reference**

Read `cedartoy/server/api/reactivity.py` and `tests/test_reactivity_route.py` to mirror the established pattern.

- [ ] **Step 2: Add failing tests**

Append to `tests/test_reactivity_route.py`:

```python
def test_fixit_prompt_returns_markdown(client, tmp_path):
    """POST a broken shader + log; receive a fix-it prompt back."""
    # The endpoint needs the original shader available in shaders/ to embed
    # alongside the broken attempt. We add a temp one.
    from cedartoy.server.api.shader_apply import SHADERS_DIR
    base = SHADERS_DIR / "fixit_test_temp.glsl"
    base.write_text("void main(){gl_FragColor=vec4(0.0);}", encoding="utf-8")
    try:
        resp = client.post(
            "/api/reactivity/fixit-prompt",
            json={
                "base": "fixit_test_temp.glsl",
                "broken_glsl": "void main(){iKick;}",
                "gl_log": "ERROR: 0:1: 'iKick' : undeclared identifier",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        prompt = body["prompt"]
        assert "iKick" in prompt
        assert "undeclared identifier" in prompt
        assert "gl_FragColor=vec4(0.0)" in prompt
        assert "kick_pulse_camera" in prompt  # cookbook content embedded
        assert "fix the compile error" in prompt.lower()
    finally:
        base.unlink(missing_ok=True)


def test_fixit_prompt_404_when_base_missing(client):
    resp = client.post(
        "/api/reactivity/fixit-prompt",
        json={
            "base": "nope_xyz.glsl",
            "broken_glsl": "void main(){}",
            "gl_log": "anything",
        },
    )
    assert resp.status_code == 404
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest D:/cedartoy/tests/test_reactivity_route.py -k fixit -v`
Expected: 2 FAIL with 404 (route doesn't exist).

- [ ] **Step 4: Add the endpoint**

Open `cedartoy/server/api/reactivity.py`. Read the existing structure (one `/prompt` GET handler that reads cookbook + template from disk and calls `build_reactivity_prompt`). After that handler, add:

```python
from pydantic import BaseModel  # if not already imported


class FixitRequest(BaseModel):
    base: str
    broken_glsl: str
    gl_log: str


@router.post("/fixit-prompt")
def fixit_prompt(body: FixitRequest) -> dict:
    """Build a Claude-ready prompt asking for a fix to a broken reactive variant."""
    from cedartoy.reactivity import build_fixit_prompt
    from cedartoy.server.api.shader_apply import SHADERS_DIR

    candidate = (SHADERS_DIR / body.base).resolve()
    try:
        candidate.relative_to(SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="base outside shaders directory")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"base shader not found: {body.base}")

    cookbook_path = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "reactivity" / "REACTIVITY_COOKBOOK.md"

    prompt = build_fixit_prompt(
        broken_glsl=body.broken_glsl,
        gl_log=body.gl_log,
        original_glsl=candidate.read_text(encoding="utf-8"),
        cookbook=cookbook_path.read_text(encoding="utf-8"),
    )
    return {"prompt": prompt}
```

If `from pathlib import Path` isn't already at the top of `reactivity.py`, add it. If `HTTPException` isn't imported either, add `HTTPException` to the existing `fastapi` import line.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest D:/cedartoy/tests/test_reactivity_route.py -v`
Expected: all PASS (including the 2 new tests + the existing /prompt tests).

- [ ] **Step 6: Commit**

```bash
git -C D:/cedartoy add cedartoy/server/api/reactivity.py tests/test_reactivity_route.py
git -C D:/cedartoy commit -m "feat(api): POST /api/reactivity/fixit-prompt for the Claude fix-it loop

Reads the original shader from shaders/<base>, embeds it alongside the
broken attempt and the GL compile log, and bundles in the cookbook so
Claude has the same context it had during the original retrofit."
```

---

## Task 4 — Web: preview-panel emits `shader-compile-result`

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/preview-panel.js`
- Modify: `web/js/app.js` (cache-bust)
- Modify: `web/index.html` (cache-bust)

The current `loadShader()` catches the renderer's thrown exception and shows a red overlay. We need to *also* emit a `shader-compile-result` event with `{ok, log}` so the drawer can react.

- [ ] **Step 1: Replace the `loadShader` method**

Open `web/js/components/preview-panel.js`. Find the `loadShader(path)` method:

```javascript
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
```

Replace with:

```javascript
    async loadShader(path) {
        const errorDiv = this.querySelector('#preview-error');
        errorDiv.style.display = 'none';
        let ok = true;
        let log = '';
        try {
            const shaderData = await api.getShader(path);
            this.renderer.compileShader(shaderData.source);
            this.renderer.render();
        } catch (err) {
            ok = false;
            log = err && err.message ? err.message : String(err);
            console.error('Failed to load shader:', err);
            errorDiv.textContent = `Shader Error: ${log}`;
            errorDiv.style.display = 'block';
        }
        document.dispatchEvent(new CustomEvent('shader-compile-result', {
            detail: { ok, log, path },
        }));
    }
```

- [ ] **Step 2: Bump cache-busts**

In `web/js/app.js`, change:

```javascript
import './components/preview-panel.js?v=4';
```

to:

```javascript
import './components/preview-panel.js?v=5';
```

In `web/index.html`, change `app.js?v=8` to `app.js?v=9`.

- [ ] **Step 3: Commit**

```bash
git -C D:/cedartoy add web/js/components/preview-panel.js web/js/app.js web/index.html
git -C D:/cedartoy commit -m "feat(preview-panel): emit shader-compile-result on every compile

Fires {ok, log, path} after every loadShader() — clean or failed. The
new shader-reactivity-drawer subscribes to flip its state between
'compiled clean' and 'compile failed (with fix-it prompt)'."
```

---

## Task 5 — Web: `<shader-reactivity-drawer>` component

**Repo:** `D:\cedartoy`

**Files:**
- Create: `web/js/components/shader-reactivity-drawer.js`

- [ ] **Step 1: Write the component**

Create `web/js/components/shader-reactivity-drawer.js` with:

```javascript
/**
 * <shader-reactivity-drawer>
 *
 * Stage 2 paste-back surface for the Claude round-trip. Lives next to
 * the existing config-editor reactivity button. Three states:
 *   - idle           — empty textarea, ready for a paste.
 *   - compiled-ok    — last Apply succeeded; banner shows ✔ Compiled.
 *   - compile-failed — last Apply produced a GL error; shows the log
 *                      and offers a "Copy fix-it prompt" button.
 *
 * Subscribes to:
 *   - shader-compile-result {ok, log, path}: from preview-panel after
 *     every WebGL compile attempt.
 */
class ShaderReactivityDrawer extends HTMLElement {
    constructor() {
        super();
        this._state = 'idle';          // 'idle' | 'compiled-ok' | 'compile-failed'
        this._lastGlLog = '';
        this._lastAppliedPath = '';     // the _reactive.glsl path we just wrote
        this._lastBrokenGlsl = '';      // the GLSL we extracted from the paste
    }

    connectedCallback() {
        this.render();
        this._attach();
        document.addEventListener('shader-compile-result', (e) => this._onCompile(e.detail));
    }

    render() {
        this.innerHTML = `
            <div class="reactivity-drawer">
                <div class="reactivity-drawer-status" id="rd-status"></div>
                <textarea id="rd-input" rows="6"
                    placeholder="Paste Claude's reply here (including the &#96;&#96;&#96;glsl fence)..."></textarea>
                <div class="reactivity-drawer-actions">
                    <button class="btn btn-primary" id="rd-apply">Apply</button>
                    <button class="btn btn-secondary" id="rd-overwrite"
                        title="Replaces the original shader file. This can't be undone.">Apply over original</button>
                    <button class="btn btn-secondary" id="rd-fixit" disabled
                        title="Copy a prompt to Claude that bundles the broken GLSL + compile error.">📋 Copy fix-it prompt ▸</button>
                </div>
                <div class="reactivity-drawer-log" id="rd-log" hidden></div>
            </div>
        `;
    }

    _attach() {
        this.querySelector('#rd-apply').addEventListener('click', () => this._apply('sibling'));
        this.querySelector('#rd-overwrite').addEventListener('click', () => {
            if (confirm('Overwrite the original shader? This cannot be undone.')) {
                this._apply('overwrite');
            }
        });
        this.querySelector('#rd-fixit').addEventListener('click', () => this._copyFixitPrompt());
    }

    _extractGlsl(text) {
        if (!text) return null;
        const fence = text.match(/```(?:glsl)?\s*\n([\s\S]*?)```/i);
        if (fence) return fence[1].trim();
        const trimmed = text.trim();
        if (/^#version|^precision\b|^void\s+main\b/m.test(trimmed)) {
            return trimmed;
        }
        return null;
    }

    async _apply(mode) {
        const base = window.cedartoy?.currentShader;
        if (!base) {
            this._setStatus('error', 'Pick a shader before applying.');
            return;
        }
        const text = this.querySelector('#rd-input').value;
        const glsl = this._extractGlsl(text);
        if (!glsl) {
            this._setStatus('error',
                'Couldn’t find a ```glsl block in that paste. Paste the full reply (including the fence), or paste only the GLSL.');
            return;
        }
        this._lastBrokenGlsl = glsl;
        try {
            const r = await fetch('/api/shader/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ base, glsl, mode }),
            });
            if (!r.ok) {
                const detail = await r.json().catch(() => ({}));
                throw new Error(detail.detail || `HTTP ${r.status}`);
            }
            const { path } = await r.json();
            this._lastAppliedPath = path;
            // Trigger compile by selecting the new shader.
            // (shader-browser strips the shaders/ prefix; do the same here.)
            const display = path.startsWith('shaders/') ? path.slice('shaders/'.length) : path;
            document.dispatchEvent(new CustomEvent('shader-select', {
                detail: { path: display },
            }));
            this._setStatus('pending', `Compiling ${this._basename(path)}…`);
        } catch (e) {
            this._setStatus('error', `Apply failed: ${e.message}`);
        }
    }

    _onCompile(detail) {
        // Only react to the compile that matches what we just applied.
        if (!this._lastAppliedPath) return;
        const justApplied = this._lastAppliedPath.endsWith(detail.path)
            || detail.path?.endsWith(this._lastAppliedPath.split('/').pop());
        if (!justApplied) return;

        if (detail.ok) {
            this._state = 'compiled-ok';
            this._lastGlLog = '';
            this._setStatus('ok', `✔ Compiled · running ${this._basename(this._lastAppliedPath)}`);
            this.querySelector('#rd-log').hidden = true;
            this.querySelector('#rd-fixit').disabled = true;
        } else {
            this._state = 'compile-failed';
            this._lastGlLog = detail.log || '';
            this._setStatus('error', `✗ Compile failed · ${this._basename(this._lastAppliedPath)}`);
            const logEl = this.querySelector('#rd-log');
            logEl.textContent = this._lastGlLog;
            logEl.hidden = false;
            this.querySelector('#rd-fixit').disabled = false;
        }
    }

    async _copyFixitPrompt() {
        const base = window.cedartoy?.currentShader;
        if (!base || !this._lastBrokenGlsl || !this._lastGlLog) {
            this._setStatus('error', 'Apply a shader first.');
            return;
        }
        // Resolve the *original* base (strip _reactive suffix if user re-applied
        // over the sibling — we want the pristine original).
        const baseClean = base.replace(/_reactive\.glsl$/i, '.glsl');
        try {
            const r = await fetch('/api/reactivity/fixit-prompt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base: baseClean,
                    broken_glsl: this._lastBrokenGlsl,
                    gl_log: this._lastGlLog,
                }),
            });
            if (!r.ok) {
                const detail = await r.json().catch(() => ({}));
                throw new Error(detail.detail || `HTTP ${r.status}`);
            }
            const { prompt } = await r.json();
            try {
                await navigator.clipboard.writeText(prompt);
                this._setStatus('ok', '✔ Fix-it prompt copied — paste into Claude');
            } catch (e) {
                // Clipboard unavailable; open as a blob URL so user can copy manually.
                const blob = new Blob([prompt], { type: 'text/markdown' });
                window.open(URL.createObjectURL(blob), '_blank');
            }
        } catch (e) {
            this._setStatus('error', `Fix-it prompt failed: ${e.message}`);
        }
    }

    _setStatus(kind, msg) {
        const el = this.querySelector('#rd-status');
        if (!el) return;
        el.dataset.kind = kind;
        el.textContent = msg;
    }

    _basename(p) {
        return (p || '').split(/[\\/]/).pop();
    }
}

customElements.define('shader-reactivity-drawer', ShaderReactivityDrawer);
```

- [ ] **Step 2: Commit**

```bash
git -C D:/cedartoy add web/js/components/shader-reactivity-drawer.js
git -C D:/cedartoy commit -m "feat(shader-drawer): paste-back drawer for Claude round-trip

Textarea + Apply (writes _reactive.glsl sibling), Apply over original
(confirm modal), Copy fix-it prompt (calls /api/reactivity/fixit-prompt).
Subscribes to shader-compile-result for the OK/failed state machine."
```

---

## Task 6 — Wire drawer into Stage 2 + CSS + push

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/index.html`
- Modify: `web/js/app.js`
- Modify: `web/css/components.css`

- [ ] **Step 1: Add the drawer to Stage 2**

Open `web/index.html`. Find:

```html
                    <div data-stage="shader" hidden>
                        <stage-helper
                            title="Stage 2 · Shader"
                            subtitle="Pick a shader from the rail. Make this shader reactive ▸ copies a Claude-ready prompt that retrofits MusiCue uniforms (iBpm, iBeat, iEnergy…) onto it."></stage-helper>
                        <config-editor></config-editor>
                    </div>
```

Replace with:

```html
                    <div data-stage="shader" hidden>
                        <stage-helper
                            title="Stage 2 · Shader"
                            subtitle="Pick a shader from the rail. Make this shader reactive ▸ copies a Claude-ready prompt; paste Claude's reply into the drawer below and hit Apply."></stage-helper>
                        <config-editor></config-editor>
                        <shader-reactivity-drawer></shader-reactivity-drawer>
                    </div>
```

- [ ] **Step 2: Import the drawer module**

Open `web/js/app.js`. After the `import './components/stage-helper.js?v=1';` line, add:

```javascript
import './components/shader-reactivity-drawer.js?v=1';
```

- [ ] **Step 3: Bump app.js cache-bust**

In `web/index.html`, change `app.js?v=9` to `app.js?v=10`.

- [ ] **Step 4: Add CSS**

Open `web/css/components.css`. Append at the end:

```css
/* Shader reactivity drawer (Stage 2 paste-back) */
shader-reactivity-drawer { display: block; padding: 0 12px 12px; }
.reactivity-drawer {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    padding: 10px;
    margin-top: 8px;
}
.reactivity-drawer textarea {
    width: 100%;
    box-sizing: border-box;
    background: #0f0f0f;
    color: #eee;
    border: 1px dashed #444;
    border-radius: 3px;
    padding: 6px 8px;
    font-family: monospace;
    font-size: 11px;
    resize: vertical;
}
.reactivity-drawer-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
}
.reactivity-drawer-actions .btn { padding: 4px 10px; font-size: 12px; }
.reactivity-drawer-status {
    font-size: 12px;
    padding: 4px 8px;
    margin-bottom: 8px;
    border-radius: 3px;
    min-height: 18px;
}
.reactivity-drawer-status[data-kind="ok"]      { background: #1a2a1a; color: #7ec97e; }
.reactivity-drawer-status[data-kind="error"]   { background: #2a1a1a; color: #fcc; }
.reactivity-drawer-status[data-kind="pending"] { background: #2a2a1a; color: #cca; }
.reactivity-drawer-log {
    margin-top: 8px;
    padding: 8px;
    background: #1a0a0a;
    border: 1px solid #4a2222;
    border-radius: 3px;
    font-family: monospace;
    font-size: 11px;
    color: #fcc;
    max-height: 110px;
    overflow: auto;
    white-space: pre-wrap;
}
```

- [ ] **Step 5: Manual browser smoke**

Hard-reload the UI tab (or use a fresh `?cb=plan-e` query string). On Stage 2:
- Pick any shader (e.g. `auroras`).
- The drawer appears below the config-editor with a textarea + Apply / Apply over original / Copy fix-it prompt buttons.
- Click **Make this shader reactive ▸** in config-editor → prompt copies to clipboard (existing behavior).
- Paste a known-good GLSL into the drawer's textarea — even just `void main(){gl_FragColor=vec4(0.5);}` wrapped in `\`\`\`glsl ... \`\`\`` — and hit **Apply**.
- The drawer's status flips to "Compiling…", then "✔ Compiled · running auroras_reactive.glsl"; the preview switches to that shader; the original `shaders/auroras.glsl` is untouched.
- Now paste a deliberately broken snippet like `\`\`\`glsl\nvoid main(){iKick;}\n\`\`\`` and hit Apply → drawer flips to "✗ Compile failed", the WebGL log appears in a red box, and **Copy fix-it prompt ▸** becomes enabled.
- Click it → clipboard now holds a markdown prompt containing the original shader, the broken attempt, the GL error, and the cookbook.
- Optional: paste that fix-it prompt into Claude, take its corrected GLSL, paste back into the drawer, Apply — loop should close.

- [ ] **Step 6: Commit**

```bash
git -C D:/cedartoy add web/index.html web/js/app.js web/css/components.css
git -C D:/cedartoy commit -m "feat(ui): wire shader-reactivity-drawer into Stage 2 + styles

Drawer placed as a sibling below config-editor inside Stage 2. CSS
defines the textarea, action buttons, status banner (ok/error/pending
variants), and the red GL-log box."
```

- [ ] **Step 7: Push**

```bash
git -C D:/cedartoy push origin main
```

Expected: push succeeds.

---

## Self-review checklist

- [x] **Spec coverage:**
  - § 6.3 `POST /api/shader/apply` (sibling/overwrite, atomic-rename, traversal-safe) → Task 1.
  - § 6.4 `POST /api/reactivity/fixit-prompt` → Task 3.
  - § 7.3 `preview-panel` emits `shader-compile-result` → Task 4.
  - § 7.7 `<shader-reactivity-drawer>` (paste-back, two states, fix-it button) → Tasks 5 + 6.
  - § 8.C flow Apply → maybe compile error → fix-it prompt → Tasks 4 + 5.
  - § 9 row "Paste-back: no ```glsl fence" → Task 5 (`_extractGlsl` fallback).
  - § 9 row "Paste-back: overwrite original" → Task 5 (Apply over original button + confirm).
  - § 9 row "Compile failed but textarea empty" → Task 5 (`#rd-fixit.disabled = true` until a broken attempt exists).
  - § 11 Plan E → this plan.
- [x] **Placeholder scan:** every step contains literal code or shell commands; no "similar to" or "TBD".
- [x] **Type consistency:** `shader-compile-result` event shape `{ok, log, path}` consistent between emitter (T4) and subscriber (T5). `/api/shader/apply` request shape `{base, glsl, mode}` and response `{path}` consistent across T1 and T5. `/api/reactivity/fixit-prompt` request shape `{base, broken_glsl, gl_log}` consistent across T3 and T5. `_lastAppliedPath` / `_lastBrokenGlsl` / `_lastGlLog` referenced only within drawer's own methods.
- [x] **Scope:** 6 tasks (3 server + 3 web), single repo, ~45 min.
