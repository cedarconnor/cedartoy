# CedarToy Reactivity Prompt + Cookbook Implementation Plan (C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it easy to retrofit MusiCue-driven audio reactivity onto an existing GLSL shader by shipping (1) a paste-able Claude prompt template, (2) a versioned cookbook of GLSL reactivity snippets, (3) a small CedarToy helper that pre-fills the prompt with the currently-loaded shader.

**Architecture:** Two new markdown documents under `docs/reactivity/`. A pure `cedartoy/reactivity.py` module that parses a shader's declared uniforms and builds the prompt string. A new web-UI button on the shader-editor / stage-[2] panel that reads the current shader, fills the prompt, and either opens it in a new tab or copies it to clipboard. No LLM is called from CedarToy in v1 — the user runs the prompt through Claude themselves and pastes the result back into the editor.

**Tech Stack:** Markdown docs, Python 3.11 stdlib `re`, FastAPI endpoint to serve the rendered prompt, vanilla JS button hook.

**Spec:** `docs/superpowers/specs/2026-05-14-musicue-cedartoy-holistic-design.md` (§ Part C).

**Depends on:** none. Lands independently of Plans B-1 / B-2; the stage-[2] hook integrates more cleanly once B-1 lands but works on the existing config-editor too.

---

## File map

**Create:**
- `docs/reactivity/MUSICUE_REACTIVITY_PROMPT.md` — paste-able LLM template.
- `docs/reactivity/REACTIVITY_COOKBOOK.md` — versioned snippet library.
- `cedartoy/reactivity.py` — uniform-parser + prompt builder.
- `cedartoy/server/api/reactivity.py` — `GET /api/reactivity/prompt?shader=…` endpoint.
- `tests/test_reactivity_cookbook.py` — cookbook snippets all compile.
- `tests/test_reactivity_module.py` — uniform parsing + prompt rendering.
- `tests/test_reactivity_route.py` — HTTP.

**Modify:**
- `cedartoy/server/app.py` — register reactivity router.
- `web/js/components/shader-editor.js` (or `config-editor.js`) — add button hook.

---

## Task 1: Author `REACTIVITY_COOKBOOK.md` (7 snippets)

**Files:**
- Create: `docs/reactivity/REACTIVITY_COOKBOOK.md`

- [ ] **Step 1: Write the cookbook**

