# Production Reliability Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CedarToy reliable enough for long renders by adding typed configuration, safer render job lifecycle management, clearer diagnostics, and durable render artifacts.

**Architecture:** Introduce focused backend modules around the existing renderer instead of rewriting the rendering engine. `cedartoy.config_model` owns validated user config, `cedartoy.server.jobs` owns render job state, and the existing FastAPI/WebSocket routes become thin adapters. The UI consumes the same job/status/error contract used by CLI subprocess logs.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, pytest, plain browser Web Components, existing `moderngl` renderer.

---

## Scope

Stage 1 deliberately avoids changing shader math, multipass rendering behavior, and UI visual design. The work is limited to reliability surfaces that make existing features safer and easier to run:

- Validated config loading and config migration.
- Deterministic render job IDs, state transitions, cancellation, and log retention.
- Preflight diagnostics before long renders start.
- Artifact listing for completed renders.
- Tests for the new reliability contracts.

Stage 2 builds on these reliability contracts to make CedarToy more flexible for creative iteration. Stage 2 should start only after Stage 1 passes tests and the UI render job flow is stable.

## File Structure

- Create `cedartoy/config_model.py`: Pydantic models for normalized render config, multipass config, channel sources, and migration from legacy dictionaries.
- Modify `cedartoy/config.py`: Load files as raw data, then validate through `CedarToyConfig`.
- Modify `cedartoy/cli.py`: Convert validated config models into the existing `RenderJob`.
- Create `cedartoy/server/jobs.py`: In-process job manager with job IDs, status records, log ring buffer, cancellation, and artifact discovery.
- Modify `cedartoy/server/api/render.py`: Replace global mutable render state with `RenderJobManager`.
- Modify `cedartoy/server/websocket.py`: Start and stream a specific job by ID.
- Create `cedartoy/diagnostics.py`: Config, path, shader, output, and estimated resource checks.
- Modify `cedartoy/server/api/config.py`: Return schema and validation errors from the typed config model.
- Modify `web/js/api.js`: Add job-aware render API methods.
- Modify `web/js/components/render-panel.js`: Track job IDs, display retained diagnostics, and fetch completed artifacts.
- Create `tests/test_config_model.py`: Unit tests for config defaults, migration, validation, and CLI conversion.
- Create `tests/test_render_jobs.py`: Unit tests for job manager state transitions and artifact discovery.
- Create `tests/test_diagnostics.py`: Unit tests for preflight checks.
- Update `docs/DEVELOPER.md`: Document reliability architecture and extension points.
- Update `docs/USER_GUIDE.md`: Document new render status, diagnostics, and artifact behavior.

## Task 1: Typed Config Model

**Files:**
- Create: `cedartoy/config_model.py`
- Modify: `cedartoy/config.py`
- Modify: `cedartoy/cli.py`
- Test: `tests/test_config_model.py`

- [ ] **Step 1: Write failing config default and migration tests**

Create `tests/test_config_model.py` with these tests:

```python
from pathlib import Path

import pytest

from cedartoy.config_model import CedarToyConfig, normalize_config


def test_defaults_match_current_runtime_contract():
    cfg = CedarToyConfig(shader=Path("shaders/test.glsl"))

    assert cfg.width == 1920
    assert cfg.height == 1080
    assert cfg.fps == 60.0
    assert cfg.output_dir == Path("renders")
    assert cfg.output_pattern == "frame_{frame:05d}.{ext}"
    assert cfg.camera_mode == "2d"
    assert cfg.camera_params["tilt_deg"] == 65.0
    assert cfg.camera_params["ipd"] == 0.064


def test_migrates_legacy_camera_params_to_flat_fields():
    raw = {
        "shader": "shaders/test.glsl",
        "camera_params": {"tilt_deg": 12.5, "ipd": 0.07},
    }

    cfg = normalize_config(raw)

    assert cfg.camera_tilt_deg == 12.5
    assert cfg.camera_ipd == 0.07
    assert cfg.camera_params == {"tilt_deg": 12.5, "ipd": 0.07}


def test_rejects_invalid_render_dimensions():
    with pytest.raises(ValueError, match="width"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), width=0)

    with pytest.raises(ValueError, match="height"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), height=-1)


def test_preserves_nested_multipass_config():
    raw = {
        "shader": "shaders/test.glsl",
        "multipass": {
            "buffers": {
                "A": {"shader": "shaders/test.glsl", "channels": {0: "A"}},
                "Image": {
                    "shader": "shaders/test.glsl",
                    "outputs_to_screen": True,
                    "channels": {0: "A"},
                },
            }
        },
    }

    cfg = normalize_config(raw)

    assert cfg.multipass["buffers"]["A"]["channels"] == {0: "A"}
    assert cfg.multipass["buffers"]["Image"]["outputs_to_screen"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_config_model.py -q
```

