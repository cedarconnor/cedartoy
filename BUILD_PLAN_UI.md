# CedarToy Web UI - Implementation Plan

## Overview
This document provides a step-by-step implementation plan for building the CedarToy Web UI as specified in `docs/UI_DESIGN.md`.

---

## Phase 1: Foundation (Backend + Basic UI)

**Goal**: Set up FastAPI server, basic frontend structure, and config editor

### 1.1 Backend Setup

#### Task 1.1.1: Install Dependencies
**Files**: `requirements.txt`
```bash
# Add to requirements.txt
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
python-multipart>=0.0.6
websockets>=11.0
```

**Actions**:
- Add dependencies to `requirements.txt`
- Run `pip install -r requirements.txt`

---

#### Task 1.1.2: Create Server Package Structure
**New Files**:
- `cedartoy/server/__init__.py`
- `cedartoy/server/app.py`
- `cedartoy/server/api/__init__.py`
- `cedartoy/server/api/shaders.py`
- `cedartoy/server/api/config.py`
- `cedartoy/server/api/audio.py`
- `cedartoy/server/api/render.py`
- `cedartoy/server/websocket.py`

**Implementation**:

`cedartoy/server/__init__.py`:
```python
"""CedarToy Web UI Server"""
__version__ = "0.1.0"
```

`cedartoy/server/app.py`:
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
from pathlib import Path

from .api import shaders, config, audio, render
from .websocket import router as ws_router

