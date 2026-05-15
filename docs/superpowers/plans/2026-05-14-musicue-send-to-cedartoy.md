# MusiCue → CedarToy Folder Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Send to CedarToy" action (web button + CLI flag + alias) that produces a portable project folder (`song.wav` + `song.musicue.json` + optional `stems/` + `manifest.json`) replacing today's CLI-only single-file bundle export.

**Architecture:** A new pure folder-builder module (`musicue/compile/cedartoy_folder.py`) does all filesystem work atomically (temp dir → atomic rename). The existing `musicue export-bundle` CLI command grows `--folder` and `--include-stems` flags that delegate to the builder. A new HTTP route at `/api/songs/{song_id}/analyses/{analysis_id}/send-to-cedartoy` calls the same builder. A small React dialog in the Editor page invokes the endpoint.

**Tech Stack:** Python 3.11, Pydantic v2, Typer, FastAPI, React + TypeScript, soundfile.

**Spec:** `D:\cedartoy\docs\superpowers\specs\2026-05-14-musicue-cedartoy-holistic-design.md` (§ Shared file contract, § Part A).

---

## File map

**Create:**
- `musicue/compile/cedartoy_folder.py` — pure folder-builder + manifest dataclass.
- `musicue/ui/routes/cedartoy.py` — new FastAPI router.
- `musicue/ui/web/src/lib/cedartoyApi.ts` — TS client for the new endpoint.
- `musicue/ui/web/src/components/SendToCedartoyDialog.tsx` — React dialog.
- `tests/test_cedartoy_folder.py` — folder-builder unit tests.
- `tests/test_send_to_cedartoy_route.py` — HTTP route tests.

**Modify:**
- `musicue/cli.py` — extend `export-bundle` with `--folder` + `--include-stems`; add `send-to-cedartoy` alias.
- `musicue/ui/server.py` — register new router.
- `musicue/ui/web/src/pages/Editor.tsx` — add button + dialog mount.
- `tests/test_bundle_cli.py` — add CLI-flag coverage.

---

## Task 1: Manifest dataclass + folder-builder skeleton

**Files:**
- Create: `musicue/compile/cedartoy_folder.py`
- Create: `tests/test_cedartoy_folder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cedartoy_folder.py
"""Unit tests for the CedarToy folder export builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from musicue.compile.cedartoy_folder import (
    CedarToyProjectManifest,
    MANIFEST_SCHEMA,
)


def test_manifest_to_dict_includes_required_fields():
    m = CedarToyProjectManifest(
        audio_filename="song.wav",
        original_audio="My Song Title.mp3",
        grammar="concert_visuals",
        musicue_version="0.4.1",
        exported_at="2026-05-14T19:32:11Z",
    )
    d = m.to_dict()
    assert d["schema"] == MANIFEST_SCHEMA
    assert d["audio_filename"] == "song.wav"
    assert d["original_audio"] == "My Song Title.mp3"
    assert d["grammar"] == "concert_visuals"
    assert d["musicue_version"] == "0.4.1"
    assert d["exported_at"] == "2026-05-14T19:32:11Z"
    assert "stems_omitted_reason" not in d  # only emitted when set


def test_manifest_emits_stems_omitted_reason_when_set():
    m = CedarToyProjectManifest(
        audio_filename="song.wav",
        original_audio="song.wav",
        grammar="concert_visuals",
        musicue_version="0.4.1",
        exported_at="2026-05-14T19:32:11Z",
        stems_omitted_reason="cache missing and force_analyze=false",
    )
    d = m.to_dict()
    assert d["stems_omitted_reason"] == "cache missing and force_analyze=false"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cedartoy_folder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'musicue.compile.cedartoy_folder'`

- [ ] **Step 3: Write minimal implementation**

```python
# musicue/compile/cedartoy_folder.py
"""Build a portable CedarToy project folder.

Layout written by build_cedartoy_folder()::

    <out_dir>/
      song.wav
      song.musicue.json
      stems/                       (optional)
        drums.wav  bass.wav  vocals.wav  other.wav
      manifest.json

Atomicity: everything is written to a sibling temp folder and renamed
into place on success. A failure mid-build leaves no folder at the
target path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MANIFEST_SCHEMA = "cedartoy-project/1"


@dataclass
class CedarToyProjectManifest:
    audio_filename: str
    original_audio: str
    grammar: str
    musicue_version: str
    exported_at: str
    stems_omitted_reason: str | None = None
    schema: str = MANIFEST_SCHEMA

    def to_dict(self) -> dict:
        d: dict = {
            "schema": self.schema,
            "audio_filename": self.audio_filename,
            "original_audio": self.original_audio,
            "grammar": self.grammar,
            "musicue_version": self.musicue_version,
            "exported_at": self.exported_at,
        }
        if self.stems_omitted_reason is not None:
            d["stems_omitted_reason"] = self.stems_omitted_reason
        return d
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cedartoy_folder.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add musicue/compile/cedartoy_folder.py tests/test_cedartoy_folder.py
git commit -m "feat(cedartoy): add manifest dataclass for project folder export"
```

---

## Task 2: Folder-builder happy path — audio + bundle + manifest (no stems)

**Files:**
- Modify: `musicue/compile/cedartoy_folder.py`
- Modify: `tests/test_cedartoy_folder.py`

This task introduces fixtures. MusiCue already has `tests/test_bundle_builder.py` with synthetic `AnalysisResult` + `CueSheet` factories. Reuse them via import.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_cedartoy_folder.py`:

```python
import shutil

from musicue.compile.bundle import build_bundle
from musicue.compile.cedartoy_folder import build_cedartoy_folder
from musicue.schemas import MusiCueBundle

# Reuse the existing builder-test fixtures so we don't drift.
from tests.test_bundle_builder import (
    make_analysis_fixture,
    make_cuesheet_fixture,
)


def _write_silent_wav(path: Path, duration_sec: float = 0.25) -> None:
    import numpy as np
    import soundfile as sf

    sr = 44100
    n = int(sr * duration_sec)
    sf.write(str(path), np.zeros(n, dtype="float32"), sr, subtype="PCM_16")