Expected: FAIL because `cedartoy.config_model` does not exist.

- [ ] **Step 3: Add the config model**

Create `cedartoy/config_model.py`:

```python
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CameraMode = Literal["2d", "equirect", "ll180"]
StereoMode = Literal["none", "sbs", "tb"]
AudioMode = Literal["shadertoy", "history", "both"]
OutputFormat = Literal["png", "exr"]
BitDepth = Literal["8", "16f", "32f"]


class CedarToyConfig(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    shader: Path
    width: int = 1920
    height: int = 1080
    fps: float = 60.0
    duration_sec: float = 10.0
    frame_start: int = 0
    frame_end: int = 0
    tiles_x: int = 1
    tiles_y: int = 1
    ss_scale: float = 1.0
    temporal_samples: int = 1
    shutter: float = 0.5
    default_output_format: OutputFormat = "png"
    default_bit_depth: BitDepth = "8"
    audio_path: Optional[Path] = None
    audio_mode: AudioMode = "both"
    camera_mode: CameraMode = "2d"
    camera_stereo: StereoMode = "none"
    camera_fov: float = 90.0
    camera_tilt_deg: float = 65.0
    camera_ipd: float = 0.064
    output_dir: Path = Path("renders")
    output_pattern: str = "frame_{frame:05d}.{ext}"
    disk_streaming: Optional[bool] = None
    shader_parameters: Dict[str, Any] = Field(default_factory=dict)
    channels: Optional[Dict[int, str]] = None
    iChannel_paths: Optional[Dict[int, str]] = None
    multipass: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        camera_params = migrated.get("camera_params")
        if isinstance(camera_params, dict):
            if "camera_tilt_deg" not in migrated and "tilt_deg" in camera_params:
                migrated["camera_tilt_deg"] = camera_params["tilt_deg"]
            if "camera_ipd" not in migrated and "ipd" in camera_params:
                migrated["camera_ipd"] = camera_params["ipd"]
        return migrated

    @field_validator("width", "height", "tiles_x", "tiles_y", "temporal_samples")
    @classmethod
    def positive_int(cls, value: int, info):
        if value < 1:
            raise ValueError(f"{info.field_name} must be at least 1")
        return value

    @field_validator("fps", "ss_scale")
    @classmethod
    def positive_float(cls, value: float, info):
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value

    @field_validator("shutter")
    @classmethod
    def shutter_range(cls, value: float):
        if value < 0 or value > 1:
            raise ValueError("shutter must be between 0 and 1")
        return value

    @property
    def camera_params(self) -> Dict[str, float]:
        return {"tilt_deg": self.camera_tilt_deg, "ipd": self.camera_ipd}

    def to_runtime_dict(self) -> Dict[str, Any]:
        data = self.model_dump(mode="python")
        data["camera_params"] = self.camera_params
        return data


def normalize_config(raw: Dict[str, Any]) -> CedarToyConfig:
    return CedarToyConfig.model_validate(raw)
```

- [ ] **Step 4: Route config loading through the model**

Modify `cedartoy/config.py` so `build_config()` returns a normalized dictionary:

```python
from .config_model import normalize_config


def build_config(config_path: Optional[Path] = None, cli_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = load_defaults()

    if config_path:
        file_cfg = load_from_file(config_path)
        cfg = merge_configs(cfg, file_cfg)

    if cli_args:
        cfg = merge_configs(cfg, cli_args)

    normalized = normalize_config(cfg)
    return normalized.to_runtime_dict()
```

- [ ] **Step 5: Keep CLI conversion compatible**

Modify `cedartoy/cli.py` in `config_to_job()` to read `camera_params` from the normalized config while preserving flat fallback values:

```python
        camera_params=cfg.get("camera_params", {
            "tilt_deg": cfg["camera_tilt_deg"],
            "ipd": cfg["camera_ipd"],
        }),
```

- [ ] **Step 6: Run config tests**

Run:

```bash
python -m pytest tests/test_config_model.py -q
```

Expected: PASS.

- [ ] **Step 7: Run existing non-render tests**

Run:

```bash
python -m pytest tests/test_multipass.py tests/test_naming.py tests/test_temporal_offsets.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add cedartoy/config_model.py cedartoy/config.py cedartoy/cli.py tests/test_config_model.py
git commit -m "Add typed CedarToy configuration model"
```

## Task 2: Render Job Manager

