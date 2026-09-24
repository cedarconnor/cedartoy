"""Reactivity scorecard endpoints: proxy render + score.

POST /api/scorecard/start queues a 512×256 proxy render of the given config
on the shared render job manager (so /api/render/{id}/status and
/api/render/{id}/cancel work on it too), then scores the frames and deletes
them. GET /api/scorecard/{job_id} returns status/progress and, once done,
the scorecard JSON.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import json
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from cedartoy.config import build_config
from cedartoy.scorecard import proxy_render_config, score_render_config
from cedartoy.server.api.files import is_path_allowed
from cedartoy.server.api.project import AUDIO_EXTENSIONS, BUNDLE_EXTENSIONS, _checked_file
from cedartoy.server.api.render import job_manager
from cedartoy.server.jobs import JobStatus

router = APIRouter()

SHADER_EXTENSIONS = {".glsl", ".frag", ".fs"}
# Channel sources that are not files (see Renderer channel binding).
_CHANNEL_KEYWORDS = {"audio", "shadertoy_audio", "history", "audiohistory", "audio_history"}
_SCORECARD_ROOT = Path(gettempdir()) / "cedartoy_scorecard"
# job id -> proxy frames dir, for jobs started here (GET refuses other jobs).
_scorecard_jobs: Dict[str, Path] = {}


class ScorecardRequest(BaseModel):
    config: Dict[str, Any]


def _check_path(value: Any, what: str, extensions=None) -> Path:
    """Same rules as the project endpoints: inside an allowed root, existing,
    and (when given) an allowed extension."""
    if extensions is not None:
        return _checked_file(str(value), extensions, what)
    p = Path(str(value)).resolve()
    if not is_path_allowed(p):
        raise HTTPException(status_code=403, detail=f"{what} path not in a loaded project")
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return p


def validate_config_paths(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Reject client-supplied paths outside the allowed roots; returns a copy
    with shader/audio/bundle resolved to absolute paths."""
    cfg = dict(raw)
    if not cfg.get("shader"):
        raise HTTPException(status_code=400, detail="config.shader is required")
    cfg["shader"] = str(_check_path(cfg["shader"], "shader", SHADER_EXTENSIONS))
    if cfg.get("audio_path"):
        cfg["audio_path"] = str(_check_path(cfg["audio_path"], "audio", AUDIO_EXTENSIONS))
    if cfg.get("bundle_path"):
        cfg["bundle_path"] = str(_check_path(cfg["bundle_path"], "bundle", BUNDLE_EXTENSIONS))
    # File channels (top-level or per multipass buffer) and buffer shaders.
    mp = cfg.get("multipass") if isinstance(cfg.get("multipass"), dict) else {}
    buffers = mp.get("buffers") if isinstance(mp.get("buffers"), dict) else {
        k: v for k, v in mp.items() if k not in ("execution_order", "buffers")}
    channel_maps = [cfg.get("iChannel_paths"), cfg.get("channels")]
    for b in buffers.values():
        if isinstance(b, dict):
            if b.get("shader"):
                _check_path(b["shader"], "buffer shader", SHADER_EXTENSIONS)
            channel_maps.append(b.get("channels"))
    for chans in channel_maps:
        vals = chans.values() if isinstance(chans, dict) else (chans or [])
        for v in vals:
            if not isinstance(v, str) or v in buffers or v.lower() in _CHANNEL_KEYWORDS:
                continue
            p = Path(v[5:] if v.startswith("file:") else v).expanduser().resolve()
            if not is_path_allowed(p):
                raise HTTPException(status_code=403,
                                    detail="channel file path not in a loaded project")
    return cfg


def _render_proxy(job) -> None:
    """Run the proxy render as a CLI subprocess (as the websocket path does),
    feeding progress/logs into the job record. Raises on failure."""
    cmd = [sys.executable, "-m", "cedartoy.cli", "render", "--config", str(job.config_file)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    job_manager.mark_running(job.id, proc.pid, process=proc)
    last_error = ""
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if line.startswith("[PROGRESS]"):
            try:
                job_manager.update_progress(job.id, json.loads(line[10:]))
                continue
            except (ValueError, KeyError):
                pass
        if line.startswith("[ERROR]"):
            last_error = line[7:].strip()
        if line:
            job_manager.append_log(job.id, line)
    proc.stdout.close()
    code = proc.wait()
    if job_manager.get_job(job.id).status == JobStatus.CANCELLED:
        return
    if code != 0:
        raise RuntimeError(f"proxy render failed (exit {code}) {last_error}".strip())


def run_scorecard_job(job_id: str) -> None:
    frames_dir = _scorecard_jobs[job_id]
    if not job_manager.claim_job(job_id):
        return
    job = job_manager.get_job(job_id)
    try:
        _render_proxy(job)
        if job_manager.get_job(job_id).status == JobStatus.CANCELLED:
            return
        result = score_render_config(job.config, frames_dir)
        job_manager.mark_complete(job_id, {"scorecard": result})
    except Exception as exc:  # surfaced through GET
        if job_manager.get_job(job_id).status != JobStatus.CANCELLED:
            job_manager.mark_error(job_id, {"message": str(exc)})
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


@router.post("/start")
def start_scorecard(body: ScorecardRequest, background: BackgroundTasks) -> dict:
    cfg = validate_config_paths(body.config)
    try:
        runtime = build_config(None, cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid config: {exc}") from exc
    frames_dir = _SCORECARD_ROOT / uuid4().hex
    frames_dir.mkdir(parents=True, exist_ok=True)
    job = job_manager.create_job(proxy_render_config(runtime, frames_dir))
    _scorecard_jobs[job.id] = frames_dir
    background.add_task(run_scorecard_job, job.id)
    return {"status": "queued", "job_id": job.id,
            "proxy": {"width": job.config["width"], "height": job.config["height"]}}


@router.get("/{job_id}")
def get_scorecard(job_id: str) -> dict:
    if job_id not in _scorecard_jobs:
        raise HTTPException(status_code=404, detail="scorecard job not found")
    job = job_manager.get_job(job_id)
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "scorecard": (job.result or {}).get("scorecard"),
    }