app = FastAPI(title="CedarToy Web UI", version="0.1.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(shaders.router, prefix="/api/shaders", tags=["shaders"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(audio.router, prefix="/api/audio", tags=["audio"])
app.include_router(render.router, prefix="/api/render", tags=["render"])
app.include_router(ws_router, prefix="/ws", tags=["websocket"])

# Serve static files (frontend)
web_dir = Path(__file__).parent.parent.parent / "web"
app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
```

---

#### Task 1.1.3: Implement Shaders API
**File**: `cedartoy/server/api/shaders.py`

```python
from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict
import re

router = APIRouter()

SHADERS_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

@router.get("/", response_model=List[Dict])
async def list_shaders():
    """List all available shader files"""
    shaders = []
    for shader_path in SHADERS_DIR.rglob("*.glsl"):
        relative_path = shader_path.relative_to(SHADERS_DIR)

        # Parse metadata from shader comments
        metadata = _parse_shader_metadata(shader_path)

        shaders.append({
            "path": str(relative_path),
            "name": metadata.get("name", relative_path.stem),
            "author": metadata.get("author", "Unknown"),
            "description": metadata.get("description", ""),
        })

    return shaders

@router.get("/{shader_path:path}")
async def get_shader(shader_path: str):
    """Get shader source code"""
    full_path = SHADERS_DIR / shader_path

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Shader not found")

    # Security: ensure path is within shaders directory
    try:
        full_path.resolve().relative_to(SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    with open(full_path, 'r') as f:
        source = f.read()

    metadata = _parse_shader_metadata(full_path)

    return {
        "path": shader_path,
        "source": source,
        "metadata": metadata
    }

def _parse_shader_metadata(shader_path: Path) -> Dict:
    """Parse metadata from shader header comments"""
    metadata = {}

    with open(shader_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith("//"):
                break

            # Parse patterns like: // Name: My Shader
            match = re.match(r'^//\s*(\w+):\s*(.+)$', line)
            if match:
                key = match.group(1).lower()
                value = match.group(2).strip()
                metadata[key] = value

    return metadata
```

---

#### Task 1.1.4: Implement Files API (Directory Browser)
**File**: `cedartoy/server/api/files.py`

```python
from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict
import os

router = APIRouter()

@router.get("/browse")
async def browse_directory(path: str = "."):
    """Browse filesystem for directory/file selection"""
    try:
        target_path = Path(path).resolve()

        # Security: restrict to reasonable paths
        # Don't allow browsing system directories
        restricted = ['C:\\Windows', 'C:\\Program Files', '/etc', '/usr', '/bin']
        if any(str(target_path).startswith(r) for r in restricted):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        items = []

        # Add parent directory entry
        if target_path.parent != target_path:
            items.append({
                "name": "..",
                "path": str(target_path.parent),
                "type": "directory",
                "size": None
            })

        # List directory contents
        for item in sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                items.append({
                    "name": item.name,
                    "path": str(item),
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })
            except PermissionError:
                continue  # Skip items we can't access

        return {
            "current_path": str(target_path),
            "items": items
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/drives")
async def get_drives():
    """Get available drives (Windows only)"""
    import platform

    if platform.system() != "Windows":
        return {"drives": ["/"]}

    import string
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)

    return {"drives": drives}
```

Add to `app.py`:
```python
from .api import shaders, config, audio, render, files

app.include_router(files.router, prefix="/api/files", tags=["files"])
```

---

#### Task 1.1.5: Implement Config API
**File**: `cedartoy/server/api/config.py`

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
from pathlib import Path
import yaml
import json

from cedartoy.options_schema import OPTIONS
from cedartoy.config import load_defaults, build_config

router = APIRouter()

class ConfigData(BaseModel):
    config: Dict[str, Any]

@router.get("/schema")
async def get_schema():
    """Get options schema for form generation"""
    schema = []
    for opt in OPTIONS:
        schema.append({
            "name": opt.name,
            "label": opt.label,
            "type": opt.type,
            "default": opt.default,
            "choices": opt.choices if hasattr(opt, 'choices') else None,
            "help_text": opt.help_text,
        })
    return {"options": schema}

@router.get("/defaults")
async def get_defaults():
    """Get default configuration values"""
    defaults = load_defaults()
    return {"config": defaults}

@router.post("/save")
async def save_config(data: ConfigData, filepath: str = "cedartoy.yaml"):
    """Save configuration to YAML file"""
    try:
        path = Path(filepath)
        with open(path, 'w') as f:
            yaml.dump(data.config, f, default_flow_style=False)
        return {"status": "success", "path": str(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/load")
async def load_config(filepath: str):
    """Load configuration from YAML/JSON file"""
    try:
        path = Path(filepath)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        with open(path, 'r') as f:
            if path.suffix in ['.yaml', '.yml']:
                config = yaml.safe_load(f)
            elif path.suffix == '.json':
                config = json.load(f)
            else:
                raise HTTPException(status_code=400, detail="Unsupported file format")

        return {"config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/presets")
async def list_presets():
    """List saved preset configurations"""
    presets_dir = Path("presets")
    if not presets_dir.exists():
        return {"presets": []}

    presets = []
    for preset_file in presets_dir.glob("*.yaml"):
        presets.append({
            "name": preset_file.stem,
            "path": str(preset_file)
        })

    return {"presets": presets}

@router.post("/presets")
async def save_preset(data: ConfigData, name: str):
    """Save current config as a named preset"""
    presets_dir = Path("presets")
    presets_dir.mkdir(exist_ok=True)

    preset_path = presets_dir / f"{name}.yaml"
    with open(preset_path, 'w') as f:
        yaml.dump(data.config, f, default_flow_style=False)

    return {"status": "success", "path": str(preset_path)}
```

---

#### Task 1.1.6: Add UI Subcommand to CLI
**File**: `cedartoy/cli.py`

**Changes**:
1. Add new `ui` subcommand parser
2. Implement `run_ui_server()` function

```python
# Add to imports
import webbrowser
import uvicorn

# Add to main() function after existing subparsers
ui_parser = subparsers.add_parser('ui', help='Start web UI server')
ui_parser.add_argument('--port', type=int, default=8080, help='Server port')
ui_parser.add_argument('--no-browser', action='store_true', help='Do not open browser automatically')
ui_parser.set_defaults(func=run_ui_server)

# Add new function
def run_ui_server(args):
    """Start the FastAPI web UI server"""
    from cedartoy.server.app import app

    # Open browser automatically unless disabled
    if not args.no_browser:
        def open_browser():
            import time
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open(f'http://localhost:{args.port}')

        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    print(f"Starting CedarToy Web UI on http://localhost:{args.port}")
    print("Press Ctrl+C to stop")

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
```

---

### 1.2 Frontend Setup

#### Task 1.2.1: Create Basic HTML Structure
**File**: `web/index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CedarToy - Shader Renderer</title>
    <link rel="stylesheet" href="/css/main.css">
    <link rel="stylesheet" href="/css/components.css">
</head>
<body>
    <div id="app">
        <header class="app-header">
            <h1>🌲 CedarToy</h1>
            <nav>
                <a href="https://github.com/your-repo/cedartoy" target="_blank">GitHub</a>
                <a href="/docs/USER_GUIDE.md" target="_blank">Docs</a>
            </nav>
        </header>

        <main class="app-main">
            <aside class="shader-browser">
                <shader-browser></shader-browser>
            </aside>

            <section class="config-editor">
                <config-editor></config-editor>
            </section>

            <section class="preview-panel">
                <preview-panel></preview-panel>
                <audio-viz></audio-viz>
            </section>
        </main>

        <footer class="render-panel">
            <render-panel></render-panel>
        </footer>
    </div>

    <!-- Scripts -->
    <script type="module" src="/js/app.js"></script>
</body>
</html>
```

---

#### Task 1.2.2: Create Main CSS
**File**: `web/css/main.css`

```css
:root {
    /* Color scheme */
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --bg-tertiary: #0f3460;
    --accent: #e94560;
    --accent-secondary: #533483;
    --text-primary: #eaeaea;
    --text-secondary: #a0a0a0;
    --success: #4ecca3;
    --warning: #ffc107;
    --error: #e94560;

    /* Spacing */
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --spacing-xl: 32px;

    /* Border radius */
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 12px;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    background-color: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
}

#app {
    display: grid;
    grid-template-rows: auto 1fr auto;
    height: 100vh;
    overflow: hidden;
}

.app-header {
    background-color: var(--bg-secondary);
    padding: var(--spacing-md);
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid var(--accent);
}

.app-header h1 {
    font-size: 1.5rem;
    font-weight: 600;
}

.app-header nav a {
    margin-left: var(--spacing-md);
    color: var(--text-secondary);
    text-decoration: none;
    transition: color 0.2s;
}

.app-header nav a:hover {
    color: var(--accent);
}

.app-main {
    display: grid;
    grid-template-columns: 250px 1fr 600px;
    gap: var(--spacing-md);
    padding: var(--spacing-md);
    overflow: hidden;
}

.shader-browser,
.config-editor,
.preview-panel {
    background-color: var(--bg-secondary);
    border-radius: var(--radius-md);
    padding: var(--spacing-md);
    overflow-y: auto;
}

.render-panel {
    background-color: var(--bg-secondary);
    padding: var(--spacing-md);
    border-top: 2px solid var(--bg-tertiary);
}

/* Scrollbar styling */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--bg-tertiary);
}

::-webkit-scrollbar-thumb {
    background: var(--accent-secondary);
    border-radius: var(--radius-sm);
}

::-webkit-scrollbar-thumb:hover {
    background: var(--accent);
}
```

---

#### Task 1.2.3: Create Components CSS
**File**: `web/css/components.css`

```css
/* Buttons */
.btn {
    padding: var(--spacing-sm) var(--spacing-md);
    border: none;
    border-radius: var(--radius-sm);
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary {
    background-color: var(--accent);
    color: white;
}

.btn-primary:hover {
    background-color: #ff5872;
}

.btn-secondary {
    background-color: var(--bg-tertiary);
    color: var(--text-primary);
}

.btn-secondary:hover {
    background-color: #1a4d7a;
}

/* Form inputs */
.form-group {
    margin-bottom: var(--spacing-md);
}

.form-label {
    display: block;
    margin-bottom: var(--spacing-xs);
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.form-input,
.form-select {
    width: 100%;
    padding: var(--spacing-sm);
    background-color: var(--bg-tertiary);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: 0.9rem;
}

.form-input:focus,
.form-select:focus {
    outline: none;
    border-color: var(--accent);
}

/* Toggle switch */
.toggle {
    position: relative;
    display: inline-block;
    width: 50px;
    height: 24px;
}

.toggle input {
    opacity: 0;
    width: 0;
    height: 0;
}

.toggle-slider {
    position: absolute;
    cursor: pointer;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: var(--bg-tertiary);
    transition: 0.3s;
    border-radius: 24px;
}

.toggle-slider:before {
    position: absolute;
    content: "";
    height: 18px;
    width: 18px;
    left: 3px;
    bottom: 3px;
    background-color: white;
    transition: 0.3s;
    border-radius: 50%;
}

.toggle input:checked + .toggle-slider {
    background-color: var(--accent);
}

.toggle input:checked + .toggle-slider:before {
    transform: translateX(26px);
}

/* Progress bar */
.progress {
    width: 100%;
    height: 20px;
    background-color: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background-color: var(--accent);
    transition: width 0.3s;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 0.8rem;
    font-weight: 600;
}

/* Collapsible section */
.collapsible {
    margin-bottom: var(--spacing-sm);
}

.collapsible-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--spacing-sm);
    background-color: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    cursor: pointer;
    user-select: none;
}

.collapsible-header:hover {
    background-color: #1a4d7a;
}

.collapsible-content {
    padding: var(--spacing-md);
    display: none;
}

.collapsible.open .collapsible-content {
    display: block;
}

.collapsible-icon {
    transition: transform 0.3s;
}

.collapsible.open .collapsible-icon {
    transform: rotate(90deg);
}
```

---

#### Task 1.2.4: Create API Client
**File**: `web/js/api.js`

```javascript
/**
 * API client for CedarToy backend
 */

const API_BASE = '/api';

export const api = {
    // Shaders
    async listShaders() {
        const res = await fetch(`${API_BASE}/shaders/`);
        return await res.json();
    },

    async getShader(path) {
        const res = await fetch(`${API_BASE}/shaders/${encodeURIComponent(path)}`);
        return await res.json();
    },

    // Config
    async getSchema() {
        const res = await fetch(`${API_BASE}/config/schema`);
        return await res.json();
    },

    async getDefaults() {
        const res = await fetch(`${API_BASE}/config/defaults`);
        return await res.json();
    },

    async saveConfig(config, filepath = 'cedartoy.yaml') {
        const res = await fetch(`${API_BASE}/config/save?filepath=${encodeURIComponent(filepath)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        return await res.json();
    },

    async loadConfig(filepath) {
        const res = await fetch(`${API_BASE}/config/load?filepath=${encodeURIComponent(filepath)}`, {
            method: 'POST'
        });
        return await res.json();
    },

    async listPresets() {
        const res = await fetch(`${API_BASE}/config/presets`);
        return await res.json();
    },

    async savePreset(config, name) {
        const res = await fetch(`${API_BASE}/config/presets?name=${encodeURIComponent(name)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        return await res.json();
    },

    // Audio (placeholder for Phase 4)
    async uploadAudio(file) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/audio/upload`, {
            method: 'POST',
            body: formData
        });
        return await res.json();
    },

    // Render (placeholder for Phase 2)
    async startRender(config) {
        const res = await fetch(`${API_BASE}/render/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        return await res.json();
    },

    async cancelRender() {
        const res = await fetch(`${API_BASE}/render/cancel`, { method: 'POST' });
        return await res.json();
    },

    async getRenderStatus() {
        const res = await fetch(`${API_BASE}/render/status`);
        return await res.json();
    }
};
```

---

#### Task 1.2.5: Create Directory Browser Modal Component
**File**: `web/js/components/directory-browser.js`

```javascript
import { api } from '../api.js';

class DirectoryBrowser extends HTMLElement {
    constructor() {
        super();
        this.currentPath = '.';
        this.onSelect = null;
    }

    async show(initialPath = '.', onSelect) {
        this.currentPath = initialPath;
        this.onSelect = onSelect;
        await this.loadDirectory(this.currentPath);
        this.style.display = 'block';
    }

    hide() {
        this.style.display = 'none';
    }

    async connectedCallback() {
        this.style.display = 'none';
        this.render();
    }

    async loadDirectory(path) {
        const data = await fetch(`/api/files/browse?path=${encodeURIComponent(path)}`).then(r => r.json());
        this.currentPath = data.current_path;
        this.renderItems(data.items);
    }

    render() {
        this.innerHTML = `
            <div class="modal-overlay">
                <div class="modal-content" style="max-width: 600px; max-height: 500px;">
                    <div class="modal-header">
                        <h3>Select Directory</h3>
                        <button class="btn-close" id="close-btn">×</button>
                    </div>
                    <div class="modal-body">
                        <div class="path-bar" style="margin-bottom: 8px; padding: 8px; background: var(--bg-tertiary); border-radius: 4px;">
                            <strong>Path:</strong> <span id="current-path"></span>
                        </div>
                        <div id="items-list" style="max-height: 300px; overflow-y: auto;"></div>
                    </div>
                    <div class="modal-footer" style="display: flex; justify-content: space-between; margin-top: 16px;">
                        <button class="btn btn-secondary" id="select-current">Select Current Directory</button>
                        <button class="btn btn-secondary" id="cancel-btn">Cancel</button>
                    </div>
                </div>
            </div>
        `;

        this.attachEventListeners();
    }

    renderItems(items) {
        const itemsList = this.querySelector('#items-list');
        const currentPathEl = this.querySelector('#current-path');

        currentPathEl.textContent = this.currentPath;

        itemsList.innerHTML = items.map(item => `
            <div class="file-item" data-path="${item.path}" data-type="${item.type}"
                style="padding: 8px; cursor: pointer; display: flex; align-items: center; gap: 8px;
                border-bottom: 1px solid var(--bg-tertiary);">
                <span style="font-size: 1.2rem;">${item.type === 'directory' ? '📁' : '📄'}</span>
                <span style="flex: 1;">${item.name}</span>
                ${item.size !== null ? `<span style="color: var(--text-secondary); font-size: 0.85rem;">${this.formatSize(item.size)}</span>` : ''}
            </div>
        `).join('');

        // Add click handlers
        this.querySelectorAll('.file-item').forEach(item => {
            item.addEventListener('click', async () => {
                const path = item.dataset.path;
                const type = item.dataset.type;

                if (type === 'directory') {
                    await this.loadDirectory(path);
                }
            });
        });
    }

    attachEventListeners() {
        this.querySelector('#close-btn').addEventListener('click', () => this.hide());
        this.querySelector('#cancel-btn').addEventListener('click', () => this.hide());

        this.querySelector('#select-current').addEventListener('click', () => {
            if (this.onSelect) {
                this.onSelect(this.currentPath);
            }
            this.hide();
        });
    }

    formatSize(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
}

customElements.define('directory-browser', DirectoryBrowser);
```

Add to `index.html`:
```html
<directory-browser></directory-browser>
```

Add modal CSS to `web/css/components.css`:
```css
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.modal-content {
    background: var(--bg-secondary);
    border-radius: var(--radius-lg);
    padding: var(--spacing-lg);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
}

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--spacing-md);
}

.btn-close {
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 1.5rem;
    cursor: pointer;
    padding: 0;
    width: 30px;
    height: 30px;
}

.file-item:hover {
    background: var(--bg-tertiary);
}
```

---

#### Task 1.2.6: Create Config Editor Component
**File**: `web/js/components/config-editor.js`

```javascript
import { api } from '../api.js';

class ConfigEditor extends HTMLElement {
    constructor() {
        super();
        this.config = {};
        this.schema = [];
    }

    async connectedCallback() {
        // Load schema and defaults
        const [schemaData, defaultsData] = await Promise.all([
            api.getSchema(),
            api.getDefaults()
        ]);

        this.schema = schemaData.options;

        // Load from localStorage or use defaults
        const savedConfig = this.loadFromLocalStorage();
        this.config = savedConfig || defaultsData.config;

        this.render();
        this.attachEventListeners();
    }

    render() {
        // Group options by category
        const categories = this.groupByCategory();

        this.innerHTML = `
            <div class="config-editor-container">
                <div class="config-header">
                    <h2>Configuration</h2>
                    <div class="config-actions">
                        <button class="btn btn-secondary" id="import-btn">Import</button>
                        <button class="btn btn-secondary" id="export-btn">Export</button>
                        <button class="btn btn-secondary" id="preset-btn">Presets</button>
                    </div>
                </div>

                <div class="config-sections">
                    ${Object.entries(categories).map(([category, options]) => this.renderCategory(category, options)).join('')}
                </div>
            </div>
        `;
    }

    groupByCategory() {
        const categories = {
            'Output': [],
            'Resolution & Timing': [],
            'Quality': [],
            'Camera': [],
            'Audio': [],
            'Advanced': []
        };

        for (const opt of this.schema) {
            // Categorize based on name prefix or type
            if (opt.name.startsWith('output')) {
                categories['Output'].push(opt);
            } else if (['width', 'height', 'fps', 'duration_sec', 'frame_start', 'frame_end'].includes(opt.name)) {
                categories['Resolution & Timing'].push(opt);
            } else if (['ss_scale', 'temporal_samples', 'shutter', 'tiles_x', 'tiles_y'].includes(opt.name)) {
                categories['Quality'].push(opt);
            } else if (opt.name.startsWith('camera')) {
                categories['Camera'].push(opt);
            } else if (opt.name.startsWith('audio')) {
                categories['Audio'].push(opt);
            } else {
                categories['Advanced'].push(opt);
            }
        }

        return categories;
    }

    renderCategory(name, options) {
        const isOpen = ['Output', 'Resolution & Timing'].includes(name);

        return `
            <div class="collapsible ${isOpen ? 'open' : ''}">
                <div class="collapsible-header">
                    <span>${name}</span>
                    <span class="collapsible-icon">▶</span>
                </div>
                <div class="collapsible-content">
                    ${options.map(opt => this.renderField(opt)).join('')}
                </div>
            </div>
        `;
    }

    renderField(opt) {
        const value = this.config[opt.name] ?? opt.default;

        let inputHtml = '';

        switch (opt.type) {
            case 'bool':
                inputHtml = `
                    <label class="toggle">
                        <input type="checkbox" name="${opt.name}" ${value ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                `;
                break;

            case 'choice':
                inputHtml = `
                    <select class="form-select" name="${opt.name}">
                        ${opt.choices.map(choice =>
                            `<option value="${choice}" ${choice === value ? 'selected' : ''}>${choice}</option>`
                        ).join('')}
                    </select>
                `;
                break;

            case 'int':
                inputHtml = `<input type="number" class="form-input" name="${opt.name}" value="${value}" step="1">`;
                break;

            case 'float':
                inputHtml = `<input type="number" class="form-input" name="${opt.name}" value="${value}" step="0.1">`;
                break;

            case 'path':
                inputHtml = `
                    <div style="display: flex; gap: 8px;">
                        <input type="text" class="form-input path-input" name="${opt.name}" value="${value}" style="flex: 1;">
                        <button class="btn btn-secondary browse-btn" data-field="${opt.name}">📁</button>
                    </div>
                `;
                break;

            default:
                inputHtml = `<input type="text" class="form-input" name="${opt.name}" value="${value}">`;
        }

        return `
            <div class="form-group">
                <label class="form-label">${opt.label}</label>
                ${inputHtml}
                ${opt.help_text ? `<small style="color: var(--text-secondary); font-size: 0.8rem;">${opt.help_text}</small>` : ''}
            </div>
        `;
    }

    attachEventListeners() {
        // Collapsible sections
        this.querySelectorAll('.collapsible-header').forEach(header => {
            header.addEventListener('click', () => {
                header.parentElement.classList.toggle('open');
            });
        });

        // Form inputs - update config on change
        this.querySelectorAll('input, select').forEach(input => {
            input.addEventListener('change', (e) => {
                const name = e.target.name;
                let value = e.target.value;

                if (e.target.type === 'checkbox') {
                    value = e.target.checked;
                } else if (e.target.type === 'number') {
                    value = parseFloat(value);
                }

                this.config[name] = value;
                this.saveToLocalStorage();
                this.dispatchEvent(new CustomEvent('config-change', { detail: this.config }));
            });
        });

        // Directory browser buttons
        this.querySelectorAll('.browse-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const fieldName = btn.dataset.field;
                const currentValue = this.config[fieldName] || '.';

                const browser = document.querySelector('directory-browser');
                browser.show(currentValue, (selectedPath) => {
                    this.config[fieldName] = selectedPath;
                    const input = this.querySelector(`input[name="${fieldName}"]`);
                    if (input) input.value = selectedPath;
                    this.saveToLocalStorage();
                });
            });
        });

        // Export button
        this.querySelector('#export-btn')?.addEventListener('click', async () => {
            const filename = prompt('Save as:', 'cedartoy.yaml');
            if (filename) {
                await api.saveConfig(this.config, filename);
                alert(`Saved to ${filename}`);
            }
        });

        // Import button
        this.querySelector('#import-btn')?.addEventListener('click', async () => {
            const filename = prompt('Load from:', 'cedartoy.yaml');
            if (filename) {
                try {
                    const data = await api.loadConfig(filename);
                    this.config = data.config;
                    this.saveToLocalStorage();
                    this.render();
                    this.attachEventListeners();
                } catch (err) {
                    alert('Failed to load config: ' + err.message);
                }
            }
        });
    }

    saveToLocalStorage() {
        localStorage.setItem('cedartoy_config', JSON.stringify(this.config));
    }

    loadFromLocalStorage() {
        const saved = localStorage.getItem('cedartoy_config');
        if (saved) {
            try {
                return JSON.parse(saved);
            } catch (err) {
                console.error('Failed to parse saved config:', err);
            }
        }
        return null;
    }

    getConfig() {
        return this.config;
    }
}

customElements.define('config-editor', ConfigEditor);
```

---

#### Task 1.2.7: Create Shader Browser Component (with on-hover thumbnails)
**File**: `web/js/components/shader-browser.js`

```javascript
import { api } from '../api.js';

class ShaderBrowser extends HTMLElement {
    constructor() {
        super();
        this.thumbnailCache = new Map();
        this.currentHover = null;
    }

    async connectedCallback() {
        const shaders = await api.listShaders();

        this.innerHTML = `
            <div class="shader-browser-container">
                <h3>Shaders</h3>
                <input type="text" class="form-input" id="shader-search" placeholder="Search..." style="margin-bottom: 16px;">
                <div class="shader-list" id="shader-list">
                    ${shaders.map(shader => `
                        <div class="shader-item" data-path="${shader.path}" data-name="${shader.name}">
                            <div class="shader-name">${shader.name}</div>
                            <div class="shader-desc" style="font-size: 0.8rem; color: var(--text-secondary);">
                                ${shader.description || shader.path}
                            </div>
                            <div class="shader-thumbnail" style="display: none; position: absolute; z-index: 100;
                                border: 2px solid var(--accent); border-radius: 4px; background: var(--bg-primary);
                                padding: 4px; left: 100%; top: 0; margin-left: 8px;">
                                <img style="width: 256px; height: 144px; display: block;">
                                <div style="text-align: center; font-size: 0.75rem; margin-top: 4px;">Loading...</div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this.attachEventListeners();
    }

    attachEventListeners() {
        // Search filter
        const searchInput = this.querySelector('#shader-search');
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            this.querySelectorAll('.shader-item').forEach(item => {
                const name = item.dataset.name.toLowerCase();
                const path = item.dataset.path.toLowerCase();
                item.style.display = (name.includes(query) || path.includes(query)) ? 'block' : 'none';
            });
        });

        // Shader selection
        this.querySelectorAll('.shader-item').forEach(item => {
            item.addEventListener('click', () => {
                const path = item.dataset.path;
                this.dispatchEvent(new CustomEvent('shader-select', { detail: { path } }));
            });

            // On-hover thumbnail generation
            item.addEventListener('mouseenter', async (e) => {
                const thumbnail = item.querySelector('.shader-thumbnail');
                const img = thumbnail.querySelector('img');
                const status = thumbnail.querySelector('div');
                const path = item.dataset.path;

                thumbnail.style.display = 'block';

                // Check cache
                if (this.thumbnailCache.has(path)) {
                    img.src = this.thumbnailCache.get(path);
                    status.textContent = '';
                } else {
                    // Generate thumbnail
                    try {
                        status.textContent = 'Generating...';
                        const response = await fetch(`/api/shaders/thumbnail?path=${encodeURIComponent(path)}`);
                        const blob = await response.blob();
                        const url = URL.createObjectURL(blob);

                        this.thumbnailCache.set(path, url);
                        img.src = url;
                        status.textContent = '';
                    } catch (err) {
                        status.textContent = 'Failed to load';
                        console.error('Thumbnail error:', err);
                    }
                }
            });

            item.addEventListener('mouseleave', () => {
                const thumbnail = item.querySelector('.shader-thumbnail');
                thumbnail.style.display = 'none';
            });
        });
    }
}

customElements.define('shader-browser', ShaderBrowser);
```

---

#### Task 1.2.8: Add Thumbnail Generation Endpoint
**File**: `cedartoy/server/api/shaders.py`

Add to existing file:
```python
from fastapi.responses import FileResponse, Response
from PIL import Image
import io
from pathlib import Path

THUMBNAIL_CACHE_DIR = Path("thumbnails")
THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True)

@router.get("/thumbnail")
async def get_thumbnail(path: str):
    """Generate or retrieve cached shader thumbnail"""
    # Check cache
    cache_path = THUMBNAIL_CACHE_DIR / f"{path.replace('/', '_').replace('\\', '_')}.png"

    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png")

    # Generate thumbnail using renderer
    shader_path = SHADERS_DIR / path

    if not shader_path.exists():
        raise HTTPException(status_code=404, detail="Shader not found")

    try:
        from cedartoy.render import Renderer
        from cedartoy.types import RenderJob
        import tempfile
        import numpy as np

        # Create minimal render job for thumbnail
        output_dir = tempfile.mkdtemp()
        job = RenderJob(
            shader=str(shader_path),
            output_dir=output_dir,
            output_pattern="thumb.png",
            width=256,
            height=144,
            fps=1,
            duration_sec=0.0,  # Single frame
            frame_start=0,
            frame_end=0,
            # ... other defaults
        )

        # Render single frame
        renderer = Renderer(job)
        renderer.render_frame(0, time=0.0)

        # Read generated image
        thumb_path = Path(output_dir) / "thumb.png"
        if thumb_path.exists():
            # Copy to cache
            import shutil
            shutil.copy(thumb_path, cache_path)

            return FileResponse(cache_path, media_type="image/png")
        else:
            raise HTTPException(status_code=500, detail="Thumbnail generation failed")

    except Exception as e:
        # Return placeholder on error
        img = Image.new('RGB', (256, 144), color=(26, 26, 46))
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return Response(content=buffer.getvalue(), media_type="image/png")
```

---

#### Task 1.2.9: Create Placeholder Components
**File**: `web/js/components/preview-panel.js`
```javascript
class PreviewPanel extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
            <div class="preview-container">
                <h3>Preview</h3>
                <canvas id="preview-canvas" width="640" height="360" style="width: 100%; background: #000;"></canvas>
                <div class="preview-controls" style="margin-top: 8px;">
                    <button class="btn btn-primary">▶ Play</button>
                    <input type="range" min="0" max="100" value="0" style="flex: 1; margin: 0 8px;">
                    <span>00:00 / 00:00</span>
                </div>
            </div>
        `;
    }
}

customElements.define('preview-panel', PreviewPanel);
```

**File**: `web/js/components/audio-viz.js`
```javascript
class AudioViz extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
            <div class="audio-viz-container" style="margin-top: 16px;">
                <h4>Audio</h4>
                <input type="file" accept="audio/*" class="form-input">
                <canvas width="600" height="80" style="width: 100%; margin-top: 8px; background: var(--bg-tertiary);"></canvas>
            </div>
        `;
    }
}

customElements.define('audio-viz', AudioViz);
```

**File**: `web/js/components/render-panel.js`
```javascript
class RenderPanel extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
            <div class="render-panel-container">
                <button class="btn btn-primary" id="start-render">Start Render</button>
                <div class="progress" style="margin-top: 8px; display: none;">
                    <div class="progress-bar" style="width: 0%;">0%</div>
                </div>
                <div style="margin-top: 8px; color: var(--text-secondary);">Idle</div>
            </div>
        `;
    }
}

customElements.define('render-panel', RenderPanel);
```

---

#### Task 1.2.10: Create Main App
**File**: `web/js/app.js`

```javascript
import { api } from './api.js';
import './components/shader-browser.js';
import './components/config-editor.js';
import './components/preview-panel.js';
import './components/audio-viz.js';
import './components/render-panel.js';
import './components/directory-browser.js';

// Global app state
window.cedartoy = {
    currentShader: null,
    config: {},
    audioFile: null
};

console.log('CedarToy UI initialized');

// Listen for shader selection
document.addEventListener('shader-select', async (e) => {
    const { path } = e.detail;
    console.log('Selected shader:', path);
    window.cedartoy.currentShader = path;

    // Update config with selected shader
    const configEditor = document.querySelector('config-editor');
    if (configEditor) {
        configEditor.config.shader = path;
        configEditor.saveToLocalStorage();
    }

    // Load shader source
    const shaderData = await api.getShader(path);
    console.log('Loaded shader:', shaderData);
});

// Listen for config changes
document.addEventListener('config-change', (e) => {
    window.cedartoy.config = e.detail;
    console.log('Config updated:', window.cedartoy.config);
});
```

---

### 1.3 Testing Phase 1

#### Task 1.3.1: Manual Testing Checklist
- [ ] Start server: `python -m cedartoy.cli ui`
- [ ] Verify browser opens to `http://localhost:8080`
- [ ] Check shader list loads from `/api/shaders`
- [ ] Check config editor form generates from schema
- [ ] Test config import/export to YAML file
- [ ] Verify collapsible sections work
- [ ] Test form input changes update config state
- [ ] Check browser console for errors

---

## Phase 2: Render Integration

**Goal**: Execute renders from UI, display progress in real-time

### 2.1 Backend Render Management

#### Task 2.1.1: Implement Render API
**File**: `cedartoy/server/api/render.py`

```python
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
import subprocess
import asyncio
import signal
from pathlib import Path

router = APIRouter()

# Global render state
render_state = {
    "active": False,
    "process": None,
    "config": None,
    "progress": {"frame": 0, "total": 0, "eta_sec": 0}
}

class RenderConfig(BaseModel):
    config: Dict[str, Any]

@router.post("/start")
async def start_render(data: RenderConfig, background_tasks: BackgroundTasks):
    """Start a render job"""
    global render_state

    if render_state["active"]:
        raise HTTPException(status_code=409, detail="Render already in progress")

    # Save config to temp file
    import tempfile
    import yaml

    temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(data.config, temp_config)
    temp_config.close()

    # Start render subprocess
    cmd = [
        "python", "-m", "cedartoy.cli", "render",
        "--config", temp_config.name
    ]

    render_state["active"] = True
    render_state["config"] = data.config
    render_state["progress"] = {"frame": 0, "total": 0, "eta_sec": 0}

    # Note: Actual subprocess launch happens in WebSocket handler
    # to stream output in real-time

    return {"status": "started", "config_file": temp_config.name}

@router.post("/cancel")
async def cancel_render():
    """Cancel the current render"""
    global render_state

    if not render_state["active"]:
        raise HTTPException(status_code=404, detail="No active render")

    if render_state["process"]:
        render_state["process"].send_signal(signal.SIGTERM)

    render_state["active"] = False
    return {"status": "cancelled"}

@router.get("/status")
async def get_render_status():
    """Get current render status"""
    return {
        "active": render_state["active"],
        "progress": render_state["progress"]
    }
```

---

#### Task 2.1.2: Modify render.py for Progress Output
**File**: `cedartoy/render.py`

**Changes**: Add structured progress logging

```python
# Add near top of file
import json
import sys

def log_progress(frame, total, elapsed_sec):
    """Output structured progress for UI"""
    progress = {
        "frame": frame,
        "total": total,
        "elapsed_sec": elapsed_sec
    }
    print(f"[PROGRESS] {json.dumps(progress)}", file=sys.stderr)
    sys.stderr.flush()

def log_info(message):
    """Output info log"""
    print(f"[LOG] INFO: {message}", file=sys.stderr)
    sys.stderr.flush()

# In Renderer.render() method, add progress logging:
# After each frame is rendered:
log_progress(frame_idx + 1, total_frames, time.time() - start_time)

# At completion:
print(f"[COMPLETE] {json.dumps({'output_dir': str(output_dir), 'frames': total_frames})}", file=sys.stderr)
```

---

#### Task 2.1.3: Implement WebSocket Handler
**File**: `cedartoy/server/websocket.py`

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import subprocess
import json
from pathlib import Path

router = APIRouter()

active_connections = []

@router.websocket("/render")
async def websocket_render(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "start_render":
                await handle_render(websocket, data)
            elif msg_type == "subscribe":
                # Client subscribes to channels
                pass

    except WebSocketDisconnect:
        active_connections.remove(websocket)

async def handle_render(websocket: WebSocket, data):
    """Execute render and stream progress"""
    config_file = data.get("config_file")

    cmd = ["python", "-m", "cedartoy.cli", "render", "--config", config_file]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Stream stderr (progress logs)
    while True:
        line = process.stderr.readline()
        if not line and process.poll() is not None:
            break

        if line.startswith("[PROGRESS]"):
            progress_data = json.loads(line[10:])
            await websocket.send_json({
                "type": "render_progress",
                **progress_data
            })
        elif line.startswith("[LOG]"):
            await websocket.send_json({
                "type": "render_log",
                "message": line[5:].strip()
            })
        elif line.startswith("[COMPLETE]"):
            complete_data = json.loads(line[10:])
            await websocket.send_json({
                "type": "render_complete",
                **complete_data
            })
        elif line.startswith("[ERROR]"):
            await websocket.send_json({
                "type": "render_error",
                "message": line[7:].strip()
            })

    await websocket.send_json({"type": "render_complete", "code": process.returncode})
```

---

### 2.2 Frontend Render UI

#### Task 2.2.1: Create WebSocket Client
**File**: `web/js/websocket.js`

```javascript
class WebSocketClient {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.handlers = {};
    }

    connect() {
        return new Promise((resolve, reject) => {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                resolve();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                reject(error);
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const handler = this.handlers[data.type];
                if (handler) {
                    handler(data);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
            };
        });
    }

    on(type, handler) {
        this.handlers[type] = handler;
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    close() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

export const wsClient = new WebSocketClient('ws://localhost:8080/ws/render');
```

---

#### Task 2.2.2: Update Render Panel Component
**File**: `web/js/components/render-panel.js`

```javascript
import { api } from '../api.js';
import { wsClient } from '../websocket.js';

class RenderPanel extends HTMLElement {
    constructor() {
        super();
        this.state = 'idle'; // idle, rendering, complete, error
        this.progress = { frame: 0, total: 0, eta_sec: 0 };
        this.logs = [];
    }

    async connectedCallback() {
        this.render();
        this.attachEventListeners();

        // Connect WebSocket
        await wsClient.connect();
        this.setupWebSocketHandlers();
    }

    render() {
        const progressPercent = this.progress.total > 0
            ? Math.round((this.progress.frame / this.progress.total) * 100)
            : 0;

        const etaMin = Math.floor(this.progress.eta_sec / 60);
        const etaSec = Math.floor(this.progress.eta_sec % 60);

        this.innerHTML = `
            <div class="render-panel-container">
                <div class="render-controls">
                    <button class="btn btn-primary" id="start-render"
                        ${this.state === 'rendering' ? 'disabled' : ''}>
                        Start Render
                    </button>
                    <button class="btn btn-secondary" id="cancel-render"
                        ${this.state !== 'rendering' ? 'disabled' : ''}>
                        Cancel
                    </button>
                </div>

                ${this.state === 'rendering' ? `
                    <div class="progress" style="margin-top: 8px;">
                        <div class="progress-bar" style="width: ${progressPercent}%;">
                            ${progressPercent}%
                        </div>
                    </div>
                    <div style="margin-top: 8px; color: var(--text-secondary);">
                        Frame ${this.progress.frame} / ${this.progress.total}
                        | ETA: ${etaMin}:${etaSec.toString().padStart(2, '0')}
                    </div>
                ` : ''}

                ${this.state === 'complete' ? `
                    <div style="margin-top: 8px; color: var(--success);">
                        Render complete!
                        <button class="btn btn-secondary" id="open-output">Open Output</button>
                    </div>
                ` : ''}

                <div class="render-logs" style="margin-top: 16px; max-height: 150px; overflow-y: auto;
                    background: var(--bg-tertiary); padding: 8px; border-radius: 4px; font-family: monospace; font-size: 0.8rem;">
                    ${this.logs.map(log => `<div>${log}</div>`).join('')}
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        const startBtn = this.querySelector('#start-render');
        const cancelBtn = this.querySelector('#cancel-render');

        if (startBtn) {
            startBtn.addEventListener('click', async () => {
                await this.startRender();
            });
        }

        if (cancelBtn) {
            cancelBtn.addEventListener('click', async () => {
                await this.cancelRender();
            });
        }
    }

    async startRender() {
        const configEditor = document.querySelector('config-editor');
        const config = configEditor.getConfig();

        this.state = 'rendering';
        this.logs = ['Starting render...'];
        this.render();

        try {
            const result = await api.startRender(config);
            wsClient.send({ type: 'start_render', config_file: result.config_file });
        } catch (err) {
            this.state = 'error';
            this.logs.push(`ERROR: ${err.message}`);
            this.render();
        }
    }

    async cancelRender() {
        await api.cancelRender();
        this.state = 'idle';
        this.logs.push('Render cancelled');
        this.render();
    }

    setupWebSocketHandlers() {
        wsClient.on('render_progress', (data) => {
            this.progress = data;
            this.render();
        });

        wsClient.on('render_log', (data) => {
            this.logs.push(data.message);
            if (this.logs.length > 100) this.logs.shift(); // Keep last 100
            this.render();
            // Auto-scroll logs
            const logsEl = this.querySelector('.render-logs');
            if (logsEl) logsEl.scrollTop = logsEl.scrollHeight;
        });

        wsClient.on('render_complete', (data) => {
            this.state = 'complete';
            this.logs.push(`Complete! Output: ${data.output_dir}`);
            this.render();
        });

        wsClient.on('render_error', (data) => {
            this.state = 'error';
            this.logs.push(`ERROR: ${data.message}`);
            this.render();
        });
    }
}

customElements.define('render-panel', RenderPanel);
```

---

### 2.3 Testing Phase 2

#### Task 2.3.1: Manual Testing Checklist
- [ ] Start a render from UI
- [ ] Verify WebSocket connection established
- [ ] Check progress updates in real-time
- [ ] Verify logs display in render panel
- [ ] Test cancel functionality
- [ ] Verify completion message and output path
- [ ] Test error handling (invalid config, missing shader)

---

## Phase 3: Preview System

**Goal**: WebGL shader preview with play/pause/seek

### 3.1 WebGL Renderer

#### Task 3.1.1: Create WebGL Renderer
**File**: `web/js/webgl/renderer.js`

```javascript
export class ShaderRenderer {
    constructor(canvas) {
        this.canvas = canvas;
        this.gl = canvas.getContext('webgl2');

        if (!this.gl) {
            throw new Error('WebGL2 not supported');
        }

        this.program = null;
        this.uniforms = {};
        this.startTime = Date.now();
        this.currentTime = 0;
        this.frameCount = 0;
        this.playing = false;
    }

    compileShader(source) {
        const gl = this.gl;

        // Vertex shader (fullscreen quad)
        const vertexShader = gl.createShader(gl.VERTEX_SHADER);
        gl.shaderSource(vertexShader, `#version 300 es
            in vec4 position;
            void main() {
                gl_Position = position;
            }
        `);
        gl.compileShader(vertexShader);

        // Fragment shader (user shader wrapped)
        const fragmentShaderSource = this.wrapShaderSource(source);
        const fragmentShader = gl.createShader(gl.FRAGMENT_SHADER);
        gl.shaderSource(fragmentShader, fragmentShaderSource);
        gl.compileShader(fragmentShader);

        // Check compilation
        if (!gl.getShaderParameter(fragmentShader, gl.COMPILE_STATUS)) {
            const error = gl.getShaderInfoLog(fragmentShader);
            console.error('Shader compilation error:', error);
            throw new Error(`Shader compilation failed: ${error}`);
        }

        // Link program
        this.program = gl.createProgram();
        gl.attachShader(this.program, vertexShader);
        gl.attachShader(this.program, fragmentShader);
        gl.linkProgram(this.program);

        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
            const error = gl.getProgramInfoLog(this.program);
            throw new Error(`Program linking failed: ${error}`);
        }

        // Get uniform locations
        this.uniforms = {
            iResolution: gl.getUniformLocation(this.program, 'iResolution'),
            iTime: gl.getUniformLocation(this.program, 'iTime'),
            iTimeDelta: gl.getUniformLocation(this.program, 'iTimeDelta'),
            iFrame: gl.getUniformLocation(this.program, 'iFrame'),
            iMouse: gl.getUniformLocation(this.program, 'iMouse'),
        };

        // Create fullscreen quad
        this.createQuad();
    }

    wrapShaderSource(userSource) {
        // Wrap user's mainImage() function
        return `#version 300 es
precision highp float;

uniform vec3 iResolution;
uniform float iTime;
uniform float iTimeDelta;
uniform int iFrame;
uniform vec4 iMouse;

out vec4 fragColor;

${userSource}

void main() {
    mainImage(fragColor, gl_FragCoord.xy);
}
`;
    }

    createQuad() {
        const gl = this.gl;

        const vertices = new Float32Array([
            -1, -1,
             1, -1,
            -1,  1,
             1,  1,
        ]);

        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

        const positionLoc = gl.getAttribLocation(this.program, 'position');
        gl.enableVertexAttribArray(positionLoc);
        gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);
    }

    render() {
        if (!this.program) return;

        const gl = this.gl;

        gl.viewport(0, 0, this.canvas.width, this.canvas.height);
        gl.clearColor(0, 0, 0, 1);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.useProgram(this.program);

        // Set uniforms
        gl.uniform3f(this.uniforms.iResolution, this.canvas.width, this.canvas.height, 1.0);
        gl.uniform1f(this.uniforms.iTime, this.currentTime);
        gl.uniform1f(this.uniforms.iTimeDelta, 0.016); // ~60fps
        gl.uniform1i(this.uniforms.iFrame, this.frameCount);
        gl.uniform4f(this.uniforms.iMouse, 0, 0, 0, 0); // TODO: mouse tracking

        // Draw
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

        this.frameCount++;
    }

    play() {
        this.playing = true;
        this.startTime = Date.now() - (this.currentTime * 1000);
        this.animate();
    }

    pause() {
        this.playing = false;
    }

    seek(time) {
        this.currentTime = time;
        this.startTime = Date.now() - (time * 1000);
        if (!this.playing) {
            this.render();
        }
    }

    animate() {
        if (!this.playing) return;

        this.currentTime = (Date.now() - this.startTime) / 1000;
        this.render();

        requestAnimationFrame(() => this.animate());
    }
}
```

---

#### Task 3.1.2: Update Preview Panel Component
**File**: `web/js/components/preview-panel.js`

```javascript
import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js';

class PreviewPanel extends HTMLElement {
    constructor() {
        super();
        this.renderer = null;
        this.duration = 10.0;
        this.playing = false;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();

        // Initialize WebGL
        const canvas = this.querySelector('#preview-canvas');
        this.renderer = new ShaderRenderer(canvas);

        // Listen for shader selection
        document.addEventListener('shader-select', async (e) => {
            await this.loadShader(e.detail.path);
        });
    }

    render() {
        this.innerHTML = `
            <div class="preview-container">
                <h3>Preview</h3>
                <div style="position: relative;">
                    <canvas id="preview-canvas" width="640" height="360"
                        style="width: 100%; background: #000; border-radius: 4px;"></canvas>
                    <div id="preview-error" style="display: none; position: absolute; top: 50%; left: 50%;
                        transform: translate(-50%, -50%); color: var(--error); font-weight: bold;">
                    </div>
                </div>
                <div class="preview-controls" style="margin-top: 8px; display: flex; align-items: center; gap: 8px;">
                    <button class="btn btn-primary" id="play-btn">▶</button>
                    <input type="range" id="time-slider" min="0" max="1000" value="0"
                        style="flex: 1;">
                    <span id="time-display">00:00 / ${this.formatTime(this.duration)}</span>
                </div>
                <div style="margin-top: 8px; font-size: 0.8rem; color: var(--text-secondary);">
                    Note: Preview is single-pass only. Full multipass rendering in final output.
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        const playBtn = this.querySelector('#play-btn');
        const timeSlider = this.querySelector('#time-slider');

        playBtn.addEventListener('click', () => {
            this.togglePlay();
        });

        timeSlider.addEventListener('input', (e) => {
            const time = (parseFloat(e.target.value) / 1000) * this.duration;
            this.renderer.seek(time);
            this.updateTimeDisplay();
        });

        // Update slider during playback
        setInterval(() => {
            if (this.playing && this.renderer) {
                const progress = (this.renderer.currentTime / this.duration) * 1000;
                timeSlider.value = Math.min(progress, 1000);
                this.updateTimeDisplay();
            }
        }, 100);
    }

    async loadShader(path) {
        try {
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.style.display = 'none';

            const shaderData = await api.getShader(path);
            this.renderer.compileShader(shaderData.source);
            this.renderer.render(); // Render first frame

            console.log('Shader loaded successfully');
        } catch (err) {
            console.error('Failed to load shader:', err);
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.textContent = `Shader Error: ${err.message}`;
            errorDiv.style.display = 'block';
        }
    }

    togglePlay() {
        this.playing = !this.playing;
        const playBtn = this.querySelector('#play-btn');

        if (this.playing) {
            this.renderer.play();
            playBtn.textContent = '⏸';
        } else {
            this.renderer.pause();
            playBtn.textContent = '▶';
        }
    }

    updateTimeDisplay() {
        const timeDisplay = this.querySelector('#time-display');
        const current = this.renderer.currentTime;
        timeDisplay.textContent = `${this.formatTime(current)} / ${this.formatTime(this.duration)}`;
    }

    formatTime(seconds) {
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60);
        return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
    }
}

customElements.define('preview-panel', PreviewPanel);
```

---

### 3.2 Testing Phase 3

#### Task 3.2.1: Manual Testing Checklist
- [ ] Select a shader from browser
- [ ] Verify WebGL canvas shows shader output
- [ ] Test play/pause controls
- [ ] Test time scrubbing
- [ ] Verify time display updates
- [ ] Test shader compilation errors display correctly
- [ ] Try different shaders (aurora, luminescence)

---

## Phase 4: Audio Integration

**Goal**: Audio upload, waveform viz, FFT texture for preview

### 4.1 Backend Audio Processing

#### Task 4.1.1: Implement Audio API
**File**: `cedartoy/server/api/audio.py`

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import tempfile
import numpy as np

from cedartoy.audio import AudioProcessor

router = APIRouter()

# Global audio state
audio_state = {
    "processor": None,
    "file_path": None,
    "metadata": None
}

@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    """Upload audio file for processing"""
    global audio_state

    # Save to temp file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
    content = await file.read()
    temp_file.write(content)
    temp_file.close()

    # Process audio
    try:
        processor = AudioProcessor(temp_file.name)
        audio_state["processor"] = processor
        audio_state["file_path"] = temp_file.name
        audio_state["metadata"] = {
            "duration": processor.meta.duration,
            "sample_rate": processor.meta.sample_rate,
            "channels": processor.meta.channels,
            "frames": processor.meta.frame_count,
        }

        return {
            "status": "success",
            "metadata": audio_state["metadata"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/info")
async def get_audio_info():
    """Get loaded audio metadata"""
    if not audio_state["processor"]:
        raise HTTPException(status_code=404, detail="No audio loaded")

    return {"metadata": audio_state["metadata"]}

@router.get("/waveform")
async def get_waveform(samples: int = 1000):
    """Get downsampled waveform for visualization"""
    if not audio_state["processor"]:
        raise HTTPException(status_code=404, detail="No audio loaded")

    # Downsample audio data for waveform display
    audio_data = audio_state["processor"].data
    total_samples = len(audio_data)

    if total_samples <= samples:
        waveform = audio_data.tolist()
    else:
        # Simple decimation
        step = total_samples // samples
        waveform = audio_data[::step][:samples].tolist()

    return {"waveform": waveform}

@router.get("/fft/{frame}")
async def get_fft(frame: int):
    """Get FFT data for specific frame"""
    if not audio_state["processor"]:
        raise HTTPException(status_code=404, detail="No audio loaded")

    # Get Shadertoy texture data
    texture_data = audio_state["processor"].get_shadertoy_texture(frame)

    # Extract FFT (row 0) and waveform (row 1)
    fft = texture_data[0, :].tolist()
    waveform = texture_data[1, :].tolist()

    return {
        "fft": fft,
        "waveform": waveform,
        "frame": frame
    }
```

---

### 4.2 Frontend Audio Visualization

#### Task 4.2.1: Update Audio Viz Component
**File**: `web/js/components/audio-viz.js`

```javascript
import { api } from '../api.js';

class AudioViz extends HTMLElement {
    constructor() {
        super();
        this.audioContext = null;
        this.audioElement = null;
        this.analyser = null;
        this.waveform = [];
        this.currentTime = 0;
        this.duration = 0;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
    }

    render() {
        this.innerHTML = `
            <div class="audio-viz-container" style="margin-top: 16px;">
                <h4>Audio</h4>
                <input type="file" accept="audio/*" class="form-input" id="audio-upload">
                <div id="audio-filename" style="margin-top: 4px; color: var(--text-secondary); font-size: 0.85rem;"></div>

                <canvas id="waveform-canvas" width="600" height="80"
                    style="width: 100%; margin-top: 8px; background: var(--bg-tertiary); border-radius: 4px; cursor: pointer;"></canvas>

                <canvas id="fft-canvas" width="512" height="100"
                    style="width: 100%; margin-top: 8px; background: var(--bg-tertiary); border-radius: 4px;"></canvas>
            </div>
        `;
    }

    attachEventListeners() {
        const uploadInput = this.querySelector('#audio-upload');
        const waveformCanvas = this.querySelector('#waveform-canvas');

        uploadInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (file) {
                await this.loadAudio(file);
            }
        });

        // Click to seek
        waveformCanvas.addEventListener('click', (e) => {
            const rect = waveformCanvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const progress = x / rect.width;
            const time = progress * this.duration;

            if (this.audioElement) {
                this.audioElement.currentTime = time;
            }

            this.dispatchEvent(new CustomEvent('audio-seek', { detail: { time } }));
        });

        // Update FFT in animation loop
        this.startFFTAnimation();
    }

    async loadAudio(file) {
        // Upload to server
        const result = await api.uploadAudio(file);
        this.duration = result.metadata.duration;

        // Display filename
        this.querySelector('#audio-filename').textContent = `🎵 ${file.name} (${this.formatDuration(this.duration)})`;

        // Load waveform
        const waveformData = await api.getWaveform();
        this.waveform = waveformData.waveform;
        this.drawWaveform();

        // Setup Web Audio API for playback and FFT
        this.setupWebAudio(file);
    }

    async setupWebAudio(file) {
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        this.audioElement = new Audio(URL.createObjectURL(file));

        const source = this.audioContext.createMediaElementSource(this.audioElement);
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 1024;

        source.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);

        // Sync with preview
        this.audioElement.addEventListener('timeupdate', () => {
            this.currentTime = this.audioElement.currentTime;
            this.drawWaveform(); // Update playhead
        });

        // Listen for preview play/pause
        document.addEventListener('preview-play', () => {
            this.audioElement.play();
        });

        document.addEventListener('preview-pause', () => {
            this.audioElement.pause();
        });

        document.addEventListener('preview-seek', (e) => {
            this.audioElement.currentTime = e.detail.time;
        });
    }

    drawWaveform() {
        const canvas = this.querySelector('#waveform-canvas');
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;

        ctx.clearRect(0, 0, width, height);

        // Draw waveform
        ctx.strokeStyle = '#4ecca3';
        ctx.lineWidth = 1;
        ctx.beginPath();

        for (let i = 0; i < this.waveform.length; i++) {
            const x = (i / this.waveform.length) * width;
            const y = ((this.waveform[i] + 1) / 2) * height; // Normalize -1 to 1 → 0 to height

            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }

        ctx.stroke();

        // Draw playhead
        if (this.duration > 0) {
            const playheadX = (this.currentTime / this.duration) * width;
            ctx.strokeStyle = '#e94560';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(playheadX, 0);
            ctx.lineTo(playheadX, height);
            ctx.stroke();
        }
    }

    startFFTAnimation() {
        const canvas = this.querySelector('#fft-canvas');
        const ctx = canvas.getContext('2d');

        const animate = () => {
            if (this.analyser) {
                const bufferLength = this.analyser.frequencyBinCount;
                const dataArray = new Uint8Array(bufferLength);
                this.analyser.getByteFrequencyData(dataArray);

                // Draw FFT bars
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = '#533483';

                const barWidth = canvas.width / bufferLength;
                for (let i = 0; i < bufferLength; i++) {
                    const barHeight = (dataArray[i] / 255) * canvas.height;
                    const x = i * barWidth;
                    const y = canvas.height - barHeight;

                    ctx.fillRect(x, y, barWidth - 1, barHeight);
                }
            }

            requestAnimationFrame(animate);
        };

        animate();
    }

    formatDuration(seconds) {
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60);
        return `${min}:${sec.toString().padStart(2, '0')}`;
    }
}

customElements.define('audio-viz', AudioViz);
```

---

#### Task 4.2.2: Integrate Audio with Preview
**File**: `web/js/webgl/audio-texture.js`

```javascript
export class AudioTexture {
    constructor(gl) {
        this.gl = gl;
        this.texture = null;
        this.createTexture();
    }

    createTexture() {
        const gl = this.gl;

        this.texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.texture);

        // Initialize with empty 512x2 texture
        const emptyData = new Uint8Array(512 * 2 * 4);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 512, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, emptyData);

        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }

    update(fftData, waveformData) {
        const gl = this.gl;

        // Create 512x2 texture: row 0 = FFT, row 1 = waveform
        const data = new Uint8Array(512 * 2 * 4);

        // FFT (row 0)
        for (let i = 0; i < 512; i++) {
            const value = Math.floor((fftData[i] || 0) * 255);
            const idx = i * 4;
            data[idx] = value;
            data[idx + 1] = value;
            data[idx + 2] = value;
            data[idx + 3] = 255;
        }

        // Waveform (row 1)
        for (let i = 0; i < 512; i++) {
            const value = Math.floor(((waveformData[i] || 0) + 1) / 2 * 255);
            const idx = (512 + i) * 4;
            data[idx] = value;
            data[idx + 1] = value;
            data[idx + 2] = value;
            data[idx + 3] = 255;
        }

        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 512, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    }

    bind(unit = 0) {
        const gl = this.gl;
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
    }
}
```

Update `web/js/webgl/renderer.js` to support audio texture:
- Add `iChannel0` uniform
- Create AudioTexture instance
- Bind audio texture before rendering
- Update from FFT data each frame

---

### 4.3 Testing Phase 4

#### Task 4.3.1: Manual Testing Checklist
- [ ] Upload audio file
- [ ] Verify waveform displays
- [ ] Verify FFT bars animate in real-time
- [ ] Test playhead sync with preview
- [ ] Click waveform to seek
- [ ] Verify audio plays when preview plays
- [ ] Test audio-reactive shader (e.g., `audio_test.glsl`)

---

## Phase 5: Polish

**Goal**: Shader browser, thumbnails, presets, documentation

### 5.1 Shader Editor Integration

#### Task 5.1.1: Add CodeMirror Shader Editor
**File**: `web/js/components/shader-editor.js`

Add CodeMirror to `web/index.html`:
```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/codemirror.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/mode/clike/clike.min.js"></script>
```

Create shader editor component:
```javascript
class ShaderEditor extends HTMLElement {
    constructor() {
        super();
        this.editor = null;
        this.currentPath = null;
    }

    connectedCallback() {
        this.innerHTML = `
            <div class="shader-editor-container" style="display: none;">
                <div class="editor-header" style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <h4 id="shader-title">Shader Editor</h4>
                    <div>
                        <button class="btn btn-primary" id="save-shader">Save</button>
                        <button class="btn btn-secondary" id="close-editor">Close</button>
                    </div>
                </div>
                <textarea id="shader-code"></textarea>
            </div>
        `;

        // Initialize CodeMirror
        const textarea = this.querySelector('#shader-code');
        this.editor = CodeMirror.fromTextArea(textarea, {
            mode: 'text/x-c',
            theme: 'default',
            lineNumbers: true,
            indentUnit: 4,
            tabSize: 4,
            indentWithTabs: false
        });

        this.attachEventListeners();

        // Listen for shader double-click to edit
        document.addEventListener('shader-edit', async (e) => {
            await this.loadShader(e.detail.path);
        });
    }

    async loadShader(path) {
        this.currentPath = path;
        const data = await api.getShader(path);

        this.editor.setValue(data.source);
        this.querySelector('#shader-title').textContent = `Editing: ${path}`;
        this.querySelector('.shader-editor-container').style.display = 'block';
    }

    attachEventListeners() {
        this.querySelector('#save-shader').addEventListener('click', async () => {
            if (!this.currentPath) return;

            const source = this.editor.getValue();

            try {
                await fetch(`/api/shaders/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: this.currentPath, source })
                });

                alert('Shader saved!');

                // Reload preview
                document.dispatchEvent(new CustomEvent('shader-select', {
                    detail: { path: this.currentPath }
                }));
            } catch (err) {
                alert('Failed to save: ' + err.message);
            }
        });

        this.querySelector('#close-editor').addEventListener('click', () => {
            this.querySelector('.shader-editor-container').style.display = 'none';
        });
    }
}