def test_build_folder_writes_audio_bundle_and_manifest(tmp_path):
    audio_src = tmp_path / "src" / "song.wav"
    audio_src.parent.mkdir(parents=True)
    _write_silent_wav(audio_src)

    out_dir = tmp_path / "out" / "song"

    analysis = make_analysis_fixture(audio_path=audio_src)
    cuesheet = make_cuesheet_fixture(source_sha256=analysis.source.sha256)

    build_cedartoy_folder(
        audio_path=audio_src,
        analysis=analysis,
        cuesheet=cuesheet,
        out_dir=out_dir,
        grammar="concert_visuals",
        musicue_version="0.4.1-test",
        exported_at="2026-05-14T00:00:00Z",
    )

    assert (out_dir / "song.wav").exists()
    assert (out_dir / "song.musicue.json").exists()
    assert (out_dir / "manifest.json").exists()
    assert not (out_dir / "stems").exists()

    # Bundle round-trips through the schema.
    bundle = MusiCueBundle.model_validate_json(
        (out_dir / "song.musicue.json").read_text()
    )
    assert bundle.source_sha256 == analysis.source.sha256

    # Manifest carries the supplied metadata.
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["schema"] == "cedartoy-project/1"
    assert manifest["audio_filename"] == "song.wav"
    assert manifest["grammar"] == "concert_visuals"
    assert manifest["musicue_version"] == "0.4.1-test"
```

If `tests/test_bundle_builder.py` does not already expose `make_analysis_fixture` / `make_cuesheet_fixture` as module-level helpers, refactor whatever local fixtures it has into module-level functions with those names. Check the file first.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cedartoy_folder.py::test_build_folder_writes_audio_bundle_and_manifest -v`
Expected: FAIL with `ImportError: cannot import name 'build_cedartoy_folder'`

- [ ] **Step 3: Implement the builder**

Append to `musicue/compile/cedartoy_folder.py`:

```python
from __future__ import annotations  # already present at top — do not duplicate

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from musicue.compile.bundle import build_bundle
from musicue.schemas import AnalysisResult, CueSheet


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _copy_audio_as_wav(src: Path, dest: Path) -> None:
    """Copy src to dest. If src is already a WAV, copy bytes; else decode.

    Native sample rate is preserved — no resampling.
    """
    if src.suffix.lower() == ".wav":
        shutil.copy2(src, dest)
        return
    import soundfile as sf
    data, sr = sf.read(str(src), always_2d=False)
    sf.write(str(dest), data, sr, subtype="PCM_16")


def build_cedartoy_folder(
    *,
    audio_path: Path,
    analysis: AnalysisResult,
    cuesheet: CueSheet,
    out_dir: Path,
    grammar: str,
    musicue_version: str,
    exported_at: str | None = None,
    include_stems: bool = False,
    stems_src_dir: Path | None = None,
    original_audio_name: str | None = None,
) -> CedarToyProjectManifest:
    """Atomically build a CedarToy project folder at out_dir.

    Returns the manifest dataclass (also written as manifest.json).
    Stems handling is the next task; pass include_stems=False here.
    """
    if include_stems:
        # Filled in by Task 3 — fail loudly so callers can't silently get
        # bundle-only output when they asked for stems.
        raise NotImplementedError("include_stems not implemented yet")

    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"Target folder already exists: {out_dir} — caller must "
            f"remove it or pick a different path"
        )

    timestamp = exported_at or _iso_utc_now()
    original_audio_name = original_audio_name or audio_path.name

    manifest = CedarToyProjectManifest(
        audio_filename="song.wav",
        original_audio=original_audio_name,
        grammar=grammar,
        musicue_version=musicue_version,
        exported_at=timestamp,
    )

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    # Sibling temp dir so the atomic rename is on the same filesystem.
    tmp = Path(tempfile.mkdtemp(prefix=".cedartoy-tmp-", dir=out_dir.parent))
    try:
        _copy_audio_as_wav(audio_path, tmp / "song.wav")
        bundle = build_bundle(analysis, cuesheet)
        (tmp / "song.musicue.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8"
        )
        (tmp / "manifest.json").write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
        )
        tmp.rename(out_dir)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest
```

- [ ] **Step 4: Verify `make_analysis_fixture`/`make_cuesheet_fixture` exist in tests/test_bundle_builder.py**

Run: `grep -n "def make_analysis_fixture\|def make_cuesheet_fixture" tests/test_bundle_builder.py`
Expected: two matches.

If missing, refactor the existing fixtures in that file into module-level functions with these exact names so other test files can import them. Do this as a separate commit before continuing:

```bash
git add tests/test_bundle_builder.py
git commit -m "refactor(tests): expose bundle-builder fixtures as module-level helpers"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cedartoy_folder.py -v`
Expected: PASS (3 tests total now)

- [ ] **Step 6: Commit**

```bash
git add musicue/compile/cedartoy_folder.py tests/test_cedartoy_folder.py
git commit -m "feat(cedartoy): folder builder writes audio + bundle + manifest atomically"
```

---

## Task 3: Folder-builder — include_stems happy path + missing-stems warning

**Files:**
- Modify: `musicue/compile/cedartoy_folder.py`
- Modify: `tests/test_cedartoy_folder.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_cedartoy_folder.py`:

```python
def test_build_folder_copies_stems_when_requested(tmp_path):
    audio_src = tmp_path / "src" / "song.wav"
    audio_src.parent.mkdir(parents=True)
    _write_silent_wav(audio_src)

    stems_src = tmp_path / "stems"
    stems_src.mkdir()
    for name in ("drums", "bass", "vocals", "other"):
        _write_silent_wav(stems_src / f"{name}.wav")

    out_dir = tmp_path / "out" / "song"
    analysis = make_analysis_fixture(audio_path=audio_src)
    cuesheet = make_cuesheet_fixture(source_sha256=analysis.source.sha256)

    manifest = build_cedartoy_folder(
        audio_path=audio_src,
        analysis=analysis,
        cuesheet=cuesheet,
        out_dir=out_dir,
        grammar="concert_visuals",
        musicue_version="0.4.1-test",
        include_stems=True,
        stems_src_dir=stems_src,
    )

    for name in ("drums", "bass", "vocals", "other"):
        assert (out_dir / "stems" / f"{name}.wav").exists()
    assert manifest.stems_omitted_reason is None


def test_build_folder_records_reason_when_stems_src_missing(tmp_path):
    audio_src = tmp_path / "src" / "song.wav"
    audio_src.parent.mkdir(parents=True)
    _write_silent_wav(audio_src)

    out_dir = tmp_path / "out" / "song"
    analysis = make_analysis_fixture(audio_path=audio_src)
    cuesheet = make_cuesheet_fixture(source_sha256=analysis.source.sha256)

    manifest = build_cedartoy_folder(
        audio_path=audio_src,
        analysis=analysis,
        cuesheet=cuesheet,
        out_dir=out_dir,
        grammar="concert_visuals",
        musicue_version="0.4.1-test",
        include_stems=True,
        stems_src_dir=tmp_path / "does" / "not" / "exist",
    )

    assert not (out_dir / "stems").exists()
    assert "cache missing" in (manifest.stems_omitted_reason or "")
    saved = json.loads((out_dir / "manifest.json").read_text())
    assert "cache missing" in saved["stems_omitted_reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cedartoy_folder.py -v -k stems`
