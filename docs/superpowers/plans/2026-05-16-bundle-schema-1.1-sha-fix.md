# Plan A — Bundle schema 1.1 + sha fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `decoded_audio_sha256` to the MusiCue bundle so CedarToy's integrity check fires only on real audio corruption, not on every export.

**Architecture:** Bump `MusiCueBundle.schema_version` to `"1.1"`, compute the sha of the decoded WAV after writing it, store it on the bundle. CedarToy prefers `decoded_audio_sha256` when present and treats its absence (legacy 1.0 bundles) as "integrity check unavailable" — no false-positive warning.

**Tech Stack:** Python 3.11, Pydantic v2, pytest. The plan spans two repos: MusiCue (`D:\MusiCue`) and CedarToy (`D:\cedartoy`). Each commit lives in its respective repo.

**Spec:** `docs/superpowers/specs/2026-05-16-cedartoy-ux-sync-pass.md` § 5, § 9 (the bundle 1.1 row), § 10, § 11 (Plan A).

---

## File structure

```
MusiCue (D:\MusiCue)
├── musicue/schemas.py                   [modify]  MusiCueBundle: add decoded_audio_sha256, bump schema_version
├── musicue/compile/cedartoy_folder.py   [modify]  compute sha of song.wav after _copy_audio_as_wav, attach to bundle
└── tests/test_cedartoy_folder.py        [modify]  add regression: decoded_audio_sha256 matches the wav written

CedarToy (D:\cedartoy)
├── cedartoy/project.py                  [modify]  prefer decoded_audio_sha256; legacy 1.0 → benign note
├── tests/test_project_loader.py         [modify]  legacy 1.0 reads benign; 1.1 fires only on real mismatch
└── web/js/components/project-panel.js   [modify]  render benign note vs. sticky warning based on flag
```

Each unit has one responsibility. The bundle schema owns the *what*, `cedartoy_folder.py` owns the *write*, `project.py` owns the *read*, `project-panel.js` owns the *display*.

---

## Task 1 — Add `decoded_audio_sha256` to the bundle schema

**Repo:** `D:\MusiCue`

**Files:**
- Modify: `musicue/schemas.py` (the `MusiCueBundle` class — lines around 229-234)
- Test: `tests/test_bundle_schema.py`

- [ ] **Step 1: Open the test file and add a failing test**

```python
# tests/test_bundle_schema.py — append to the end of the file
def test_bundle_carries_decoded_audio_sha256_optional():
    """Schema 1.1 adds decoded_audio_sha256 as optional (None = legacy 1.0)."""
    from musicue.schemas import MusiCueBundle, TempoInfo

    b = MusiCueBundle(
        source_sha256="a" * 64,
        decoded_audio_sha256="b" * 64,
        duration_sec=10.0,
        tempo=TempoInfo(bpm_global=120.0),
        beats=[],
        sections=[],
        drums={},
        midi={},
        midi_energy={},
        stems_energy={},
        global_energy=None,
        cuesheet=None,
    )
    assert b.decoded_audio_sha256 == "b" * 64
    assert b.schema_version == "1.1"


def test_bundle_legacy_schema_version_is_readable():
    """A bundle dict without decoded_audio_sha256 still parses (round-trip from 1.0)."""
    from musicue.schemas import MusiCueBundle, TempoInfo

    b = MusiCueBundle(
        schema_version="1.0",
        source_sha256="a" * 64,
        duration_sec=10.0,
        tempo=TempoInfo(bpm_global=120.0),
        beats=[],
        sections=[],
        drums={},
        midi={},
        midi_energy={},
        stems_energy={},
        global_energy=None,
        cuesheet=None,
    )
    assert b.decoded_audio_sha256 is None
    assert b.schema_version == "1.0"
```

- [ ] **Step 2: Run the test to verify failure**

Run: `cd /d D:\MusiCue && python -m pytest tests/test_bundle_schema.py::test_bundle_carries_decoded_audio_sha256_optional -v`
Expected: FAIL with `pydantic.ValidationError: Extra inputs are not permitted` for `decoded_audio_sha256`, or `AssertionError` on `schema_version == "1.1"`.

- [ ] **Step 3: Add the field and bump the default schema_version**

Open `musicue/schemas.py`, find the `MusiCueBundle` class (around line 229). Change:

```python
class MusiCueBundle(BaseModel):
    schema_version: str = "1.0"
    source_sha256: str
    duration_sec: float
    fps: float = 24.0
```

to:

```python
class MusiCueBundle(BaseModel):
    schema_version: str = "1.1"
    source_sha256: str
    decoded_audio_sha256: str | None = None
    duration_sec: float
    fps: float = 24.0
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `cd /d D:\MusiCue && python -m pytest tests/test_bundle_schema.py -v`
Expected: PASS (both new tests + all existing tests in this file).

- [ ] **Step 5: Commit**

```bash
cd /d D:\MusiCue
git add musicue/schemas.py tests/test_bundle_schema.py
git commit -m "feat(bundle): schema 1.1 adds decoded_audio_sha256 field

