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
    process: Optional[Any] = None
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
        config_data = _yaml_safe(config)
        with open(config_file, "w", encoding="utf-8") as fh:
            yaml.safe_dump(config_data, fh)
        record = RenderJobRecord(id=job_id, config=dict(config_data), config_file=config_file)
        self._jobs[job_id] = record
        return record

    def get_job(self, job_id: str) -> RenderJobRecord:
        return self._jobs[job_id]

    def mark_running(self, job_id: str, process_pid: int, process: Optional[Any] = None) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.RUNNING
        job.process_pid = process_pid
        job.process = process
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
        job.process = None
        self._cleanup_config(job)
        self._touch(job)

    def mark_error(self, job_id: str, error: Dict[str, Any]) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.ERROR
        job.error = dict(error)
        job.process = None
        self._cleanup_config(job)
        self._touch(job)

    def mark_cancelled(self, job_id: str) -> None:
        job = self.get_job(job_id)
        job.status = JobStatus.CANCELLED
        job.process = None
        self._cleanup_config(job)
        self._touch(job)

    def cancel_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job.process is not None and job.process.poll() is None:
            job.process.terminate()
        self.mark_cancelled(job_id)

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


def _yaml_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _yaml_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_yaml_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_yaml_safe(item) for item in value]
    return value