**Files:**
- Create: `cedartoy/server/jobs.py`
- Modify: `cedartoy/server/api/render.py`
- Modify: `cedartoy/server/websocket.py`
- Test: `tests/test_render_jobs.py`

- [ ] **Step 1: Write failing job manager tests**

Create `tests/test_render_jobs.py`:

```python
from pathlib import Path

from cedartoy.server.jobs import JobStatus, RenderJobManager


def test_create_job_assigns_id_and_initial_state(tmp_path):
    manager = RenderJobManager(work_dir=tmp_path)

    job = manager.create_job({"shader": "shaders/test.glsl", "output_dir": str(tmp_path / "out")})

    assert job.id
    assert job.status == JobStatus.QUEUED
    assert job.config["shader"] == "shaders/test.glsl"
    assert job.config_file.exists()


def test_job_state_transitions_are_recorded(tmp_path):
    manager = RenderJobManager(work_dir=tmp_path)
    job = manager.create_job({"shader": "shaders/test.glsl"})

    manager.mark_running(job.id, process_pid=123)
    manager.append_log(job.id, "render started")
    manager.mark_complete(job.id, {"output_dir": str(tmp_path)})

    current = manager.get_job(job.id)
    assert current.status == JobStatus.COMPLETE
    assert current.process_pid == 123
    assert current.logs[-1].message == "render started"
    assert current.result == {"output_dir": str(tmp_path)}


def test_artifacts_are_listed_from_output_dir(tmp_path):
    output_dir = tmp_path / "renders"
    output_dir.mkdir()
    (output_dir / "frame_00001.png").write_bytes(b"png")
    (output_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    manager = RenderJobManager(work_dir=tmp_path)
    job = manager.create_job({"shader": "shaders/test.glsl", "output_dir": str(output_dir)})

    artifacts = manager.list_artifacts(job.id)

    assert artifacts == [{"name": "frame_00001.png", "path": str(output_dir / "frame_00001.png"), "size": 3}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_render_jobs.py -q
```

Expected: FAIL because `cedartoy.server.jobs` does not exist.

- [ ] **Step 3: Implement job records and manager**

Create `cedartoy/server/jobs.py`:

```python
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
from uuid import uuid4

import yaml


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class JobLogEntry:
    timestamp: str
    message: str
    level: str = "info"


@dataclass
class RenderJobRecord:
    id: str
    config: Dict[str, Any]
    config_file: Path
    status: JobStatus = JobStatus.QUEUED
    process_pid: Optional[int] = None
    progress: Dict[str, Any] = field(default_factory=lambda: {"frame": 0, "total": 0, "eta_sec": 0})
    logs: Deque[JobLogEntry] = field(default_factory=lambda: deque(maxlen=500))
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RenderJobManager:
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, RenderJobRecord] = {}

    def create_job(self, config: Dict[str, Any]) -> RenderJobRecord:
        job_id = uuid4().hex
        config_file = self.work_dir / f"{job_id}.yaml"
        with open(config_file, "w", encoding="utf-8") as fh:
            yaml.safe_dump(config, fh)
        record = RenderJobRecord(id=job_id, config=dict(config), config_file=config_file)
        self._jobs[job_id] = record
        return record

    def get_job(self, job_id: str) -> RenderJobRecord:
        return self._jobs[job_id]

    def mark_running(self, job_id: str, process_pid: int) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.RUNNING
        job.process_pid = process_pid
        self._touch(job)

    def update_progress(self, job_id: str, progress: Dict[str, Any]) -> None:
        job = self.get_job(job_id)
        job.progress = dict(progress)
        self._touch(job)

    def append_log(self, job_id: str, message: str, level: str = "info") -> None:
        job = self.get_job(job_id)
        job.logs.append(JobLogEntry(timestamp=datetime.now(timezone.utc).isoformat(), message=message, level=level))
        self._touch(job)

    def mark_complete(self, job_id: str, result: Dict[str, Any]) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.COMPLETE
        job.result = dict(result)
        self._cleanup_config(job)
        self._touch(job)

    def mark_error(self, job_id: str, error: Dict[str, Any]) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.ERROR
        job.error = dict(error)
        self._cleanup_config(job)
        self._touch(job)

    def mark_cancelled(self, job_id: str) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.CANCELLED
        self._cleanup_config(job)
        self._touch(job)

    def list_artifacts(self, job_id: str) -> List[Dict[str, Any]]:
        job = self.get_job(job_id)
        output_dir = Path(str(job.config.get("output_dir", "renders")))
        if not output_dir.exists():
            return []
        suffixes = {".png", ".exr", ".jpg", ".jpeg", ".tif", ".tiff"}
        artifacts = []
        for path in sorted(output_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in suffixes:
                artifacts.append({"name": path.name, "path": str(path), "size": path.stat().st_size})
        return artifacts

    def _cleanup_config(self, job: RenderJobRecord) -> None:
        try:
            job.config_file.unlink()
        except FileNotFoundError:
            pass

    def _touch(self, job: RenderJobRecord) -> None:
        job.updated_at = datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Replace render API global state**

Modify `cedartoy/server/api/render.py` so it exposes job-aware endpoints:

```python
from pathlib import Path
from tempfile import gettempdir

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