Optional field; defaults to None so existing 1.0 bundles round-trip unchanged.
The producer (compile/cedartoy_folder.py) will populate it from the sha of
the decoded WAV written to disk."
```

---

## Task 2 — Compute decoded-WAV sha and attach to bundle on export

**Repo:** `D:\MusiCue`

**Files:**
- Modify: `musicue/compile/cedartoy_folder.py` (build_cedartoy_folder, around line 147)
- Test: `tests/test_cedartoy_folder.py`

- [ ] **Step 1: Add the failing test**

```python
# tests/test_cedartoy_folder.py — append to the end of the file
def test_bundle_decoded_audio_sha_matches_written_wav(tmp_path, make_analysis_fixture, make_cuesheet_fixture):
    """The bundle's decoded_audio_sha256 equals sha256(song.wav)."""
    import hashlib
    import json
    from musicue.compile.cedartoy_folder import build_cedartoy_folder

    audio_src = _wav_fixture(tmp_path / "src.wav")  # helper from this file
    out_dir = tmp_path / "export"
    build_cedartoy_folder(
        audio_path=audio_src,
        analysis=make_analysis_fixture(),
        cuesheet=make_cuesheet_fixture(),
        out_dir=out_dir,
        grammar="concert_visuals",
        musicue_version="0.test",
    )

    wav_bytes = (out_dir / "song.wav").read_bytes()
    expected_sha = hashlib.sha256(wav_bytes).hexdigest()

    bundle_doc = json.loads((out_dir / "song.musicue.json").read_text("utf-8"))
    assert bundle_doc["schema_version"] == "1.1"
    assert bundle_doc["decoded_audio_sha256"] == expected_sha
```

Note: `_wav_fixture` is the existing helper in this test file that writes a small wav. If it doesn't exist under that exact name, use the existing fixture in this file that produces a wav (e.g. the one used by `test_build_cedartoy_folder_writes_expected_layout`); copy its body inline if needed.

- [ ] **Step 2: Run the test to verify failure**

Run: `cd /d D:\MusiCue && python -m pytest tests/test_cedartoy_folder.py::test_bundle_decoded_audio_sha_matches_written_wav -v`
Expected: FAIL with `KeyError: 'decoded_audio_sha256'` or `AssertionError` (None vs. computed sha).

- [ ] **Step 3: Compute the sha after WAV write and attach to the bundle**

Open `musicue/compile/cedartoy_folder.py`. Find the block that writes the wav and the bundle (around line 147-152):

```python
    _copy_audio_as_wav(audio_path, tmp / "song.wav")

    bundle = build_bundle(analysis, cuesheet)
    (tmp / "song.musicue.json").write_text(
        bundle.model_dump_json(indent=2), encoding="utf-8"
    )
```

Replace with:

```python
    wav_path = tmp / "song.wav"
    _copy_audio_as_wav(audio_path, wav_path)

    bundle = build_bundle(analysis, cuesheet)
    bundle.decoded_audio_sha256 = _sha256_file(wav_path)
    (tmp / "song.musicue.json").write_text(
        bundle.model_dump_json(indent=2), encoding="utf-8"
    )
```

Then add the helper near the other private helpers (near `_iso_utc_now`):

```python
import hashlib


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()
```

If `import hashlib` is already at the top of the file, don't duplicate it — just add the helper function.

- [ ] **Step 4: Run the tests to verify pass**

Run: `cd /d D:\MusiCue && python -m pytest tests/test_cedartoy_folder.py -v`
Expected: PASS (new test + all existing tests in this file).

- [ ] **Step 5: Commit**

```bash
cd /d D:\MusiCue
git add musicue/compile/cedartoy_folder.py tests/test_cedartoy_folder.py
git commit -m "feat(cedartoy-folder): emit decoded_audio_sha256 in bundle 1.1

