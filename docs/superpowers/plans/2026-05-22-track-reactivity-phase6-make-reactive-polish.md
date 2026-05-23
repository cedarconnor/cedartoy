# Track Reactivity — Phase 6: Make-Reactive Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the original "apply over original looks identical" report and make generated reactivity fit the song: (1) `get_shader` returns `Cache-Control: no-store` + the client fetches with `cache: 'no-store'`, so an overwrite always recompiles fresh source; (2) the Make-Reactive prompt includes a summary of the loaded song's actual bundle data, so Claude maps to tracks that exist.

**Architecture:** Two small, independent changes. The cache fix wraps `get_shader`'s response with a no-store header and adds `cache: 'no-store'` to `api.getShader`. The prompt enrichment adds a `format_bundle_health` formatter (next to `bundle_health` in `musicue.py`), threads an optional `bundle_summary` into `build_reactivity_prompt`, and lets `/api/reactivity/prompt` take an optional `audio` param to compute it.

**Tech Stack:** FastAPI (+ `fastapi.responses.JSONResponse`, `TestClient`), pytest, vanilla JS.

---

## Background facts (read before starting)

- **Item #4 had two causes** (diagnosed in the spec §1.1): reactivity gated off without playback (already solved by Validate mode, Phases 2-3) and a possible stale GET. This phase fixes the stale-GET cause.
- **`get_shader`** (`cedartoy/server/api/shaders.py:147-172`) reads the file and `return`s a plain dict `{path, source, metadata}` — FastAPI serializes it with **no cache headers**, so a browser may serve a heuristically-cached copy on an overwrite (same URL). `shaders.py` imports `from fastapi.responses import FileResponse, Response`.
- **`api.getShader`** (`web/js/api.js:14-17`) does a plain `fetch('/api/shaders/' + encodeURIComponent(path))` with no cache control.
- **Prompt builder** (`cedartoy/reactivity.py:33-50`): `build_reactivity_prompt(*, shader_src, template_path, cookbook_path)` substitutes cookbook + shader into template slots and returns the string. `reactivity.py` does **not** import `musicue` — keep it that way; pass a pre-formatted summary string in.
- **Prompt endpoint** (`cedartoy/server/api/reactivity.py:24-59`): `reactivity_prompt(shader)` builds the prompt; it already imports `build_track_timeline, load_for_audio` from `musicue` (Phase 1). `bundle_health(bundle)` exists in `musicue.py` (Phase 1).
- **`shaders.py` carries pre-existing WIP** — snapshot it before editing (Task 1 Step 0).
- **Test project:** `D:\MusiCue\exports\hair dye` (drums kick 84 / hat 94 / snare 7; `stems_energy` empty) for the live smoke.

---

## Task 1: Shader source served + fetched no-store

**Files:**
- Modify: `cedartoy/server/api/shaders.py`, `web/js/api.js`
- Test: `tests/test_shader_cache_headers.py` (create), `tests/web/test_api_no_store_source.py` (create)

- [ ] **Step 0: Snapshot pre-existing WIP**

Run: `git status --short cedartoy/server/api/shaders.py`
If ` M`, snapshot first:

```bash
git add cedartoy/server/api/shaders.py
git commit -m "chore(wip): snapshot pre-existing shaders.py edits"
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_shader_cache_headers.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cedartoy.server.api.shaders import router, SHADERS_DIR


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api/shaders")
    return TestClient(app)


def test_get_shader_is_no_store(tmp_path, monkeypatch):
    # Use a real shader from the repo's shaders dir.
    sample = next(SHADERS_DIR.rglob("*.glsl"))
    rel = sample.relative_to(SHADERS_DIR).as_posix()
    r = _client().get(f"/api/shaders/{rel}")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    assert "source" in r.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shader_cache_headers.py -v`
