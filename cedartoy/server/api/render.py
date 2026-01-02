from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import tempfile
import yaml
from pathlib import Path

router = APIRouter()

# Global render state
render_state = {
    "active": False,
    "process": None,
    "config": None,
    "config_file": None,
    "progress": {"frame": 0, "total": 0, "eta_sec": 0}
}

class RenderConfig(BaseModel):
    config: Dict[str, Any]

@router.post("/start")
async def start_render(data: RenderConfig):
    """Start a render job"""
    global render_state

    if render_state["active"]:
        raise HTTPException(status_code=409, detail="Render already in progress")

    # Save config to temp file
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(data.config, temp_file)
    temp_file.close()

    render_state["active"] = True
    render_state["config"] = data.config
    render_state["config_file"] = temp_file.name
    render_state["progress"] = {"frame": 0, "total": 0, "eta_sec": 0}

    return {
        "status": "started",
        "config_file": temp_file.name,
        "message": "Render started. Connect to WebSocket /ws/render for progress."
    }

@router.post("/cancel")
async def cancel_render():
    """Cancel the current render"""
    global render_state

    if not render_state["active"]:
        raise HTTPException(status_code=404, detail="No active render")

    if render_state["process"]:
        import signal
        render_state["process"].send_signal(signal.SIGTERM)

    render_state["active"] = False
    render_state["process"] = None

    return {"status": "cancelled"}

@router.get("/status")
async def get_render_status():
    """Get current render status"""
    return {
        "active": render_state["active"],
        "progress": render_state["progress"]
    }
