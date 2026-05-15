from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cedartoy.diagnostics import run_preflight_checks
from cedartoy.render_estimate import estimate_render, load_history
from cedartoy.server.jobs import RenderJobManager


router = APIRouter()
job_manager = RenderJobManager(Path(gettempdir()) / "cedartoy_jobs")


class EstimateRequest(BaseModel):
    shader_basename: str
    width: int = Field(..., gt=0, le=32768)
    height: int = Field(..., gt=0, le=32768)
    fps: float = Field(..., gt=0, le=240)
    duration_sec: float = Field(..., gt=0)
    tile_count: int = Field(..., gt=0)
    ss_scale: float = Field(..., gt=0, le=8)
    format: str
    bit_depth: int


@router.post("/estimate")
def estimate(body: EstimateRequest) -> dict:
    """Compute time + size estimate using disk-cached history when available."""
    try:
        est = estimate_render(
            shader_basename=body.shader_basename,
            width=body.width, height=body.height,
            fps=body.fps, duration_sec=body.duration_sec,
            tile_count=body.tile_count, ss_scale=body.ss_scale,
            format=body.format, bit_depth=body.bit_depth,
            history=load_history(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "frame_time_sec": est.frame_time_sec,
        "total_frames": est.total_frames,
        "total_seconds": est.total_seconds,
        "output_bytes": est.output_bytes,
        "history_hit": est.history_hit,
        "exceeds_time_threshold_1h": est.exceeds_time_threshold(3600),
        "exceeds_size_threshold_50gb": est.exceeds_size_threshold(50 * 1024**3),
    }


class RenderConfig(BaseModel):
    config: Dict[str, Any]


@router.post("/start")
async def start_render(data: RenderConfig):
    """Create a render job and write its normalized config to a temp file."""
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


@router.post("/{job_id}/cancel")
async def cancel_render(job_id: str):
    """Cancel a render job by ID."""
    try:
        job_manager.cancel_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Render job not found")
    return {"status": "cancelled", "job_id": job_id}


@router.get("/{job_id}/status")
async def get_render_status(job_id: str):
    """Get current render job status."""
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
    """List render output artifacts for a completed or running job."""
    try:
        return {"artifacts": job_manager.list_artifacts(job_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Render job not found")
