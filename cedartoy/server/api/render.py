from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cedartoy.server.jobs import RenderJobManager


router = APIRouter()
job_manager = RenderJobManager(Path(gettempdir()) / "cedartoy_jobs")


class RenderConfig(BaseModel):
    config: Dict[str, Any]


@router.post("/start")
async def start_render(data: RenderConfig):
    """Create a render job and write its normalized config to a temp file."""
    job = job_manager.create_job(data.config)
    return {"status": "queued", "job_id": job.id, "config_file": str(job.config_file)}


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