Expected: FAIL — `cache-control` header missing (None != "no-store").

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/server/api/shaders.py`, update the import line:

```python
from fastapi.responses import FileResponse, Response, JSONResponse
```

In `get_shader`, replace the final `return {...}` with a no-store `JSONResponse`:

```python
    return JSONResponse(
        content={"path": shader_path, "source": source, "metadata": metadata},
        headers={"Cache-Control": "no-store"},
    )
```

In `web/js/api.js`, update `getShader`:

```javascript
    async getShader(path) {
        const res = await fetch(`${API_BASE}/shaders/${encodeURIComponent(path)}`,
            { cache: 'no-store' });
        return await res.json();
    },
```

- [ ] **Step 4: Add the JS source test + run both**

Create `tests/web/test_api_no_store_source.py`:

```python
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/api.js"


def test_get_shader_fetches_no_store():
    s = SRC.read_text(encoding="utf-8")
    # the getShader fetch must opt out of the HTTP cache
    assert "getShader" in s
    assert "no-store" in s
```

Run: `python -m pytest tests/test_shader_cache_headers.py tests/web/test_api_no_store_source.py tests/test_shaders_route.py -v`
Expected: PASS (new tests + any existing shaders-route tests, if present; if `tests/test_shaders_route.py` does not exist, drop it from the command).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/server/api/shaders.py web/js/api.js tests/test_shader_cache_headers.py tests/web/test_api_no_store_source.py
git commit -m "fix(shaders): serve + fetch shader source no-store (fresh recompile on overwrite)"
```

---

## Task 2: Bundle-health summary in the Make-Reactive prompt

**Files:**
- Modify: `cedartoy/musicue.py` (add `format_bundle_health`)
- Modify: `cedartoy/reactivity.py` (`build_reactivity_prompt` optional summary)
- Modify: `cedartoy/server/api/reactivity.py` (optional `audio` param)
- Test: `tests/test_tracks.py`, `tests/test_reactivity_route.py`

- [ ] **Step 1: Write the failing test (formatter)**

Append to `tests/test_tracks.py`:

```python
def test_format_bundle_health_summary():
    from cedartoy.musicue import format_bundle_health
    health = {
        "beats": {"present": True, "count": 240},
        "sections": {"present": True, "count": 18},
        "drums": {"kick": 84, "snare": 7, "hat": 94, "tom": 0},
        "midi_energy": {"vocals": True, "bass": False},
        "stems_energy": {"present": False},
    }
    s = format_bundle_health(health)
    assert "beats: 240" in s
    assert "sections: 18" in s
    assert "kick(84)" in s and "hat(94)" in s
    # absent/empty data is called out so Claude won't map to it
    assert "tom" in s          # zero-count drum named as empty
    assert "bass" in s         # empty stem named
    assert "stems_energy" in s and "absent" in s.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k format_bundle_health -v`
Expected: FAIL — `cannot import name 'format_bundle_health'`.

- [ ] **Step 3: Write the formatter**

In `cedartoy/musicue.py`, add right after `bundle_health`:

```python
def format_bundle_health(health: Dict[str, Any]) -> str:
    """Human/Claude-readable one-paragraph summary of which bundle data exists.

    Names empty/absent tracks explicitly so reactivity prompts avoid mapping
    visuals to data that isn't there.
    """
    beats = health.get("beats", {})
    sections = health.get("sections", {})
    drums = health.get("drums", {})
    midi = health.get("midi_energy", {})
    stems = health.get("stems_energy", {})

    present_drums = [f"{k}({v})" for k, v in drums.items() if v]
    empty_drums = [k for k, v in drums.items() if not v]
    present_stems = [k for k, v in midi.items() if v]
    empty_stems = [k for k, v in midi.items() if not v]

    lines = [
        f"- beats: {beats.get('count', 0)} ({'present' if beats.get('present') else 'absent'})",
        f"- sections: {sections.get('count', 0)} ({'present' if sections.get('present') else 'absent'})",
        f"- drums present: {', '.join(present_drums) if present_drums else 'none'}",
        f"- drums empty: {', '.join(empty_drums) if empty_drums else 'none'}",
        f"- melodic stems present: {', '.join(present_stems) if present_stems else 'none'}",
        f"- melodic stems empty: {', '.join(empty_stems) if empty_stems else 'none'}",
        f"- stems_energy: {'present' if stems.get('present') else 'absent'}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run formatter test**

Run: `python -m pytest tests/test_tracks.py -k format_bundle_health -v`
Expected: PASS.

- [ ] **Step 5: Thread summary into the prompt builder + endpoint**

In `cedartoy/reactivity.py`, extend `build_reactivity_prompt`:

```python
def build_reactivity_prompt(
    *,
    shader_src: str,
    template_path: Path,
    cookbook_path: Path,
    bundle_summary: str | None = None,
) -> str:
    """Substitute cookbook + shader into the template's marked slots."""
    template = template_path.read_text(encoding="utf-8")
    cookbook = cookbook_path.read_text(encoding="utf-8")
    if _COOKBOOK_SLOT not in template:
        raise ValueError(f"prompt template missing cookbook slot: {_COOKBOOK_SLOT!r}")
    if _SHADER_SLOT not in template:
        raise ValueError(f"prompt template missing shader slot: {_SHADER_SLOT!r}")
    out = template.replace(_COOKBOOK_SLOT, cookbook).replace(_SHADER_SLOT, shader_src)
    if bundle_summary:
        out += ("\n\n## This song's available MusiCue data\n"
                "Map reactivity only to data that exists below; do not react to "
                "empty/absent tracks.\n" + bundle_summary + "\n")
    return out
```

In `cedartoy/server/api/reactivity.py`, import the formatter and accept an optional `audio` query param:

```python
from cedartoy.musicue import build_track_timeline, load_for_audio, bundle_health, format_bundle_health
```

Change the route signature and body:

```python
@router.get("/prompt")
def reactivity_prompt(shader: str, audio: str | None = None) -> dict:
    """Return the full prompt text + uniform introspection for the named shader."""
    # ... existing path resolution unchanged up to reading `src` ...
```

Then where the prompt is built, compute and pass the summary:

```python
    bundle_summary = None
    if audio:
        audio_path = Path(audio)
        if audio_path.exists():
            result = load_for_audio(audio_path)
            if result.bundle is not None:
                bundle_summary = format_bundle_health(bundle_health(result.bundle))

    prompt = build_reactivity_prompt(
        shader_src=src,
        template_path=_PROMPT_PATH,
        cookbook_path=_COOKBOOK_PATH,
        bundle_summary=bundle_summary,
    )
```

(Leave the `declared_uniforms` / `missing_uniforms` computation and the return dict shape unchanged.)

- [ ] **Step 6: Write the endpoint test**

Append to `tests/test_reactivity_route.py` (create the file if it doesn't exist with the standard TestClient harness — mount `router` at prefix `/api/reactivity`):

```python
def test_prompt_includes_bundle_health_when_audio_given(tmp_path):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cedartoy.server.api.reactivity import router, _SHADERS_DIR

    # a real shader that exists in the repo
    shader = next(_SHADERS_DIR.rglob("*.glsl")).relative_to(_SHADERS_DIR).as_posix()

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF....fake")
    bundle = {
        "schema_version": "1.0", "source_sha256": "x", "duration_sec": 2.0,
        "fps": 24.0, "tempo": {"bpm_global": 120.0, "time_signature": [4, 4]},
        "beats": [{"t": 0.0, "beat_in_bar": 0, "bar": 0, "is_downbeat": True}],
        "sections": [{"start": 0.0, "end": 2.0, "label": "verse", "energy_rank": 0.5}],
        "drums": {"kick": [{"t": 0.0, "strength": 0.9}], "hat": []},
        "midi": {}, "midi_energy": {}, "stems_energy": {},
        "global_energy": {"hop_sec": 0.5, "values": [0.2]}, "cuesheet": {},
    }
    audio.with_suffix("").with_suffix(".musicue.json").write_text(json.dumps(bundle), encoding="utf-8")

    app = FastAPI(); app.include_router(router, prefix="/api/reactivity")
    c = TestClient(app)
    r = c.get("/api/reactivity/prompt", params={"shader": shader, "audio": str(audio)})
    assert r.status_code == 200
    p = r.json()["prompt"]
    assert "available MusiCue data" in p
    assert "kick(1)" in p              # one kick onset present
    assert "hat" in p                  # empty drum named

    # without audio, no health section
    r2 = c.get("/api/reactivity/prompt", params={"shader": shader})
    assert "available MusiCue data" not in r2.json()["prompt"]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_reactivity_route.py tests/test_tracks.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add cedartoy/musicue.py cedartoy/reactivity.py cedartoy/server/api/reactivity.py tests/test_tracks.py tests/test_reactivity_route.py