```markdown
# MusiCue Reactivity Cookbook — v1

`cookbook_version: 1`

Reusable GLSL idioms that turn MusiCue bundle data into visual modulation.
Each entry is self-contained: it lists the inputs it reads, the parameter
it modulates, default amplitude, a recommended cap, and where to insert
it in a typical Shadertoy-style shader.

These snippets assume CedarToy has bound:

- `iChannel0` — 2×512 musical spectrum texture (row 0.25 = spectrum, row 0.75 = heartbeat)
- `iBpm` `iBeat` `iBar` `iSectionEnergy` `iEnergy` — built-in uniforms when a bundle is loaded
- `iTime` `iResolution` — standard Shadertoy uniforms

---

## kick_pulse_camera (v1)

**Does:** Forward camera nudge on kick onsets.
**Inputs:** `iChannel0` row 0 bins 0–32.
**Modulates:** ray origin or eye position.
**Default amplitude:** 0.08 · **Cap:** 0.20.
**Where:** inside your camera-position calculation, before final ray origin.

```glsl
// === kick_pulse_camera (cookbook_version 1) ===
float kickEnergy = texture(iChannel0, vec2(0.03, 0.25)).r;
vec3 cameraPushOffset = cameraForward * kickEnergy * 0.08;
// add cameraPushOffset to your ray origin / eye position
```

---

## beat_pump_zoom (v1)

**Does:** FOV / scale wobble locked to the beat phase.
**Inputs:** `iBeat`.
**Modulates:** field-of-view or uniform scale.
**Default amplitude:** 0.04 · **Cap:** 0.10.
**Where:** near your `mainImage` UV scale or FOV calculation.

```glsl
// === beat_pump_zoom (cookbook_version 1) ===
float beatWave = 0.5 + 0.5 * sin(6.2831853 * iBeat - 1.5707963);
float zoomMul = 1.0 + beatWave * 0.04;
vec2 uv = (fragCoord / iResolution.xy - 0.5) * zoomMul + 0.5;
```

---

## section_palette_shift (v1)

**Does:** Advance the palette index by 1 step per section, eased.
**Inputs:** `iBar`, `iSectionEnergy`.
**Modulates:** palette lookup / hue rotation.
**Default amplitude:** 1.0 (one palette step per section).
**Where:** wherever you compute hue or palette index.

```glsl
// === section_palette_shift (cookbook_version 1) ===
float palette = float(iBar / 8) + iSectionEnergy * 0.5;
// Use palette as input to your existing palette function or hue rotation.
// Example: vec3 col = palette3(palette);
```

---

## energy_brightness_lift (v1)

**Does:** Multiplies final color by an energy-driven scalar.
**Inputs:** `iEnergy`.
**Modulates:** final fragColor.
**Default amplitude:** brightness range [0.9, 1.15] · **Cap:** [0.8, 1.30].
**Where:** at the end of `mainImage`, just before `fragColor = …`.

```glsl
// === energy_brightness_lift (cookbook_version 1) ===
col *= mix(0.9, 1.15, iEnergy);
```

---

## bar_anchored_strobe (v1)

**Does:** Single bright frame on every Nth downbeat, gated by section energy.
**Inputs:** `iBar`, `iBeat`, `iSectionEnergy`.
**Modulates:** additive white flash.
**Default amplitude:** 0.5 (white add) · **Cap:** 1.0.
**Where:** at the end of `mainImage`.

```glsl
// === bar_anchored_strobe (cookbook_version 1) ===
bool onBarStart = iBeat < 0.04 && (iBar % 4) == 0;
if (onBarStart && iSectionEnergy > 0.6) {
    col += vec3(0.5);
}
```

---

## melodic_glow_tint (v1)

**Does:** High-bin melodic energy modulates emissive tint on bright pixels.
**Inputs:** `iChannel0` row 0 bins 256–512.
**Modulates:** color tint where luminance > 0.6.
**Default amplitude:** 0.2 tint mix · **Cap:** 0.45.
**Where:** after primary shading, before final write.

```glsl
// === melodic_glow_tint (cookbook_version 1) ===
float mid = texture(iChannel0, vec2(0.75, 0.25)).r;
vec3 tint = vec3(1.0, 0.6, 0.8);
float lum = dot(col, vec3(0.299, 0.587, 0.114));
if (lum > 0.6) {
    col = mix(col, col * tint, clamp(mid, 0.0, 1.0) * 0.2);
}
```

---

## hat_grain (v1)

**Does:** Hi-hat energy adds film-grain density to the final image.
**Inputs:** `iChannel0` row 0 bins 96–256.
**Modulates:** additive noise.
**Default amplitude:** 0.04 · **Cap:** 0.10.
**Where:** at the end of `mainImage`.

```glsl
// === hat_grain (cookbook_version 1) ===
float hat = texture(iChannel0, vec2(0.35, 0.25)).r;
float n = fract(sin(dot(fragCoord, vec2(12.9898, 78.233))) * 43758.5453);
col += (n - 0.5) * hat * 0.04;
```
```

- [ ] **Step 2: Commit the cookbook**

```bash
git add docs/reactivity/REACTIVITY_COOKBOOK.md
git commit -m "docs(reactivity): v1 reactivity cookbook with 7 GLSL snippets"
```

---

## Task 2: Author `MUSICUE_REACTIVITY_PROMPT.md`

**Files:**
- Create: `docs/reactivity/MUSICUE_REACTIVITY_PROMPT.md`

- [ ] **Step 1: Write the prompt template**

```markdown
# Make this GLSL shader MusiCue-reactive

You are modifying an existing Shadertoy-style GLSL shader so it reacts to a
song analyzed by MusiCue. Use ONLY the inputs documented below. Do not
invent uniforms. Prefer cookbook patterns when they fit.

## Inputs available

```glsl
// Standard Shadertoy uniforms — already present in any Shadertoy shader.
uniform float     iTime;
uniform vec3      iResolution;
uniform sampler2D iChannel0;   // 2x512 musical spectrum texture
                               //   row 0.25 (frequency): bins 0–32 kick,
                               //                         32–96 snare+tom,
                               //                         96–256 hat+cymbal,
                               //                         256–512 melodic
                               //   row 0.75 (waveform):  tempo-locked heartbeat
                               //                         0.5 + 0.5·iEnergy·sin(2π·iBeat)