Computed by sha256-ing the WAV bytes written to song.wav (after any
m4a/mp3 decode). CedarToy compares this against the audio it loads
instead of source_sha256, killing the false-positive warning that
fired on every export from a compressed source."
```

---

## Task 3 — Push MusiCue main

**Repo:** `D:\MusiCue`

- [ ] **Step 1: Push**

```bash
cd /d D:\MusiCue
git push origin main
```

Expected: push succeeds.

---

## Task 4 — CedarToy reads the new sha field

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `cedartoy/project.py` (the sha comparison block, lines 99-112)
- Test: `tests/test_project_loader.py`

- [ ] **Step 1: Add three failing tests covering the three branches**

```python
# tests/test_project_loader.py — append to the end of the file
def test_bundle_1_1_matching_sha_clears_warning(tmp_path):
    """Bundle 1.1 with decoded_audio_sha256 matching the wav: no warning, match=True."""
    import hashlib
    import json
    from cedartoy.project import load_project

    folder = tmp_path / "project"
    folder.mkdir()
    wav_bytes = b"RIFF" + b"\x00" * 100  # minimal stand-in; we only check sha
    (folder / "song.wav").write_bytes(wav_bytes)
    expected_sha = hashlib.sha256(wav_bytes).hexdigest()
    (folder / "song.musicue.json").write_text(json.dumps({
        "schema_version": "1.1",
        "source_sha256": "a" * 64,
        "decoded_audio_sha256": expected_sha,
    }), encoding="utf-8")

    proj = load_project(folder)
    assert proj.bundle_sha_matches_audio is True
    assert not any("sha" in w.lower() for w in proj.warnings)


def test_bundle_1_1_real_mismatch_fires_warning(tmp_path):
    """Bundle 1.1 with mismatched decoded_audio_sha256: match=False, sticky warning."""
    import json
    from cedartoy.project import load_project

    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "song.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    (folder / "song.musicue.json").write_text(json.dumps({
        "schema_version": "1.1",
        "source_sha256": "a" * 64,
        "decoded_audio_sha256": "b" * 64,
    }), encoding="utf-8")

    proj = load_project(folder)
    assert proj.bundle_sha_matches_audio is False
    assert any("audio has changed" in w.lower() for w in proj.warnings)