from cedartoy.server.jobs import RenderJobManager


router = APIRouter()
job_manager = RenderJobManager(Path(gettempdir()) / "cedartoy_jobs")


class RenderConfig(BaseModel):
    config: Dict[str, Any]


@router.post("/start")
async def start_render(data: RenderConfig):
    job = job_manager.create_job(data.config)
    return {"status": "queued", "job_id": job.id, "config_file": str(job.config_file)}


@router.post("/{job_id}/cancel")
async def cancel_render(job_id: str):
    try:
        job = job_manager.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Render job not found")
    job_manager.mark_cancelled(job.id)
    return {"status": "cancelled", "job_id": job.id}


@router.get("/{job_id}/status")
async def get_render_status(job_id: str):
    try:
        job = job_manager.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Render job not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "logs": [entry.__dict__ for entry in job.logs],
    }


@router.get("/{job_id}/artifacts")
async def list_render_artifacts(job_id: str):
    try:
        return {"artifacts": job_manager.list_artifacts(job_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Render job not found")
```

- [ ] **Step 5: Update WebSocket to start by job ID**

Modify `cedartoy/server/websocket.py` to import `job_manager`, fetch the job by ID, and update job state while streaming:

```python
from .api.render import job_manager


async def handle_render(websocket: WebSocket, data):
    job_id = data.get("job_id")
    if not job_id:
        await websocket.send_json({"type": "render_error", "message": "No job_id provided"})
        return

    try:
        job = job_manager.get_job(job_id)
    except KeyError:
        await websocket.send_json({"type": "render_error", "message": "Render job not found", "job_id": job_id})
        return

    cmd = [sys.executable, "-m", "cedartoy.cli", "render", "--config", str(job.config_file)]
```

After `subprocess.Popen(...)`, call:

```python
job_manager.mark_running(job_id, process.pid)
```

When progress is parsed in `process_log_line`, pass `job_id` into the function and call:

```python
job_manager.update_progress(job_id, progress_data)
```

When regular logs are parsed, call:

```python
job_manager.append_log(job_id, message)
```

When complete data is parsed, call:

```python
job_manager.mark_complete(job_id, complete_data)
```

When error data is parsed, call:

```python
job_manager.mark_error(job_id, error_data)
```

- [ ] **Step 6: Run job manager tests**

Run:

```bash
python -m pytest tests/test_render_jobs.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cedartoy/server/jobs.py cedartoy/server/api/render.py cedartoy/server/websocket.py tests/test_render_jobs.py
git commit -m "Add render job lifecycle manager"
```

## Task 3: Preflight Diagnostics

**Files:**
- Create: `cedartoy/diagnostics.py`
- Modify: `cedartoy/server/api/render.py`
- Test: `tests/test_diagnostics.py`

- [ ] **Step 1: Write failing diagnostics tests**

Create `tests/test_diagnostics.py`:

```python
from pathlib import Path

from cedartoy.diagnostics import DiagnosticSeverity, run_preflight_checks


def test_preflight_reports_missing_shader():
    result = run_preflight_checks({"shader": "missing-file.glsl", "width": 64, "height": 64})

    assert result.ok is False
    assert result.items[0].severity == DiagnosticSeverity.ERROR
    assert "Shader file not found" in result.items[0].message


def test_preflight_warns_about_large_memory_estimate(tmp_path):
    shader = tmp_path / "shader.glsl"
    shader.write_text("void mainImage(out vec4 fragColor, in vec2 fragCoord){ fragColor = vec4(1.0); }", encoding="utf-8")

    result = run_preflight_checks({
        "shader": str(shader),
        "width": 16384,
        "height": 16384,
        "ss_scale": 2,
        "tiles_x": 1,
        "tiles_y": 1,
    })

    assert any(item.code == "memory.estimate.high" for item in result.items)


def test_preflight_passes_small_valid_shader(tmp_path):
    shader = tmp_path / "shader.glsl"
    shader.write_text("void mainImage(out vec4 fragColor, in vec2 fragCoord){ fragColor = vec4(1.0); }", encoding="utf-8")

    result = run_preflight_checks({"shader": str(shader), "width": 64, "height": 64})

    assert result.ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_diagnostics.py -q
```

Expected: FAIL because `cedartoy.diagnostics` does not exist.

- [ ] **Step 3: Implement preflight checks**

Create `cedartoy/diagnostics.py`:

```python
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, List


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class DiagnosticItem:
    severity: DiagnosticSeverity
    code: str
    message: str


@dataclass
class DiagnosticResult:
    items: List[DiagnosticItem]

    @property
    def ok(self) -> bool:
        return not any(item.severity == DiagnosticSeverity.ERROR for item in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "items": [
                {"severity": item.severity, "code": item.code, "message": item.message}
                for item in self.items
            ],
        }


def run_preflight_checks(config: Dict[str, Any]) -> DiagnosticResult:
    items: List[DiagnosticItem] = []
    shader = Path(str(config.get("shader", "")))

    if not shader.exists():
        items.append(DiagnosticItem(
            DiagnosticSeverity.ERROR,
            "shader.missing",
            f"Shader file not found: {shader}",
        ))
    elif not shader.is_file():
        items.append(DiagnosticItem(
            DiagnosticSeverity.ERROR,
            "shader.not_file",
            f"Shader path is not a file: {shader}",
        ))

    width = int(config.get("width", 1920))
    height = int(config.get("height", 1080))
    ss_scale = float(config.get("ss_scale", 1.0))
    tiles_x = int(config.get("tiles_x", 1))
    tiles_y = int(config.get("tiles_y", 1))

    internal_width = max(1, int(round(width * ss_scale)))
    internal_height = max(1, int(round(height * ss_scale)))
    full_rgba32_bytes = internal_width * internal_height * 4 * 4
    tile_rgba32_bytes = ((internal_width + tiles_x - 1) // tiles_x) * ((internal_height + tiles_y - 1) // tiles_y) * 4 * 4

    if full_rgba32_bytes > 4 * 1024**3 and tiles_x * tiles_y == 1:
        gb = full_rgba32_bytes / 1024**3
        items.append(DiagnosticItem(
            DiagnosticSeverity.WARNING,
            "memory.estimate.high",
            f"Estimated full-frame RGBA32 accumulation buffer is {gb:.2f} GB. Increase tiles_x/tiles_y or enable disk_streaming for safer long renders.",
        ))

    if tile_rgba32_bytes > 1024**3:
        gb = tile_rgba32_bytes / 1024**3
        items.append(DiagnosticItem(
            DiagnosticSeverity.WARNING,
            "memory.tile.high",
            f"Estimated per-tile RGBA32 buffer is {gb:.2f} GB. Use more tiles for lower peak memory.",
        ))

    output_dir = Path(str(config.get("output_dir", "renders")))
    if output_dir.exists() and not output_dir.is_dir():
        items.append(DiagnosticItem(
            DiagnosticSeverity.ERROR,
            "output.not_directory",
            f"Output path exists and is not a directory: {output_dir}",
        ))

    return DiagnosticResult(items)
```

- [ ] **Step 4: Add preflight API behavior**

Modify `cedartoy/server/api/render.py` so `start_render()` runs preflight before creating a job:

```python
from cedartoy.diagnostics import run_preflight_checks


@router.post("/start")
async def start_render(data: RenderConfig):
    diagnostics = run_preflight_checks(data.config)
    if not diagnostics.ok:
        raise HTTPException(status_code=400, detail=diagnostics.to_dict())
    job = job_manager.create_job(data.config)
    return {
        "status": "queued",
        "job_id": job.id,
        "config_file": str(job.config_file),
        "diagnostics": diagnostics.to_dict(),
    }
```

- [ ] **Step 5: Run diagnostics tests**

Run:

```bash
python -m pytest tests/test_diagnostics.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cedartoy/diagnostics.py cedartoy/server/api/render.py tests/test_diagnostics.py
git commit -m "Add render preflight diagnostics"
```

## Task 4: Frontend Job-Aware Render Panel

**Files:**
- Modify: `web/js/api.js`
- Modify: `web/js/components/render-panel.js`

- [ ] **Step 1: Update API client methods**

Modify the render section of `web/js/api.js`:

```javascript
    async startRender(config) {
        const res = await fetch(`${API_BASE}/render/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(JSON.stringify(data.detail || data));
        }
        return data;
    },

    async cancelRender(jobId) {
        const res = await fetch(`${API_BASE}/render/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
        return await res.json();
    },

    async getRenderStatus(jobId) {
        const res = await fetch(`${API_BASE}/render/${encodeURIComponent(jobId)}/status`);
        return await res.json();
    },

    async listRenderArtifacts(jobId) {
        const res = await fetch(`${API_BASE}/render/${encodeURIComponent(jobId)}/artifacts`);
        return await res.json();
    }
```

- [ ] **Step 2: Store job ID in render panel**

Modify `web/js/components/render-panel.js` constructor:

```javascript
        this.jobId = null;
        this.artifacts = [];
        this.diagnostics = null;
```

- [ ] **Step 3: Send job ID over WebSocket**

Modify `startRender()` in `web/js/components/render-panel.js`:

```javascript
            const result = await api.startRender(config);
            this.jobId = result.job_id;
            this.diagnostics = result.diagnostics;
            this.addLog(`Queued render job: ${this.jobId}`);

            wsClient.send({
                type: 'start_render',
                job_id: this.jobId
            });
```

- [ ] **Step 4: Cancel by job ID**

Modify `cancelRender()`:

```javascript
            if (!this.jobId) {
                this.addLog('No active job to cancel');
                return;
            }
            await api.cancelRender(this.jobId);
            this.state = 'idle';
            this.addLog(`Render cancelled: ${this.jobId}`);
            this.render();
```

- [ ] **Step 5: Fetch artifacts on completion**

Modify the `render_complete` WebSocket handler:

```javascript
        wsClient.on('render_complete', async (data) => {
            this.state = 'complete';
            if (data.output_dir) {
                this.outputDir = data.output_dir;
                this.addLog(`Render complete. Output: ${data.output_dir}`);
            } else {
                this.addLog('Render complete.');
            }
            if (this.jobId) {
                const artifacts = await api.listRenderArtifacts(this.jobId);
                this.artifacts = artifacts.artifacts || [];
            }
            this.render();
        });
```

- [ ] **Step 6: Render artifact list**

In `render()`, below the complete state block, add:

```javascript
                ${this.artifacts.length > 0 ? `
                    <div class="render-artifacts" style="margin-top: 8px; font-size: 0.85rem;">
                        ${this.artifacts.slice(0, 10).map(item => `
                            <div>${this.escapeHtml(item.name)} (${Math.round(item.size / 1024)} KB)</div>
                        `).join('')}
                    </div>
                ` : ''}
```

- [ ] **Step 7: Manual browser verification**

Run:

```bash
python -m cedartoy.cli ui --no-browser
```

Open `http://localhost:8080`, select `shaders/test.glsl`, set duration to `1`, start a render, and verify:

- A job ID appears in logs.
- Progress updates.
- Completion shows output artifacts.
- Cancellation sends a request containing the job ID.

- [ ] **Step 8: Commit**

```bash
git add web/js/api.js web/js/components/render-panel.js
git commit -m "Make render panel job-aware"
```

## Task 5: Documentation and End-to-End Verification

**Files:**
- Modify: `docs/DEVELOPER.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1: Update developer architecture docs**

Add this section to `docs/DEVELOPER.md`:

```markdown
## Production Reliability Architecture

Validated user configuration is owned by `cedartoy.config_model.CedarToyConfig`. File loading remains in `cedartoy.config`, but callers should treat raw dictionaries as untrusted until they pass through `normalize_config()`.

Render job lifecycle state is owned by `cedartoy.server.jobs.RenderJobManager`. API and WebSocket modules should not maintain their own global process state. The manager records job ID, status, progress, retained logs, final result, errors, and output artifacts.

Preflight checks live in `cedartoy.diagnostics`. These checks run before a UI render job is queued so missing shaders, invalid output paths, and risky memory estimates are reported before the renderer creates an OpenGL context.
```

- [ ] **Step 2: Update user guide**

Add this section to `docs/USER_GUIDE.md`:

```markdown
## Render Reliability

The Web UI assigns every render a job ID. Progress, logs, completion state, and output artifacts are tracked against that job ID, so a render can be inspected after it finishes or fails.

Before a render starts, CedarToy runs preflight checks. Errors block the render, while warnings are shown in the render logs and allow the render to continue. Common warnings include high estimated memory use for large untiled renders.

Completed jobs list generated image artifacts from the configured output directory. For long sequences, only the first artifacts are shown in the UI summary; the full output remains in the configured output directory.
```

- [ ] **Step 3: Run full test suite**

Run:

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Run CLI smoke render**

Run:

```bash
python -m cedartoy.cli render shaders/test.glsl --output-dir renders/reliability_smoke --width 64 --height 64 --duration-sec 1 --fps 1
```

Expected: `renders/reliability_smoke/frame_00000.png` exists and the process exits with code `0`.

- [ ] **Step 5: Run UI smoke test**

Run:

```bash
python -m cedartoy.cli ui --no-browser
```

Expected manual checks:

- `GET /api/health` returns status `ok`.
- Starting a render returns `job_id`.
- WebSocket render messages include progress for the same job.
- Completed render shows artifacts in the render panel.

- [ ] **Step 6: Commit**

```bash
git add docs/DEVELOPER.md docs/USER_GUIDE.md
git commit -m "Document production reliability workflow"
```

## Stage 2: Creative Flexibility Layer

**Goal:** Turn CedarToy from a reliable render launcher into a flexible shader production workspace for fast look development, audio-reactive iteration, and reusable creative setups.

**Dependency on Stage 1:** Stage 2 depends on typed config, job IDs, diagnostics, and artifact discovery. Do not start Stage 2 by reworking the render API; consume the Stage 1 contracts.

**Architecture:** Add creative features as focused modules around the existing renderer and UI. The backend remains the source of truth for config validation and final rendering. The browser preview becomes a richer approximation of final output, with explicit warnings when a final-render feature cannot be previewed exactly.

### Stage 2 Task A: Render Profiles

**Files:**
- Create: `cedartoy/profiles.py`
- Modify: `cedartoy/config_model.py`
- Modify: `cedartoy/server/api/config.py`
- Modify: `web/js/components/config-editor.js`
- Test: `tests/test_profiles.py`

**Behavior:**
- Built-in profiles: `preview`, `draft`, `final`, `vr180_final`, and `audio_sync_check`.
- Profiles patch existing config rather than replacing it.
- User config wins over profile defaults when both specify the same field.

**Profile definitions:**

```python
BUILTIN_PROFILES = {
    "preview": {"width": 640, "height": 360, "fps": 30.0, "duration_sec": 2.0, "temporal_samples": 1, "tiles_x": 1, "tiles_y": 1},
    "draft": {"width": 1280, "height": 720, "fps": 30.0, "temporal_samples": 1, "ss_scale": 1.0},
    "final": {"width": 3840, "height": 2160, "fps": 60.0, "temporal_samples": 8, "ss_scale": 1.0},
    "vr180_final": {"width": 4096, "height": 4096, "camera_mode": "ll180", "camera_tilt_deg": 65.0, "temporal_samples": 8},
    "audio_sync_check": {"width": 1280, "height": 720, "fps": 60.0, "duration_sec": 10.0, "audio_mode": "both"},
}
```

**Verification:**
- `python -m pytest tests/test_profiles.py -q` passes.
- UI can apply a profile, then edit individual fields without losing profile-derived values.

### Stage 2 Task B: Texture and Channel Manager

**Files:**
- Modify: `cedartoy/config_model.py`
- Modify: `cedartoy/cli.py`
- Modify: `cedartoy/server/api/files.py`
- Create: `web/js/components/channel-manager.js`
- Modify: `web/js/app.js`
- Modify: `web/index.html`
- Test: `tests/test_channel_config.py`

**Behavior:**
- UI exposes `iChannel0` through `iChannel3`.
- Each channel can be set to `none`, `audio`, `history`, `file:<path>`, or a multipass buffer name.
- The manager writes normalized `channels` for single-pass shaders and `multipass.buffers.<name>.channels` for multipass configs.
- File selection uses the existing allowed-roots API and does not bypass path restrictions.

**Channel schema:**

```python
ChannelKind = Literal["none", "audio", "history", "file", "buffer"]


class ChannelBinding(BaseModel):
    kind: ChannelKind
    value: Optional[str] = None

    def to_renderer_source(self) -> Optional[str]:
        if self.kind == "none":
            return None
        if self.kind in ("audio", "history"):
            return self.kind
        if self.kind == "file":
            return f"file:{self.value}"
        if self.kind == "buffer":
            return str(self.value)
        raise ValueError(f"Unsupported channel kind: {self.kind}")
```

**Verification:**
- `python -m pytest tests/test_channel_config.py -q` passes.
- In the UI, selecting an image file for `iChannel1` updates config and a final render binds it as `file:<path>`.

### Stage 2 Task C: Rich Shader Parameters

**Files:**
- Modify: `cedartoy/server/api/shaders.py`
- Modify: `cedartoy/config_model.py`
- Modify: `web/js/components/config-editor.js`
- Test: `tests/test_shader_metadata.py`

**Behavior:**
- Extend `// @param` metadata beyond float and int.
- Supported types: `float`, `int`, `bool`, `color`, `vec2`, `vec3`, and `enum`.
- Supported metadata fields: `group`, `step`, `default`, `min`, `max`, `label`, and enum `choices`.
- Existing float and int declarations continue to parse.

**Example shader comments:**

```glsl
// @param exposure float default=1.0 min=0.0 max=8.0 step=0.05 group="Tone" label="Exposure"
// @param tint color default="#ffcc88" group="Tone" label="Tint"
// @param orbit vec3 default="0.0,1.0,4.0" min="-10.0,-10.0,-10.0" max="10.0,10.0,10.0" group="Camera" label="Orbit"
// @param blend_mode enum default="screen" choices="normal,screen,add,multiply" group="Compositing" label="Blend Mode"
// @param beat_gate bool default=true group="Audio" label="Beat Gate"
```

**Verification:**
- `python -m pytest tests/test_shader_metadata.py -q` passes.
- UI renders appropriate controls for each parameter type and persists values under `shader_parameters`.

### Stage 2 Task D: WebGL Multipass Preview

**Files:**
- Create: `web/js/webgl/multipass-renderer.js`
- Modify: `web/js/webgl/renderer.js`
- Modify: `web/js/components/preview-panel.js`
- Modify: `cedartoy/server/api/shaders.py`

**Behavior:**
- Browser preview can compile and render configured multipass buffers in execution order.
- Each buffer renders into a WebGL framebuffer texture.
- Preview supports buffer-to-buffer channels and audio channel binding.
- Preview displays a clear unsupported-feature message for feedback buffers, EXR-only workflows, and final tiling.

**Preview contract:**

```javascript
const previewGraph = {
    buffers: {
        A: { shader: "shaders/tothebeat/buffer_a.glsl", channels: { 0: "audio" } },
        Image: { shader: "shaders/tothebeat/image.glsl", outputs_to_screen: true, channels: { 0: "A" } }
    },
    execution_order: ["A", "Image"]
};
```

**Verification:**
- A two-pass shader previews with buffer `A` feeding `Image`.
- A feedback shader shows a preview limitation message and still allows final render.

### Stage 2 Task E: Timeline Automation

**Files:**
- Create: `cedartoy/automation.py`
- Modify: `cedartoy/types.py`
- Modify: `cedartoy/render.py`
- Modify: `cedartoy/config_model.py`
- Create: `web/js/components/timeline-editor.js`
- Test: `tests/test_automation.py`

**Behavior:**
- Shader parameters can be keyframed over time.
- Supported interpolation: `hold`, `linear`, and `smoothstep`.
- Render-time parameter values are evaluated per frame before uniforms are bound.
- Automation config is stored under `automation.parameters.<param_name>`.

**Automation config example:**

```yaml
automation:
  parameters:
    exposure:
      interpolation: smoothstep
      keys:
        - time: 0.0
          value: 0.5
        - time: 3.0
          value: 2.0
        - time: 8.0
          value: 1.0
```

**Verification:**
- `python -m pytest tests/test_automation.py -q` passes.
- A shader parameter with automation changes value across rendered frames.

### Stage 2 Task F: Batch Rendering

**Files:**
- Create: `cedartoy/batch.py`
- Modify: `cedartoy/cli.py`
- Modify: `cedartoy/server/jobs.py`
- Modify: `web/js/components/render-panel.js`
- Test: `tests/test_batch.py`

**Behavior:**
- CLI supports `python -m cedartoy.cli batch batch.yaml`.
- Batch files define multiple render entries that share base config.
- UI can queue multiple configs as separate Stage 1 render jobs.
- Batch execution stops on the first failed job unless `continue_on_error: true`.

**Batch config example:**

```yaml
base:
  width: 1920
  height: 1080
  fps: 60
  duration_sec: 10
  default_output_format: png
jobs:
  - shader: shaders/auroras.glsl
    output_dir: renders/batch/auroras
  - shader: shaders/sun.glsl
    output_dir: renders/batch/sun
    shader_parameters:
      glow_strength: 2.5
continue_on_error: false
```

**Verification:**
- `python -m pytest tests/test_batch.py -q` passes.
- Running the batch example creates separate output folders for each job.

## Self-Review

- **Spec coverage:** Stage 1 covers typed config, job lifecycle, diagnostics, artifact listing, frontend integration, and docs. Stage 2 covers render profiles, channel management, richer shader parameters, multipass preview, timeline automation, and batch rendering.
- **Placeholder scan:** No unfinished requirements or hand-wavy implementation steps remain.
- **Type consistency:** `CedarToyConfig`, `RenderJobManager`, `JobStatus`, `run_preflight_checks`, `job_id`, `ChannelBinding`, and `automation.parameters` are named consistently across backend, frontend, and tests.
- **Testing coverage:** Each Stage 1 backend reliability unit has a focused pytest file, and final verification includes full tests, CLI smoke render, and UI smoke flow. Each Stage 2 creative unit names its own pytest target and manual verification path.