// MusiCue-driven uniforms — bound by CedarToy when a bundle is loaded.
// Declaring any of these in your shader opts in to bundle-aware reactivity.
uniform float iBpm;             // current BPM
uniform float iBeat;            // [0,1] phase within current beat
uniform int   iBar;             // 0-indexed bar number
uniform float iSectionEnergy;   // [0,1] rank of current section
uniform float iEnergy;          // [0,1] global energy at this moment
```

## Rules

1. **Preserve visual identity.** Reactivity is a modulation layer on top
   of the existing shader. Do NOT change the core look.
2. **Modulate parameters the shader already exposes** — FOV, speed,
   palette weights, distortion strength, brightness, glow. Avoid
   introducing new top-level passes or new buffers.
3. **Cap modulation amplitudes** to ±20% of base value by default. The
   shader must still look recognisable when the song is silent (all
   bundle uniforms = 0). Each cookbook entry has a recommended cap —
   honor it.
4. **Use cookbook patterns where they fit.** They have been chosen for
   musical legibility. Mix-and-match is fine; rewriting them is fine if
   the shader's variable names differ — but keep the comment header so a
   reader can see which idiom each block came from.
5. **Carry the cookbook version.** Add a `// cookbook_version: 1` line
   near the top of the shader so future tooling can suggest upgrades.
6. **Emit only the modified shader, in a single fenced ```glsl block.
   No prose, no diff, no explanation.

## Cookbook (attached)

<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>

## Target shader

<paste the contents of your target shader.glsl here verbatim>
```

- [ ] **Step 2: Commit the template**

```bash
git add docs/reactivity/MUSICUE_REACTIVITY_PROMPT.md
git commit -m "docs(reactivity): paste-able Claude prompt template"
```

---

## Task 3: Test that every cookbook snippet compiles

**Files:**
- Create: `tests/test_reactivity_cookbook.py`

- [ ] **Step 1: Write the test**

The test reads `REACTIVITY_COOKBOOK.md`, extracts each fenced GLSL block, wraps it in a minimal Shadertoy-shell shader that declares the bundle uniforms, and feeds the result to CedarToy's existing GLSL compile path. Any snippet that fails to compile is a test failure.

Look at how CedarToy compiles shaders today — it's probably an OpenGL context spin-up; if there's no headless OpenGL in the test env, fall back to a `glslangValidator` subprocess call, which CedarToy users probably already have. Choose the simplest of the two that works in the test environment:

```python
# tests/test_reactivity_cookbook.py
"""Every cookbook snippet must compile inside a minimal Shadertoy shell."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

COOKBOOK = Path(__file__).parent.parent / "docs" / "reactivity" / "REACTIVITY_COOKBOOK.md"

SHELL = """\
#version 330
uniform float     iTime;
uniform vec3      iResolution;
uniform sampler2D iChannel0;
uniform float     iBpm;
uniform float     iBeat;
uniform int       iBar;
uniform float     iSectionEnergy;
uniform float     iEnergy;

out vec4 fragColor;

vec3 cameraForward = vec3(0.0, 0.0, 1.0);
vec3 col = vec3(0.5);

void main() {
    vec2 fragCoord = gl_FragCoord.xy;
    // === SNIPPET ===
    fragColor = vec4(col, 1.0);
}
"""


def _extract_snippets(md: str) -> list[tuple[str, str]]:
    """Return list of (name, glsl_body) tuples."""
    out = []
    for m in re.finditer(r"```glsl\n(// === ([^\s]+)[^\n]*\n.*?)```",
                         md, re.DOTALL):
        body, name = m.group(1), m.group(2)
        out.append((name, body))
    return out


@pytest.fixture(scope="module")
def glslang_available():
    return shutil.which("glslangValidator") is not None


def test_cookbook_extracts_at_least_seven_snippets():
    md = COOKBOOK.read_text(encoding="utf-8")
    snippets = _extract_snippets(md)
    assert len(snippets) >= 7
    names = [n for n, _ in snippets]
    assert "kick_pulse_camera" in names
    assert "energy_brightness_lift" in names


