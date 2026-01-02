from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

app = FastAPI(title="CedarToy Web UI", version="0.1.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "CedarToy Web UI is running"}

# Import and mount API routers
from .api import shaders, config, audio, render, files
from .websocket import router as ws_router

app.include_router(shaders.router, prefix="/api/shaders", tags=["shaders"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(audio.router, prefix="/api/audio", tags=["audio"])
app.include_router(render.router, prefix="/api/render", tags=["render"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(ws_router, prefix="/ws", tags=["websocket"])

# Serve static files (frontend) - MUST be last to not intercept API routes
web_dir = Path(__file__).parent.parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