Expected: FAIL with `NotImplementedError: include_stems not implemented yet`

- [ ] **Step 3: Replace the NotImplementedError branch with real stems handling**

In `musicue/compile/cedartoy_folder.py`, replace the `if include_stems: raise NotImplementedError(...)` block with this logic placed inside the `try:` block after the bundle/manifest writes:

```python
STEM_NAMES = ("drums", "bass", "vocals", "other")
```

(at module level, near `MANIFEST_SCHEMA`)

Replace the body of `build_cedartoy_folder` after the existing `tmp.rename(out_dir)` line. The full new shape:

```python
def build_cedartoy_folder(
    *,
    audio_path: Path,
    analysis: AnalysisResult,
    cuesheet: CueSheet,
    out_dir: Path,
    grammar: str,
    musicue_version: str,
    exported_at: str | None = None,
    include_stems: bool = False,
    stems_src_dir: Path | None = None,
    original_audio_name: str | None = None,
) -> CedarToyProjectManifest:
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"Target folder already exists: {out_dir} — caller must "
            f"remove it or pick a different path"
        )

    timestamp = exported_at or _iso_utc_now()
    original_audio_name = original_audio_name or audio_path.name

    stems_omitted_reason: str | None = None
    stems_to_copy: list[Path] = []
    if include_stems:
        src = Path(stems_src_dir) if stems_src_dir else None
        if src is None or not src.exists():
            stems_omitted_reason = (
                "cache missing and force_analyze=false; "
                f"stems_src_dir={src}"
            )
        else:
            for name in STEM_NAMES:
                p = src / f"{name}.wav"
                if p.exists():
                    stems_to_copy.append(p)
            if not stems_to_copy:
                stems_omitted_reason = (
                    f"cache missing (no stem WAVs in {src})"
                )

    manifest = CedarToyProjectManifest(
        audio_filename="song.wav",
        original_audio=original_audio_name,
        grammar=grammar,
        musicue_version=musicue_version,
        exported_at=timestamp,
        stems_omitted_reason=stems_omitted_reason,
    )

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".cedartoy-tmp-", dir=out_dir.parent))
    try:
        _copy_audio_as_wav(audio_path, tmp / "song.wav")

        bundle = build_bundle(analysis, cuesheet)
        (tmp / "song.musicue.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8"
        )

        if stems_to_copy:
            (tmp / "stems").mkdir()
            for p in stems_to_copy:
                shutil.copy2(p, tmp / "stems" / p.name)

        (tmp / "manifest.json").write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
        )

        tmp.rename(out_dir)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest
```

- [ ] **Step 4: Run all folder tests**

Run: `pytest tests/test_cedartoy_folder.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add musicue/compile/cedartoy_folder.py tests/test_cedartoy_folder.py
git commit -m "feat(cedartoy): support optional stems copy with omission reason"
```

---

## Task 4: Folder-builder — non-WAV source audio is decoded

**Files:**
- Modify: `tests/test_cedartoy_folder.py`

The `_copy_audio_as_wav` helper already handles this — write the test that pins the behavior.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_cedartoy_folder.py`:

```python
def test_build_folder_decodes_non_wav_audio(tmp_path):
    import numpy as np
    import soundfile as sf

    flac_src = tmp_path / "src" / "song.flac"
    flac_src.parent.mkdir(parents=True)
    sr = 44100
    sf.write(str(flac_src), np.zeros(int(sr * 0.25), dtype="float32"), sr)

    out_dir = tmp_path / "out" / "song"
    analysis = make_analysis_fixture(audio_path=flac_src)
    cuesheet = make_cuesheet_fixture(source_sha256=analysis.source.sha256)

    manifest = build_cedartoy_folder(
        audio_path=flac_src,
        analysis=analysis,
        cuesheet=cuesheet,
        out_dir=out_dir,
        grammar="concert_visuals",
        musicue_version="0.4.1-test",
    )

    out_wav = out_dir / "song.wav"
    assert out_wav.exists()
    info = sf.info(str(out_wav))
    assert info.samplerate == sr
    # Manifest records the original filename so the destination machine
    # can show "(originally song.flac)".
    assert manifest.original_audio == "song.flac"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_cedartoy_folder.py::test_build_folder_decodes_non_wav_audio -v`
Expected: PASS (existing implementation already handles this branch)

If FAIL: check that `make_analysis_fixture` accepts an audio path with a non-`.wav` suffix. If it hard-codes WAV, update it to read the actual file's sha256 in Task 2's refactor step.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cedartoy_folder.py
git commit -m "test(cedartoy): pin non-WAV source audio decoding behavior"
```

---

## Task 5: Atomic-rename failure leaves no partial folder

**Files:**
- Modify: `tests/test_cedartoy_folder.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_cedartoy_folder.py`:

```python
def test_build_folder_atomic_on_failure(tmp_path, monkeypatch):
    audio_src = tmp_path / "src" / "song.wav"
    audio_src.parent.mkdir(parents=True)
    _write_silent_wav(audio_src)

    out_dir = tmp_path / "out" / "song"
    analysis = make_analysis_fixture(audio_path=audio_src)
    cuesheet = make_cuesheet_fixture(source_sha256=analysis.source.sha256)

    # Force build_bundle to raise to simulate mid-build failure.
    import musicue.compile.cedartoy_folder as mod
    def boom(*a, **kw):
        raise RuntimeError("synthetic build_bundle failure")
    monkeypatch.setattr(mod, "build_bundle", boom)

    with pytest.raises(RuntimeError, match="synthetic"):
        build_cedartoy_folder(
            audio_path=audio_src,
            analysis=analysis,
            cuesheet=cuesheet,
            out_dir=out_dir,
            grammar="concert_visuals",
            musicue_version="0.4.1-test",
        )

    # No folder at the target.
    assert not out_dir.exists()
    # And no leftover .cedartoy-tmp-* siblings.
    assert not any(
        p.name.startswith(".cedartoy-tmp-")
        for p in out_dir.parent.iterdir()
    )
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_cedartoy_folder.py::test_build_folder_atomic_on_failure -v`
Expected: PASS (the implementation's try/except already cleans up).

If FAIL: the cleanup branch is missing — add `shutil.rmtree(tmp, ignore_errors=True)` to the `except` in `build_cedartoy_folder`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cedartoy_folder.py
git commit -m "test(cedartoy): pin atomic-rename failure cleanup"
```

---

## Task 6: CLI — `--folder` + `--include-stems` on `export-bundle` and `send-to-cedartoy` alias

**Files:**
- Modify: `musicue/cli.py`
- Modify: `tests/test_bundle_cli.py`

The existing `export-bundle` command lives at `musicue/cli.py:315-363`. It currently writes a single `<stem>.musicue.json` file. We add two new flags and an alias.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_bundle_cli.py`:

```python
def test_export_bundle_folder_writes_full_layout(tmp_path):
    """--folder switches to the four-file project layout."""
    from typer.testing import CliRunner
    from musicue.cli import app

    runner = CliRunner()
    audio = _write_fixture_audio(tmp_path / "song.wav")  # existing helper
    analysis_path = _write_fixture_analysis(tmp_path / "analysis.json", audio)
    cuesheet_path = _write_fixture_cuesheet(tmp_path / "cuesheet.json", audio)
    out = tmp_path / "exports" / "song"

    res = runner.invoke(app, [
        "export-bundle", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
        "--folder", str(out),
    ])
    assert res.exit_code == 0, res.stdout

    assert (out / "song.wav").exists()
    assert (out / "song.musicue.json").exists()
    assert (out / "manifest.json").exists()
    assert not (out / "stems").exists()


def test_export_bundle_folder_include_stems(tmp_path):
    """--include-stems copies stems from --stems-dir when present."""
    from typer.testing import CliRunner
    from musicue.cli import app

    runner = CliRunner()
    audio = _write_fixture_audio(tmp_path / "song.wav")
    analysis_path = _write_fixture_analysis(tmp_path / "analysis.json", audio)
    cuesheet_path = _write_fixture_cuesheet(tmp_path / "cuesheet.json", audio)

    stems = tmp_path / "stems"
    stems.mkdir()
    for name in ("drums", "bass", "vocals", "other"):
        _write_fixture_audio(stems / f"{name}.wav")

    out = tmp_path / "exports" / "song"
    res = runner.invoke(app, [
        "export-bundle", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
        "--folder", str(out),
        "--include-stems",
        "--stems-dir", str(stems),
    ])
    assert res.exit_code == 0, res.stdout
    for name in ("drums", "bass", "vocals", "other"):
        assert (out / "stems" / f"{name}.wav").exists()


def test_send_to_cedartoy_alias_runs(tmp_path):
    """`send-to-cedartoy` alias produces the same layout."""
    from typer.testing import CliRunner
    from musicue.cli import app

    runner = CliRunner()
    audio = _write_fixture_audio(tmp_path / "song.wav")
    analysis_path = _write_fixture_analysis(tmp_path / "analysis.json", audio)
    cuesheet_path = _write_fixture_cuesheet(tmp_path / "cuesheet.json", audio)
    out = tmp_path / "exports" / "song"

    res = runner.invoke(app, [
        "send-to-cedartoy", str(audio),
        "--analysis", str(analysis_path),
        "--cuesheet", str(cuesheet_path),
        "--output", str(out),
    ])
    assert res.exit_code == 0, res.stdout
    assert (out / "song.musicue.json").exists()
    assert (out / "manifest.json").exists()
```

If `_write_fixture_audio` / `_write_fixture_analysis` / `_write_fixture_cuesheet` do not already exist in `tests/test_bundle_cli.py`, add them at the top of the file:

```python
def _write_fixture_audio(path: Path) -> Path:
    import numpy as np
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    return path


def _write_fixture_analysis(path: Path, audio: Path) -> Path:
    from tests.test_bundle_builder import make_analysis_fixture
    analysis = make_analysis_fixture(audio_path=audio)
    path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    return path


def _write_fixture_cuesheet(path: Path, audio: Path) -> Path:
    from tests.test_bundle_builder import make_analysis_fixture, make_cuesheet_fixture
    analysis = make_analysis_fixture(audio_path=audio)
    cs = make_cuesheet_fixture(source_sha256=analysis.source.sha256)
    path.write_text(cs.model_dump_json(indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bundle_cli.py -v -k "folder or alias or include_stems"`
Expected: FAIL — `--folder`, `--include-stems`, `--stems-dir`, and `send-to-cedartoy` are unknown to Typer.

- [ ] **Step 3: Extend `export-bundle` and add the alias**

In `musicue/cli.py`, replace the existing `export_bundle` function with this version:

```python
@app.command(name="export-bundle")
def export_bundle(
    audio: Path = typer.Argument(..., help="Audio file (wav/flac/mp3)"),
    analysis: Optional[Path] = typer.Option(None, "--analysis"),
    cuesheet: Optional[Path] = typer.Option(None, "--cuesheet"),
    grammar: str = typer.Option("concert_visuals", "--grammar", "-g"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
        help="Single-file output path (legacy mode)."),
    folder: Optional[Path] = typer.Option(None, "--folder",
        help="Folder output path. Switches to the portable CedarToy "
             "project layout (song.wav + song.musicue.json + manifest.json + "
             "optional stems/)."),
    include_stems: bool = typer.Option(False, "--include-stems",
        help="Copy Demucs stems into <folder>/stems/. Requires --folder."),
    stems_dir: Optional[Path] = typer.Option(None, "--stems-dir",
        help="Override the source directory for stems (drums/bass/vocals/other.wav)."),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Compose AnalysisResult + CueSheet into a CedarToy-targeted output.

    Default: writes <audio_stem>.musicue.json next to the audio.
    With --folder: writes a portable project folder for CedarToy.
    """
    from musicue.analysis.pipeline import run_analysis
    from musicue.compile.bundle import build_bundle
    from musicue.compile.cedartoy_folder import build_cedartoy_folder
    from musicue.compile.compiler import compile_analysis
    from musicue.config import MusiCueConfig
    from musicue.schemas import AnalysisResult, CueSheet
    from importlib.metadata import version as _pkg_version

    if include_stems and folder is None:
        typer.echo("--include-stems requires --folder", err=True)
        raise typer.Exit(code=2)

    # Resolve analysis (run pipeline if missing).
    if analysis is None:
        cfg = MusiCueConfig()
        candidate = cfg.runs_dir / audio.stem / "analysis.json"
        if candidate.exists():
            analysis = candidate
        else:
            typer.echo(f"No analysis found; running pipeline on {audio}.")
            result = run_analysis(audio, cfg)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(result.model_dump_json(indent=2))
            analysis = candidate
    analysis_obj = AnalysisResult.model_validate_json(analysis.read_text())

    # Resolve cuesheet (compile if missing).
    if cuesheet is None:
        sibling = audio.with_suffix("").with_suffix(".cuesheet.json")
        if sibling.exists():
            cs_obj = CueSheet.model_validate_json(sibling.read_text())
        else:
            typer.echo(f"No cuesheet found; compiling with grammar '{grammar}'.")
            cs_obj = compile_analysis(analysis_obj, grammar=grammar)
    else:
        cs_obj = CueSheet.model_validate_json(cuesheet.read_text())

    # Folder mode: build the portable project layout.
    if folder is not None:
        if folder.exists():
            if not force:
                typer.echo(f"Refusing to overwrite {folder}; pass --force.", err=True)
                raise typer.Exit(code=1)
            import shutil as _sh
            _sh.rmtree(folder)

        # Default stems source: ~/.musicue/runs/<stem>/stems/ when --include-stems
        # is set but --stems-dir wasn't provided.
        effective_stems_dir = stems_dir
        if include_stems and effective_stems_dir is None:
            cfg = MusiCueConfig()
            effective_stems_dir = cfg.runs_dir / audio.stem / "stems"

        try:
            mc_ver = _pkg_version("musicue")
        except Exception:
            mc_ver = "0.0.0+dev"

        build_cedartoy_folder(
            audio_path=audio,
            analysis=analysis_obj,
            cuesheet=cs_obj,
            out_dir=folder,
            grammar=grammar,
            musicue_version=mc_ver,
            include_stems=include_stems,
            stems_src_dir=effective_stems_dir,
            original_audio_name=audio.name,
        )
        typer.echo(f"Project folder written to {folder}")
        return

    # Legacy single-file output.
    target = output if output else audio.with_suffix("").with_suffix(".musicue.json")
    if target.exists() and not force:
        typer.echo(f"Refusing to overwrite {target}; pass --force.", err=True)
        raise typer.Exit(code=1)
    bundle = build_bundle(analysis_obj, cs_obj)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bundle.model_dump_json(indent=2))
    typer.echo(f"Bundle written to {target}")


@app.command(name="send-to-cedartoy")
def send_to_cedartoy(
    audio: Path = typer.Argument(..., help="Audio file"),
    output: Path = typer.Option(..., "--output", "-o",
        help="Project folder to create."),
    analysis: Optional[Path] = typer.Option(None, "--analysis"),
    cuesheet: Optional[Path] = typer.Option(None, "--cuesheet"),
    grammar: str = typer.Option("concert_visuals", "--grammar", "-g"),
    include_stems: bool = typer.Option(True, "--include-stems/--no-stems"),
    stems_dir: Optional[Path] = typer.Option(None, "--stems-dir"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Alias: produce a portable CedarToy project folder."""
    # Thin re-dispatch to export-bundle's folder path so behavior stays in
    # one place.
    export_bundle(
        audio=audio,
        analysis=analysis,
        cuesheet=cuesheet,
        grammar=grammar,
        output=None,
        folder=output,
        include_stems=include_stems,
        stems_dir=stems_dir,
        force=force,
    )
```

- [ ] **Step 4: Run all CLI tests**

Run: `pytest tests/test_bundle_cli.py -v`
Expected: PASS (legacy tests + 3 new folder/alias tests).

- [ ] **Step 5: Commit**

```bash
git add musicue/cli.py tests/test_bundle_cli.py
git commit -m "feat(cli): add --folder/--include-stems + send-to-cedartoy alias"
```

---

## Task 7: FastAPI route — `POST /api/songs/{song_id}/analyses/{analysis_id}/send-to-cedartoy`

**Files:**
- Create: `musicue/ui/routes/cedartoy.py`
- Create: `tests/test_send_to_cedartoy_route.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_send_to_cedartoy_route.py
"""HTTP tests for the send-to-cedartoy endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from musicue.ui.server import create_app
from tests.test_bundle_builder import (
    make_analysis_fixture,
    make_cuesheet_fixture,
)


def _seed_song(storage_root: Path, source_sha: str, audio_bytes_path: Path) -> str:
    """Drop a song + analysis into the on-disk storage layout."""
    song_dir = storage_root / "songs" / source_sha
    (song_dir).mkdir(parents=True, exist_ok=True)
    target_audio = song_dir / "source.wav"
    import shutil
    shutil.copy2(audio_bytes_path, target_audio)
    (song_dir / "title.txt").write_text("Test Song", encoding="utf-8")

    analyses_dir = song_dir / "analyses" / "abc123"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    analysis = make_analysis_fixture(audio_path=target_audio)
    (analyses_dir / "analysis.json").write_text(
        analysis.model_dump_json(indent=2), encoding="utf-8"
    )
    return analysis.source.sha256


@pytest.fixture
def client(tmp_path):
    app = create_app(storage_root=tmp_path)
    return TestClient(app), tmp_path


def test_send_to_cedartoy_writes_folder(client, tmp_path):
    c, root = client

    # Seed a song + analysis whose sha matches the audio we just wrote.
    audio = tmp_path / "seed.wav"
    sf.write(str(audio), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    from musicue.ui.storage import sha256_of_file
    sha = sha256_of_file(audio)
    _seed_song(root, sha, audio)

    out = tmp_path / "exports" / "song"
    resp = c.post(
        f"/api/songs/{sha}/analyses/abc123/send-to-cedartoy",
        json={
            "output_folder": str(out),
            "grammar": "concert_visuals",
            "include_stems": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output_folder"] == str(out)
    assert body["ok"] is True

    assert (out / "song.wav").exists()
    assert (out / "song.musicue.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["grammar"] == "concert_visuals"


def test_send_to_cedartoy_404_when_song_missing(client, tmp_path):
    c, _root = client
    resp = c.post(
        "/api/songs/deadbeef/analyses/abc123/send-to-cedartoy",
        json={"output_folder": str(tmp_path / "out"), "grammar": "concert_visuals"},
    )
    assert resp.status_code == 404


def test_send_to_cedartoy_400_when_grammar_invalid(client, tmp_path):
    c, root = client
    audio = tmp_path / "seed.wav"
    sf.write(str(audio), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    from musicue.ui.storage import sha256_of_file
    sha = sha256_of_file(audio)
    _seed_song(root, sha, audio)

    resp = c.post(
        f"/api/songs/{sha}/analyses/abc123/send-to-cedartoy",
        json={"output_folder": str(tmp_path / "out"), "grammar": "bogus"},
    )
    assert resp.status_code == 400


def test_send_to_cedartoy_409_when_target_exists(client, tmp_path):
    c, root = client
    audio = tmp_path / "seed.wav"
    sf.write(str(audio), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    from musicue.ui.storage import sha256_of_file
    sha = sha256_of_file(audio)
    _seed_song(root, sha, audio)

    out = tmp_path / "out"
    out.mkdir()

    resp = c.post(
        f"/api/songs/{sha}/analyses/abc123/send-to-cedartoy",
        json={"output_folder": str(out), "grammar": "concert_visuals"},
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_send_to_cedartoy_route.py -v`
Expected: FAIL — endpoint returns 404 (route not registered).

- [ ] **Step 3: Implement the router**

```python
# musicue/ui/routes/cedartoy.py
"""Route: POST /api/songs/{song_id}/analyses/{analysis_id}/send-to-cedartoy.

Composes the existing analysis + a freshly-compiled cuesheet into a
portable CedarToy project folder on the server's filesystem. Same code
path the CLI uses; see musicue/compile/cedartoy_folder.py.
"""
from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from musicue.compile.cedartoy_folder import build_cedartoy_folder
from musicue.compile.compiler import compile_analysis
from musicue.schemas import AnalysisResult
from musicue.ui.routes._validators import (
    validate_analysis_id,
    validate_song_id,
)

router = APIRouter(prefix="/api/songs/{song_id}/analyses/{analysis_id}",
                   tags=["cedartoy"])

_GRAMMARS = ("concert_visuals", "character_animation", "lighting", "camera_edit")


class SendToCedarToyRequest(BaseModel):
    output_folder: str = Field(..., description="Server-local folder path to create.")
    grammar: str = Field("concert_visuals")
    include_stems: bool = False
    force_analyze: bool = Field(
        False,
        description="If true, re-run the analysis pipeline ignoring cache. "
                    "Blocks the request for the duration of analysis (~2 min). "
                    "Pre-existing analysis on disk is overwritten.",
    )


@router.post("/send-to-cedartoy")
def send_to_cedartoy(
    song_id: str,
    analysis_id: str,
    body: SendToCedarToyRequest,
    request: Request,
) -> dict:
    song_id = validate_song_id(song_id)
    analysis_id = validate_analysis_id(analysis_id)

    if body.grammar not in _GRAMMARS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown grammar '{body.grammar}'. Available: {', '.join(_GRAMMARS)}",
        )

    storage = request.app.state.storage
    song = storage.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="song not found")
    analysis_path = storage.analysis_dir(song_id, analysis_id) / "analysis.json"

    if body.force_analyze:
        # Re-run analysis synchronously. Blocks the request. Same pattern as
        # the /click endpoint, which also runs a multi-second pipeline inside
        # the request handler. Async-job delivery is a deferred improvement.
        from musicue.analysis.pipeline import run_analysis
        from musicue.config import MusiCueConfig
        cfg = MusiCueConfig()
        result = run_analysis(song.source_path, cfg)
        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        analysis_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    elif not analysis_path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")

    out_dir = Path(body.output_folder)
    if out_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"target folder already exists: {out_dir}",
        )

    try:
        analysis = AnalysisResult.model_validate_json(
            analysis_path.read_text(encoding="utf-8")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"analysis parse error: {e}") from e

    try:
        cuesheet = compile_analysis(analysis, grammar=body.grammar)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"compile failed: {e}") from e

    stems_src = storage.analysis_dir(song_id, analysis_id) / "stems"
    try:
        mc_ver = _pkg_version("musicue")
    except Exception:
        mc_ver = "0.0.0+dev"

    try:
        manifest = build_cedartoy_folder(
            audio_path=song.source_path,
            analysis=analysis,
            cuesheet=cuesheet,
            out_dir=out_dir,
            grammar=body.grammar,
            musicue_version=mc_ver,
            include_stems=body.include_stems,
            stems_src_dir=stems_src if body.include_stems else None,
            original_audio_name=song.source_path.name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"folder build failed: {e}") from e

    return {
        "ok": True,
        "output_folder": str(out_dir),
        "stems_included": manifest.stems_omitted_reason is None and body.include_stems,
        "stems_omitted_reason": manifest.stems_omitted_reason,
    }
```

- [ ] **Step 4: Verify `storage.get_song` exists**

Run: `grep -n "def get_song" musicue/ui/storage.py`
Expected: a method that returns a `SongRecord` or `None`.

If missing, add it — UIStorage already has the song-dir layout; reading `title.txt` + locating `source.<ext>` is straightforward. Add as a separate commit:

```python
def get_song(self, song_id: str) -> SongRecord | None:
    d = self.song_dir(song_id)
    if not d.exists():
        return None
    candidates = [p for p in d.iterdir() if p.name.startswith("source.")]
    if not candidates:
        return None
    src = candidates[0]
    title = (d / "title.txt").read_text(encoding="utf-8").strip() if (d / "title.txt").exists() else song_id
    return SongRecord(id=song_id, title=title, source_path=src,
                      source_ext=src.suffix.lstrip("."))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_send_to_cedartoy_route.py -v`
Expected: All four tests PASS. (Route is registered in Task 8 — if these tests fail because `create_app` doesn't include the router, complete Task 8 next and rerun.)

- [ ] **Step 6: Commit**

```bash
git add musicue/ui/routes/cedartoy.py tests/test_send_to_cedartoy_route.py musicue/ui/storage.py
git commit -m "feat(api): add send-to-cedartoy route + storage.get_song"
```

---

## Task 8: Register the new router in `server.py`

**Files:**
- Modify: `musicue/ui/server.py`

- [ ] **Step 1: Register the router**

In `musicue/ui/server.py`, find the block that imports `from musicue.ui.routes import ...` (around lines 49–55) and add `cedartoy`:

```python
from musicue.ui.routes import analyses as analyses_routes
from musicue.ui.routes import cedartoy as cedartoy_routes
from musicue.ui.routes import click as click_routes
# ... existing imports ...

app.include_router(songs_routes.router)
app.include_router(jobs_routes.router)
app.include_router(analyses_routes.router)
app.include_router(click_routes.router)
app.include_router(library_routes.router)
app.include_router(export_routes.router)
app.include_router(health_routes.router)
app.include_router(cedartoy_routes.router)   # NEW
```

- [ ] **Step 2: Run all route tests**

Run: `pytest tests/test_send_to_cedartoy_route.py -v`
Expected: PASS (4 tests)

- [ ] **Step 3: Commit**

```bash
git add musicue/ui/server.py
git commit -m "feat(api): register send-to-cedartoy router"
```

---

## Task 9: TS API client — `cedartoyApi.ts`

**Files:**
- Create: `musicue/ui/web/src/lib/cedartoyApi.ts`

- [ ] **Step 1: Write the client**

```typescript
// musicue/ui/web/src/lib/cedartoyApi.ts

export type CedarToyGrammar =
  | "concert_visuals"
  | "character_animation"
  | "lighting"
  | "camera_edit";

export interface SendToCedarToyRequest {
  output_folder: string;
  grammar: CedarToyGrammar;
  include_stems: boolean;
  force_analyze?: boolean;
}

export interface SendToCedarToyResponse {
  ok: boolean;
  output_folder: string;
  stems_included: boolean;
  stems_omitted_reason: string | null;
}

export async function sendToCedarToy(
  songId: string,
  analysisId: string,
  req: SendToCedarToyRequest,
): Promise<SendToCedarToyResponse> {
  const r = await fetch(
    `/api/songs/${songId}/analyses/${analysisId}/send-to-cedartoy`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    },
  );
  if (!r.ok) {
    let detail = "";
    try {
      const j = await r.json();
      detail = j.detail ?? JSON.stringify(j);
    } catch {
      detail = await r.text().catch(() => "");
    }
    throw new Error(`send-to-cedartoy failed (${r.status}): ${detail}`);
  }
  return (await r.json()) as SendToCedarToyResponse;
}
```

- [ ] **Step 2: Verify it type-checks**

Run: `cd musicue/ui/web && npx tsc --noEmit`
Expected: no errors related to this file.

- [ ] **Step 3: Commit**

```bash
git add musicue/ui/web/src/lib/cedartoyApi.ts
git commit -m "feat(ui): TS client for send-to-cedartoy endpoint"
```

---

## Task 10: React `SendToCedartoyDialog` component

**Files:**
- Create: `musicue/ui/web/src/components/SendToCedartoyDialog.tsx`

- [ ] **Step 1: Write the component**

```tsx
// musicue/ui/web/src/components/SendToCedartoyDialog.tsx
import { CSSProperties, useState } from "react";
import {
  CedarToyGrammar,
  sendToCedarToy,
} from "../lib/cedartoyApi";

interface Props {
  open: boolean;
  songId: string;
  analysisId: string;
  songTitle: string;
  onClose: () => void;
}

const GRAMMARS: Array<{ key: CedarToyGrammar; label: string }> = [
  { key: "concert_visuals", label: "Concert visuals" },
  { key: "character_animation", label: "Character animation" },
  { key: "lighting", label: "Lighting" },
  { key: "camera_edit", label: "Camera edit" },
];

export default function SendToCedartoyDialog({
  open,
  songId,
  analysisId,
  songTitle,
  onClose,
}: Props) {
  const safeName = songTitle.replace(/[\\/:*?"<>|]/g, "_");
  const [outputFolder, setOutputFolder] = useState<string>(
    `exports/${safeName}`,
  );
  const [grammar, setGrammar] = useState<CedarToyGrammar>("concert_visuals");
  const [includeStems, setIncludeStems] = useState<boolean>(true);
  const [forceAnalyze, setForceAnalyze] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  if (!open) return null;

  const handleSend = async () => {
    setBusy(true);
    setErr(null);
    setOkMsg(null);
    try {
      const res = await sendToCedarToy(songId, analysisId, {
        output_folder: outputFolder,
        grammar,
        include_stems: includeStems,
        force_analyze: forceAnalyze,
      });
      const stemsLine = res.stems_included
        ? "stems included"
        : res.stems_omitted_reason ?? "stems not included";
      setOkMsg(`Wrote ${res.output_folder} — ${stemsLine}.`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose} style={overlayStyle}>
      <div onClick={(e) => e.stopPropagation()} style={panelStyle}>
        <div style={{ fontSize: 16, marginBottom: 14, color: "#fff" }}>
          Send to CedarToy
        </div>

        <div style={gridStyle}>
          <label style={labelStyle}>Output folder</label>
          <input
            value={outputFolder}
            onChange={(e) => setOutputFolder(e.target.value)}
            style={inputStyle}
            placeholder="exports/<song>/"
          />

          <label style={labelStyle}>Grammar</label>
          <select
            value={grammar}
            onChange={(e) => setGrammar(e.target.value as CedarToyGrammar)}
            style={inputStyle}
          >
            {GRAMMARS.map((g) => (
              <option key={g.key} value={g.key}>{g.label}</option>
            ))}
          </select>

          <label style={labelStyle}>Stems</label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={includeStems}
              onChange={(e) => setIncludeStems(e.target.checked)}
            />
            Include stems (drums / bass / vocals / other)
          </label>

          <label style={labelStyle}>Analysis</label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={forceAnalyze}
              onChange={(e) => setForceAnalyze(e.target.checked)}
            />
            Force re-analyze (ignore cache, ~2 min)
          </label>
        </div>

        {err && <div style={{ marginTop: 14, color: "#f88", fontSize: 12 }}>{err}</div>}
        {okMsg && <div style={{ marginTop: 14, color: "#7ec97e", fontSize: 12 }}>{okMsg}</div>}

        <div style={actionsStyle}>
          <button onClick={onClose} disabled={busy} style={btnSecondary}>
            {okMsg ? "Close" : "Cancel"}
          </button>
          <button
            onClick={handleSend}
            disabled={busy || !outputFolder.trim()}
            style={btnPrimary}
          >
            {busy ? "Sending…" : "Export ▶"}
          </button>
        </div>
      </div>
    </div>
  );
}

const overlayStyle: CSSProperties = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
  display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
};
const panelStyle: CSSProperties = {
  background: "#161616", border: "1px solid #333", borderRadius: 6,
  padding: 20, minWidth: 480, color: "#ddd", fontSize: 13,
};
const gridStyle: CSSProperties = {
  display: "grid", gridTemplateColumns: "120px 1fr", gap: 10, alignItems: "center",
};
const labelStyle: CSSProperties = { color: "#bbb" };
const inputStyle: CSSProperties = {
  background: "#1a1a1a", color: "#eee", border: "1px solid #333",
  padding: "5px 8px", borderRadius: 4, fontSize: 13,
};
const actionsStyle: CSSProperties = {
  marginTop: 18, display: "flex", justifyContent: "flex-end", gap: 8,
};
const btnPrimary: CSSProperties = {
  background: "#3a5a8c", color: "#fff", border: "1px solid #5a7ab0",
  padding: "6px 16px", borderRadius: 4, cursor: "pointer", fontSize: 13,
};
const btnSecondary: CSSProperties = {
  background: "#1a1a1a", color: "#bbb", border: "1px solid #333",
  padding: "6px 16px", borderRadius: 4, cursor: "pointer", fontSize: 13,
};
```

- [ ] **Step 2: Type-check**

Run: `cd musicue/ui/web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add musicue/ui/web/src/components/SendToCedartoyDialog.tsx
git commit -m "feat(ui): SendToCedartoyDialog component"
```

---

## Task 11: Wire button + dialog into `Editor.tsx`

**Files:**
- Modify: `musicue/ui/web/src/pages/Editor.tsx`

- [ ] **Step 1: Add the import + state**

Near the existing `import ExportModal from "../components/ExportModal";` add:

```tsx
import SendToCedartoyDialog from "../components/SendToCedartoyDialog";
```

Near the existing `const [exportOpen, setExportOpen] = useState<boolean>(false);` (around line 47) add:

```tsx
const [cedarToyOpen, setCedarToyOpen] = useState<boolean>(false);
```

- [ ] **Step 2: Add the button next to "Export ▶"**

Locate the existing "Export ▶" button (around lines 156–170). Immediately AFTER its closing `</button>` and BEFORE the closing `</div>` that wraps the toolbar, insert:

```tsx
<button
  onClick={() => setCedarToyOpen(true)}
  title="Export a portable CedarToy project folder (audio + bundle + optional stems)."
  style={{
    background: "#1a1a1a",
    color: "#bbb",
    border: "1px solid #333",
    padding: "6px 14px",
    borderRadius: 4,
    cursor: "pointer",
    fontSize: 13,
    marginRight: 16,
  }}
>
  → Send to CedarToy
</button>
```

- [ ] **Step 3: Mount the dialog**

Immediately after the existing `<ExportModal .../>` element (around lines 172–178), add:

```tsx
<SendToCedartoyDialog
  open={cedarToyOpen}
  songId={songId!}
  analysisId={analysisId!}
  songTitle={song?.title ?? "song"}
  onClose={() => setCedarToyOpen(false)}
/>
```

- [ ] **Step 4: Type-check + smoke-build**

Run: `cd musicue/ui/web && npx tsc --noEmit && npm run build`
Expected: clean type-check; build succeeds.

- [ ] **Step 5: Manual smoke**

Run the UI server and click the new button against a song that has an analysis:

```bash
python -m musicue.cli serve --port 8765
# then in another shell:
curl -s http://127.0.0.1:8765/api/health
```

Open `http://127.0.0.1:8765/` in a browser, navigate to a song with a completed analysis, click `→ Send to CedarToy`, supply an output folder, and verify the folder is created on disk with `song.wav`, `song.musicue.json`, `manifest.json`, and (if checked) `stems/`.

- [ ] **Step 6: Commit**

```bash
git add musicue/ui/web/src/pages/Editor.tsx
git commit -m "feat(ui): wire Send to CedarToy button + dialog in Editor"
```

---

## Task 12: End-to-end integration sanity test

**Files:**
- Modify: `tests/test_send_to_cedartoy_route.py`

- [ ] **Step 1: Add the end-to-end test**

Append to `tests/test_send_to_cedartoy_route.py`:

```python
def test_send_to_cedartoy_with_stems(client, tmp_path):
    """End-to-end: cached stems on disk are copied into the output folder."""
    c, root = client

    audio = tmp_path / "seed.wav"
    sf.write(str(audio), np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")
    from musicue.ui.storage import sha256_of_file
    sha = sha256_of_file(audio)
    _seed_song(root, sha, audio)

    # Drop stems into the analysis dir to mimic a cached Demucs run.
    stems_dir = root / "songs" / sha / "analyses" / "abc123" / "stems"
    stems_dir.mkdir(parents=True)
    for name in ("drums", "bass", "vocals", "other"):
        sf.write(str(stems_dir / f"{name}.wav"),
                 np.zeros(11025, dtype="float32"), 44100, subtype="PCM_16")

    out = tmp_path / "exports" / "song"
    resp = c.post(
        f"/api/songs/{sha}/analyses/abc123/send-to-cedartoy",
        json={
            "output_folder": str(out),
            "grammar": "concert_visuals",
            "include_stems": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stems_included"] is True

    for name in ("drums", "bass", "vocals", "other"):
        assert (out / "stems" / f"{name}.wav").exists()
```

- [ ] **Step 2: Run all tests one final time**

Run: `pytest tests/test_cedartoy_folder.py tests/test_send_to_cedartoy_route.py tests/test_bundle_cli.py -v`
Expected: ALL PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_send_to_cedartoy_route.py
git commit -m "test(api): end-to-end stems-cached send-to-cedartoy"
```

---

## Done

After Task 12 the feature is shippable:

- CLI: `musicue export-bundle <audio> --folder <out> [--include-stems]`
- CLI alias: `musicue send-to-cedartoy <audio> --output <out>`
- HTTP: `POST /api/songs/{song_id}/analyses/{analysis_id}/send-to-cedartoy`
- Web: `→ Send to CedarToy` button on the Editor page, beside `Export ▶`.

Output is always the same folder layout the spec defined:

```
<out>/
  song.wav
  song.musicue.json
  manifest.json
  stems/                   (optional)
    drums.wav bass.wav vocals.wav other.wav
```

Hand-off targets:
- **Plan B-1** (CedarToy stage rail + project loader) consumes this folder format.
- **Plan C** (reactivity prompt + cookbook) is independent.