def test_bundle_1_0_skips_sha_check(tmp_path):
    """Bundle 1.0 (no decoded_audio_sha256): match=None, benign note, no warning."""
    import json
    from cedartoy.project import load_project

    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "song.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    (folder / "song.musicue.json").write_text(json.dumps({
        "schema_version": "1.0",
        "source_sha256": "a" * 64,
    }), encoding="utf-8")

    proj = load_project(folder)
    assert proj.bundle_sha_matches_audio is None
    notes = " ".join(proj.warnings).lower()
    assert "integrity check unavailable" in notes
    assert "does not match" not in notes  # no false-positive
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `cd /d D:\cedartoy && python -m pytest tests/test_project_loader.py -k "bundle_1" -v`
Expected: 3 FAIL — current code compares `source_sha256` directly so test 1 fails (sha won't match), test 2 may pass accidentally for the wrong reason, test 3 fails (current code emits "does not match" warning).

- [ ] **Step 3: Rewrite the sha comparison block in `cedartoy/project.py`**

Find the block at lines 99-112:

```python
    sha_match: bool | None = None
    if audio_path is not None and bundle_path is not None:
        try:
            audio_sha = compute_audio_sha256(audio_path)
            bundle_doc = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle_sha = bundle_doc.get("source_sha256")
            sha_match = audio_sha == bundle_sha
            if not sha_match:
                warnings.append(
                    f"bundle source_sha256 ({bundle_sha[:12] if bundle_sha else '?'}…) "
                    f"does not match audio sha ({audio_sha[:12]}…); using anyway"
                )
        except Exception as e:
            warnings.append(f"sha check failed: {e}")
```

Replace with:

```python
    sha_match: bool | None = None
    if audio_path is not None and bundle_path is not None:
        try:
            bundle_doc = json.loads(bundle_path.read_text(encoding="utf-8"))
            decoded_sha = bundle_doc.get("decoded_audio_sha256")
            if decoded_sha:
                audio_sha = compute_audio_sha256(audio_path)
                sha_match = audio_sha == decoded_sha
                if not sha_match:
                    warnings.append(
                        f"Audio has changed since MusiCue exported it "
                        f"(sha {audio_sha[:12]}… vs. expected {decoded_sha[:12]}…). "
                        f"Re-export from MusiCue for fresh bundle data."
                    )
            else:
                # Legacy bundle schema 1.0 — no decoded sha available.
                warnings.append(
                    "Bundle schema 1.0 — audio integrity check unavailable. "
                    "Re-export from MusiCue for schema 1.1."
                )
        except Exception as e:
            warnings.append(f"sha check failed: {e}")
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `cd /d D:\cedartoy && python -m pytest tests/test_project_loader.py -v`
Expected: PASS (new tests + any pre-existing tests in this file; if a pre-existing test asserted the old warning text, update it as part of this task — the old text is gone).

- [ ] **Step 5: Commit**

```bash
cd /d D:\cedartoy
git add cedartoy/project.py tests/test_project_loader.py
git commit -m "fix(project): prefer bundle.decoded_audio_sha256 over source_sha256

source_sha256 hashes the original m4a/mp3 (pre-decode), so it never
matches the WAV CedarToy reads. Bundle schema 1.1 carries
decoded_audio_sha256 (sha of the WAV) for a real integrity check.
Schema 1.0 bundles skip the check with a benign note instead of
firing a false-positive warning."
```

---

## Task 5 — Project panel renders benign note vs. sticky warning

**Repo:** `D:\cedartoy`

**Files:**
- Modify: `web/js/components/project-panel.js` (the `banner` computation, lines 14-19)

- [ ] **Step 1: Inspect the current banner logic**

The current code emits a single warning style for the `bundle_sha_matches_audio === false` case. The fix: the *new* server-side warning text already says "Audio has changed…" (real mismatch) or "Bundle schema 1.0 — …" (legacy note). The JS should distinguish:

- `bundle_sha_matches_audio === false` → red sticky warning (`.project-warning`).
- `bundle_sha_matches_audio === null` AND a "schema 1.0" string appears in warnings → a softer info-style note (`.project-row-info`).
- `bundle_sha_matches_audio === true` → nothing.

- [ ] **Step 2: Update the banner block**

Open `web/js/components/project-panel.js`. Replace the existing `banner` const (around line 15):

```javascript
        const banner = p && p.bundle_sha_matches_audio === false
            ? `<div class="project-warning">⚠ Bundle sha does not match audio — re-export from MusiCue, or proceed knowing the bundle was built against different audio.</div>`
            : '';
```

with:

```javascript
        let banner = '';
        if (p && p.bundle_sha_matches_audio === false) {
            banner = `<div class="project-warning">⚠ Audio has changed since MusiCue exported it. Re-export from MusiCue for fresh bundle data.</div>`;
        } else if (p && p.bundle_sha_matches_audio === null && (p.warnings || []).some(w => w.toLowerCase().includes('schema 1.0'))) {
            banner = `<div class="project-row project-row-info">ℹ Bundle schema 1.0 — audio integrity check unavailable. Re-export from MusiCue for schema 1.1.</div>`;
        }
```

- [ ] **Step 3: Bump the cache-bust query string on the import**

Open `web/js/app.js`. Find:

```javascript
import './components/project-panel.js?v=1';
```

Change to:

```javascript
import './components/project-panel.js?v=2';
```

(This ensures the browser picks up the new JS without a hard reload.)

- [ ] **Step 4: Manual browser smoke test**

Start the UI if it isn't running:

```bash
cd /d D:\cedartoy && python -m cedartoy.cli ui
```

Open `http://localhost:8080`. In Stage 1, paste the path of a project folder produced by a **post-Task-2 MusiCue** export (you'll need to re-export at least one song from MusiCue for the bundle to be 1.1).

Expected:
- Bundle 1.1 + matching audio: no banner. Audio row shows ✔.
- Bundle 1.0 (any pre-Task-2 export): soft info note "Bundle schema 1.0 — audio integrity check unavailable."
- Real mismatch (replace `song.wav` with `audio_data/somethingelse.wav`): red banner "Audio has changed…".

- [ ] **Step 5: Commit**

```bash
cd /d D:\cedartoy
git add web/js/components/project-panel.js web/js/app.js
git commit -m "feat(ui): project panel distinguishes real mismatch from legacy bundle

Three states now have three distinct UI affordances:
- bundle 1.1 sha matches → no banner
- bundle 1.1 sha mismatch → red sticky warning (real corruption signal)
- bundle 1.0 (no sha) → soft info note suggesting re-export"
```

---

## Task 6 — Push CedarToy main

**Repo:** `D:\cedartoy`

- [ ] **Step 1: Push**

```bash
cd /d D:\cedartoy
git push origin main
```

Expected: push succeeds.

- [ ] **Step 2: Verify**

In the browser, hard-reload Stage 1 (`Ctrl+Shift+R`) and reload the same project folder. The warning is gone (or appears as the soft info note for legacy bundles).

---

## Self-review checklist

- [x] **Spec coverage:** § 5 (bundle 1.1 schema) → Tasks 1-2. § 9 row "decoded_audio_sha256 mismatch" → Task 4 test 2. § 9 row "Bundle 1.0 legacy" → Task 4 test 3. § 10 `tests/test_bundle_v1_1.py` (CedarToy side) → Task 4 (added to existing `tests/test_project_loader.py` rather than a new file, since the project loader is what hosts the comparison logic). § 10 `tests/test_bundle_decoded_sha.py` (MusiCue side) → Task 2 (added to existing `tests/test_cedartoy_folder.py` for the same reason). § 11 Plan A → this plan.
- [x] **Placeholders:** none. Every step has the literal code or command.
- [x] **Type consistency:** `decoded_audio_sha256` consistently as `str | None`; `bundle_sha_matches_audio` consistently as `bool | None`; warning strings match between server emitter (Task 4 step 3) and UI detector (Task 5 step 2 — `'schema 1.0'` substring match works for both warning variants).
- [x] **Scope:** 6 tasks, two repos, ~30 minutes total. Single-plan-shaped.