@pytest.mark.parametrize("snippet_index", list(range(7)))
def test_cookbook_snippet_compiles(tmp_path, glslang_available, snippet_index):
    if not glslang_available:
        pytest.skip("glslangValidator not on PATH")
    md = COOKBOOK.read_text(encoding="utf-8")
    snippets = _extract_snippets(md)
    if snippet_index >= len(snippets):
        pytest.skip("fewer snippets than parametrized indices")
    name, body = snippets[snippet_index]
    shader = SHELL.replace("// === SNIPPET ===", body)
    out = tmp_path / f"{name}.frag"
    out.write_text(shader, encoding="utf-8")

    res = subprocess.run(
        ["glslangValidator", "-S", "frag", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, f"glslang failed:\n{res.stdout}\n{res.stderr}"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_reactivity_cookbook.py -v`
Expected: the extraction test passes; the per-snippet compile tests pass if `glslangValidator` is on PATH, else skip cleanly.

If snippets fail to compile, fix them in the cookbook (likely small things — missing semicolons, wrong vector swizzle, etc.) and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reactivity_cookbook.py
git commit -m "test(reactivity): every cookbook snippet compiles in a Shadertoy shell"
```

---

## Task 4: Uniform parser + prompt builder (pure module)

**Files:**
- Create: `cedartoy/reactivity.py`
- Create: `tests/test_reactivity_module.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reactivity_module.py
"""Unit tests for cedartoy.reactivity."""
from __future__ import annotations

from pathlib import Path

import pytest

from cedartoy.reactivity import (
    BUNDLE_UNIFORMS,
    build_reactivity_prompt,
    parse_declared_uniforms,
)


def test_parse_finds_declared_uniforms():
    src = """\
    uniform float iTime;
    uniform vec3  iResolution;
    uniform sampler2D iChannel0;
    uniform float iBpm;
    uniform float iEnergy;
    """
    declared = parse_declared_uniforms(src)
    assert "iTime" in declared
    assert "iBpm" in declared
    assert "iEnergy" in declared
    assert "iChannel0" in declared


def test_parse_ignores_uniforms_inside_comments():
    src = """\
    // uniform float iBpm; — commented out
    /* uniform float iBeat; */
    uniform float iEnergy;
    """
    declared = parse_declared_uniforms(src)
    assert "iEnergy" in declared
    assert "iBpm" not in declared
    assert "iBeat" not in declared


def test_bundle_uniforms_set_matches_spec():
    assert set(BUNDLE_UNIFORMS) == {
        "iBpm", "iBeat", "iBar", "iSectionEnergy", "iEnergy", "iChannel0",
    }


def test_build_prompt_substitutes_shader_and_cookbook(tmp_path):
    cookbook = tmp_path / "COOKBOOK.md"
    cookbook.write_text("# COOKBOOK\nentry 1\n")
    template = tmp_path / "PROMPT.md"
    template.write_text(
        "<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>\n"
        "<paste the contents of your target shader.glsl here verbatim>\n"
    )
    shader = "void main() { /* my shader */ }"
    out = build_reactivity_prompt(shader_src=shader,
                                  template_path=template,
                                  cookbook_path=cookbook)
    assert "# COOKBOOK" in out
    assert "/* my shader */" in out
    assert "<paste" not in out
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_reactivity_module.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# cedartoy/reactivity.py
"""Helpers for the reactivity authoring workflow.

* parse_declared_uniforms — find which bundle uniforms a shader already
  declares, so the UI can show "Missing: iBar, iSectionEnergy".
* build_reactivity_prompt — substitute a shader + the cookbook into the
  prompt template, ready to copy into Claude.
"""
from __future__ import annotations

import re
from pathlib import Path

BUNDLE_UNIFORMS = (
    "iBpm", "iBeat", "iBar", "iSectionEnergy", "iEnergy", "iChannel0",
)

# Strips // line comments and /* … */ block comments before scanning for uniforms.
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_UNIFORM_RE = re.compile(r"\buniform\s+\w+\s+(\w+)")


def _strip_comments(src: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", src))


def parse_declared_uniforms(src: str) -> set[str]:
    return set(_UNIFORM_RE.findall(_strip_comments(src)))


def build_reactivity_prompt(
    *,
    shader_src: str,
    template_path: Path,
    cookbook_path: Path,
) -> str:
    """Substitute cookbook + shader into the template's marked slots."""
    template = template_path.read_text(encoding="utf-8")
    cookbook = cookbook_path.read_text(encoding="utf-8")

    cookbook_slot = "<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>"
    shader_slot = "<paste the contents of your target shader.glsl here verbatim>"

    if cookbook_slot not in template:
        raise ValueError(
            f"prompt template missing cookbook slot: {cookbook_slot!r}"
        )
    if shader_slot not in template:
        raise ValueError(
            f"prompt template missing shader slot: {shader_slot!r}"
        )

    return template.replace(cookbook_slot, cookbook).replace(shader_slot, shader_src)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reactivity_module.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/reactivity.py tests/test_reactivity_module.py
git commit -m "feat(reactivity): uniform parser + prompt builder"
```

---

## Task 5: `GET /api/reactivity/prompt?shader=…` endpoint

**Files:**
- Create: `cedartoy/server/api/reactivity.py`
- Create: `tests/test_reactivity_route.py`
- Modify: `cedartoy/server/app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reactivity_route.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cedartoy.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_reactivity_prompt_returns_filled_template(client):
    # Use a shader from the shipped library.
    resp = client.get("/api/reactivity/prompt", params={"shader": "auroras.glsl"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "prompt" in body
    p = body["prompt"]
    assert "Make this GLSL shader MusiCue-reactive" in p
    assert "kick_pulse_camera" in p   # cookbook substituted
    assert "<paste" not in p          # placeholders gone
    # The auroras source should have been substituted in.
    assert "mainImage" in p or "main(" in p

    assert "declared_uniforms" in body  # introspection result
    assert "missing_uniforms" in body
    assert isinstance(body["declared_uniforms"], list)
    assert isinstance(body["missing_uniforms"], list)


def test_reactivity_prompt_404_on_unknown_shader(client):
    resp = client.get("/api/reactivity/prompt", params={"shader": "nope.glsl"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_reactivity_route.py -v`
Expected: FAIL — route not registered.

- [ ] **Step 3: Implement the router**

```python
# cedartoy/server/api/reactivity.py
"""Build a Claude-ready reactivity prompt from the current shader."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cedartoy.reactivity import (
    BUNDLE_UNIFORMS,
    build_reactivity_prompt,
    parse_declared_uniforms,
)

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHADERS_DIR = _REPO_ROOT / "shaders"
_PROMPT_PATH = _REPO_ROOT / "docs" / "reactivity" / "MUSICUE_REACTIVITY_PROMPT.md"
_COOKBOOK_PATH = _REPO_ROOT / "docs" / "reactivity" / "REACTIVITY_COOKBOOK.md"


@router.get("/prompt")
def reactivity_prompt(shader: str) -> dict:
    """Return the full prompt text + uniform introspection for the named shader."""
    # Strip any leading shaders/ since callers might prefix it.
    rel = shader[len("shaders/"):] if shader.startswith("shaders/") else shader
    rel = rel[len("shaders\\"):] if rel.startswith("shaders\\") else rel
    src_path = _SHADERS_DIR / rel
    if not src_path.exists() or not src_path.is_file():
        raise HTTPException(status_code=404, detail=f"shader not found: {shader}")

    src = src_path.read_text(encoding="utf-8")
    declared = parse_declared_uniforms(src)
    bundle_declared = sorted(u for u in BUNDLE_UNIFORMS if u in declared)
    missing = sorted(u for u in BUNDLE_UNIFORMS if u not in declared)

    prompt = build_reactivity_prompt(
        shader_src=src,
        template_path=_PROMPT_PATH,
        cookbook_path=_COOKBOOK_PATH,
    )

    return {
        "shader": shader,
        "declared_uniforms": bundle_declared,
        "missing_uniforms": missing,
        "prompt": prompt,
    }
```

In `cedartoy/server/app.py`:

```python
from .api import reactivity as reactivity_routes
app.include_router(reactivity_routes.router, prefix="/api/reactivity", tags=["reactivity"])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reactivity_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/server/api/reactivity.py cedartoy/server/app.py tests/test_reactivity_route.py
git commit -m "feat(api): GET /api/reactivity/prompt returns filled template"
```

---

## Task 6: Wire the "Make this shader reactive ▸" button

**Files:**
- Modify: `web/js/components/shader-editor.js` (or `config-editor.js` if the shader-editor doesn't have a natural slot)

The button reads the currently-selected shader path, calls `/api/reactivity/prompt`, and either copies the result to clipboard or opens it in a new tab. v1 picks "copy to clipboard with toast" — fewest browser-API gotchas.

- [ ] **Step 1: Add the button + handler**

In the shader-editor template, near the top of the parameter panel, insert:

```html
<div class="reactivity-status" id="reactivity-status">
    <span id="reactivity-declared"></span>
    <button id="reactivity-prompt-btn">Make this shader reactive ▸</button>
</div>
```

In the JS:

```javascript
async _updateReactivityStatus(shaderPath) {
    if (!shaderPath) return;
    try {
        const r = await fetch(
            `/api/reactivity/prompt?shader=${encodeURIComponent(shaderPath)}`
        );
        if (!r.ok) {
            this.querySelector('#reactivity-declared').textContent = '';
            return;
        }
        const data = await r.json();
        this._reactivityPrompt = data.prompt;
        const declared = data.declared_uniforms.join(' ') || '(none)';
        this.querySelector('#reactivity-declared').textContent =
            `Reactivity: declared ${declared} · missing ${data.missing_uniforms.join(' ')}`;
    } catch (e) {
        console.error('reactivity status failed', e);
    }
}

async _onReactivityPromptClick() {
    if (!this._reactivityPrompt) {
        alert('Pick a shader first.');
        return;
    }
    try {
        await navigator.clipboard.writeText(this._reactivityPrompt);
        const status = this.querySelector('#reactivity-status');
        const note = document.createElement('span');
        note.textContent = ' ✔ copied — paste into Claude';
        note.style.color = '#7ec97e';
        status.appendChild(note);
        setTimeout(() => note.remove(), 4000);
    } catch (e) {
        // Clipboard API may be unavailable over plain http; fall back to a
        // blob URL the user can open in a new tab and copy from.
        const blob = new Blob([this._reactivityPrompt], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank');
    }
}
```

Call `this._updateReactivityStatus(this.config.shader)` whenever the shader changes (the existing `config-change` handler is the natural place). Wire the button to `_onReactivityPromptClick`.

- [ ] **Step 2: Smoke**

Pick a shader, observe the "Reactivity:" line showing declared/missing uniforms. Click the button, paste into a scratch buffer, verify the prompt has both the shader source and the full cookbook substituted in.

- [ ] **Step 3: Commit**

```bash
git add web/js/components/shader-editor.js
git commit -m "feat(ui): Make-this-shader-reactive button copies filled prompt"
```

---

## Task 7: Cross-app smoke + end-to-end

**Files:**
- Modify: `tests/test_reactivity_route.py`

- [ ] **Step 1: Add a "snippet ends up in prompt" test**

```python
def test_prompt_substitutes_specific_cookbook_idiom(client):
    resp = client.get("/api/reactivity/prompt", params={"shader": "auroras.glsl"})
    body = resp.json()
    p = body["prompt"]
    # Every cookbook idiom name should appear somewhere in the prompt.
    for name in ["kick_pulse_camera", "beat_pump_zoom", "section_palette_shift",
                 "energy_brightness_lift", "bar_anchored_strobe",
                 "melodic_glow_tint", "hat_grain"]:
        assert name in p, f"prompt missing cookbook entry {name}"
```

- [ ] **Step 2: Manual end-to-end smoke**

1. Launch the CedarToy UI.
2. Pick a non-reactive shader (e.g. `4tjGRh_planet.glsl`).
3. Click **Make this shader reactive ▸**.
4. Paste the prompt into Claude.ai or `claude` CLI.
5. Paste Claude's GLSL response into the shader-editor.
6. Render a short preview against a MusiCue-exported folder; verify the shader visibly reacts where expected (drops, kicks, section transitions).
7. Compare to the unmodified shader rendered against the same audio with `--bundle-mode raw` to confirm the reactivity adds modulation without destroying the original look.

- [ ] **Step 3: Commit**

```bash
git add tests/test_reactivity_route.py
git commit -m "test(reactivity): every cookbook idiom name lands in the prompt"
```

---

## Done

After Task 7:

- `docs/reactivity/MUSICUE_REACTIVITY_PROMPT.md` and `REACTIVITY_COOKBOOK.md` are paste-able authoring assets.
- `cedartoy/reactivity.py` parses the bundle uniforms a shader declares and assembles the prompt deterministically.
- `GET /api/reactivity/prompt?shader=…` returns the filled prompt + uniform introspection.
- The shader-editor button copies the prompt to clipboard with a friendly toast; falls back to opening a blob URL when clipboard is unavailable.
- Every cookbook snippet is regression-tested to compile in a minimal Shadertoy shell.

Out of scope (explicit follow-ups for v2):

- In-app "Reactivity Wizard" with API-key-driven Anthropic call + side-by-side diff/A-B preview.
- Cookbook auto-upgrade (the `// cookbook_version: N` comment is recorded but not yet consumed).
- Per-stem uniforms (`iVocalEnergy`, etc.) — wait for MusiCue's `stems_energy` to populate, then add cookbook entries.