git commit -m "feat(reactivity): inject bundle-health summary into the Make-Reactive prompt"
```

---

## Task 3: Regression sweep + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Python suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (E2E skips without a server). No Phase 1-5 regressions.

- [ ] **Step 2: Live smoke (start server)**

Start the UI (`python -m cedartoy.cli ui`). Verify:
- `curl -s -D - http://127.0.0.1:8080/api/shaders/<some>.glsl -o NUL` (or a Playwright `fetch`) shows `cache-control: no-store`.
- `GET /api/reactivity/prompt?shader=<a>.glsl&audio=D:\MusiCue\exports\hair dye\song.wav` returns a prompt whose text contains "available MusiCue data" and `kick(84)` / `hat(94)` / lists `stems_energy: absent`.
- (Optional, the original #4 end-to-end) In the browser: select a shader, paste a trivially-different reactive variant into the drawer, "Apply over original", confirm the preview recompiles to the new source (no stale copy). The no-store header guarantees the fetch isn't served from cache.

- [ ] **Step 3: Stop server, record results, commit any fix**

Stop the UI server. Commit any fix surfaced; otherwise nothing to do.

---

## Self-Review

**Spec coverage (Phase 6 of `2026-05-22-track-reactivity-validation-design.md`):**
- §1.1 / §6 cache fix (`Cache-Control: no-store` + client cache-bust) → Task 1. Combined with Validate mode (Phases 2-3), both causes of the original "apply over original looks identical" report are now addressed.
- §6 reactivity "explain prompt" (bundle-health summary into the Make-Reactive prompt) → Task 2.

**Placeholder scan:** No TBD/TODO. Code complete. Task 1 Step 0 is a conditional WIP-snapshot guard. The endpoint edit in Task 2 Step 5 references "existing path resolution unchanged" — that refers to the concrete lines already in `reactivity_prompt` (shader path containment + `src = src_path.read_text(...)`), which stay verbatim; only the signature gains `audio`, and the prompt call gains `bundle_summary`.

**Type/contract consistency:** `format_bundle_health(health: dict) -> str` (musicue, Task 2) consumes the exact `bundle_health` shape from Phase 1 (`beats/sections/drums/midi_energy/stems_energy`). `build_reactivity_prompt(..., bundle_summary=None)` (reactivity) — additive keyword, existing callers unaffected. The endpoint passes `format_bundle_health(bundle_health(result.bundle))` as `bundle_summary`. `get_shader` still returns `{path, source, metadata}` (now via `JSONResponse`) — response body unchanged, only headers added, so `api.getShader` consumers are unaffected.

**Carry-over note:** the prompt enrichment is opt-in via the `audio` query param; the existing `/api/reactivity/prompt?shader=` calls (no audio) behave exactly as before (no health section). If the UI's "Make this shader reactive" button should always include health, wire the current project's `audio_path` into that fetch — but that UI change is out of scope here and can be a small follow-up.
