from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

app = FastAPI(title="CedarToy Web UI", version="0.1.0")

# CORS - restricted to localhost origins only for security
# This prevents cross-origin requests from untrusted sites
ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
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