customElements.define('shader-editor', ShaderEditor);
```

Update shader browser to support double-click to edit:
```javascript
// In shader-browser.js, add double-click handler
item.addEventListener('dblclick', () => {
    document.dispatchEvent(new CustomEvent('shader-edit', { detail: { path } }));
});
```

Add save endpoint to `cedartoy/server/api/shaders.py`:
```python
@router.post("/save")
async def save_shader(data: dict):
    """Save shader source code"""
    path = data.get("path")
    source = data.get("source")

    if not path or not source:
        raise HTTPException(status_code=400, detail="Missing path or source")

    full_path = SHADERS_DIR / path

    # Security check
    try:
        full_path.resolve().relative_to(SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    with open(full_path, 'w') as f:
        f.write(source)

    return {"status": "success"}
```

---

### 5.2 Preset Management

#### Task 5.2.1: Preset UI
**File**: `web/js/components/config-editor.js`

- Add preset dropdown
- Load preset on selection
- Save current config as new preset
- Delete preset

---

### 5.3 Error Handling

#### Task 5.3.1: Global Error Handler
- Add toast notifications for errors
- Validate config before render
- Display helpful error messages

---

### 5.4 Documentation

#### Task 5.4.1: Update User Guide
**File**: `docs/USER_GUIDE.md`

- Add section on Web UI usage
- Document keyboard shortcuts
- Add screenshots

#### Task 5.4.2: Create UI Help Page
**File**: `web/help.html`

- Embed docs in UI
- Quick tips and troubleshooting

---

## Deployment Checklist

- [ ] Add `ui` to main CLI help text
- [ ] Test on fresh Python environment
- [ ] Verify all dependencies in `requirements.txt`
- [ ] Test with multiple shaders
- [ ] Test with various audio formats
- [ ] Verify multipass renders work (even if preview doesn't show)
- [ ] Add version number to UI
- [ ] Create release notes

---

## Additional Features (Integrated into phases)

**Phase 1 additions:**
- Server-side directory browser API (`GET /api/files/browse`)
- localStorage auto-save for config state

**Phase 3 additions:**
- CodeMirror integration for shader editing
- On-hover thumbnail generation endpoint

**Future Enhancements (Post-MVP):**
1. **Multipass Preview**: Simplified multipass in WebGL (decided: single-pass only for now)
2. **Batch Rendering**: Queue multiple render jobs
3. **Parameter Widgets**: Sliders for custom uniforms in shaders
4. **Export Presets**: Share config presets as files
5. **Performance Profiling**: Show render time per frame
6. **Real-time Preview Quality**: Adjustable preview resolution

---

## Estimated Implementation Time

| Phase | Tasks | Estimated Time |
|-------|-------|---------------|
| Phase 1 | Backend setup + config editor | 8-12 hours |
| Phase 2 | Render integration + WebSocket | 6-8 hours |
| Phase 3 | WebGL preview system | 8-10 hours |
| Phase 4 | Audio integration | 6-8 hours |
| Phase 5 | Polish + documentation | 4-6 hours |
| **Total** | | **32-44 hours** |

---

## Notes

- Each phase builds on the previous
- Test thoroughly before moving to next phase
- Keep design simple and focused on core features
- Prioritize render-to-file workflow over preview perfection
- Audio reactivity is a key differentiator—make it shine!
