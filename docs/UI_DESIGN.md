# CedarToy Web UI Design Document

## Overview

A web-based UI for CedarToy that provides shader browsing, configuration editing, audio-reactive preview, and render management—all accessible via browser on localhost.

## Goals

1. **Accessible**: No complex setup—run one command, open browser
2. **Standard scope**: Config editor + render progress + shader browser + low-res preview
3. **Audio-reactive**: Real-time WebGL preview with audio visualization
4. **Render-focused**: UI assists render-to-file workflow, preview is secondary

## Non-Goals

- Full shader IDE/code editor (users edit GLSL in their preferred editor)
- Render queue (single render at a time)
- Cross-platform optimization (Windows-focused)
- Production-quality preview (low-res is acceptable)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (localhost:8080)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Shader    │  │   Config    │  │      Preview Panel      │  │
│  │   Browser   │  │   Editor    │  │  ┌───────────────────┐  │  │
│  │             │  │             │  │  │  WebGL Canvas     │  │  │
│  │  - List     │  │  - Form     │  │  │  (shader preview) │  │  │
│  │  - Search   │  │  - Presets  │  │  └───────────────────┘  │  │
│  │  - Thumbs   │  │  - Import   │  │  ┌───────────────────┐  │  │
│  │             │  │  - Export   │  │  │  Audio Waveform   │  │  │
│  └─────────────┘  └─────────────┘  │  └───────────────────┘  │  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Render Panel                           │   │
│  │  [Start Render]  ████████████░░░░ 67%   00:42 remaining   │   │
│  │  Output: D:\renders\frame_00127.png                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP + WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Python Backend (FastAPI)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  REST API    │  │  WebSocket   │  │  Render Process      │   │
│  │              │  │  Server      │  │                      │   │
│  │  /shaders    │  │              │  │  - Subprocess        │   │
│  │  /config     │  │  - Progress  │  │  - Progress parsing  │   │
│  │  /audio      │  │  - Logs      │  │  - Cancellation      │   │
│  │  /render     │  │  - Preview   │  │                      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Backend
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Web Framework | **FastAPI** | Async, WebSocket support, auto-docs, modern |
| WebSocket | `fastapi.WebSocket` | Real-time progress & preview data |
| Audio Processing | Existing `audio.py` | Reuse FFT/waveform logic |
| Render Execution | `subprocess` | Isolate render, capture progress |
| Config Management | Existing `config.py` | Reuse YAML/JSON handling |

### Frontend
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Framework | **Vanilla JS + Web Components** | No build step, simple deployment |
| Styling | **CSS Variables + Grid** | Modern, no dependencies |
| WebGL | Raw WebGL2 | Shadertoy-compatible shader preview |
| Audio | Web Audio API | FFT analysis for reactive preview |
| Charts | Canvas 2D | Waveform/spectrogram visualization |

### Alternative Frontend Option
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Framework | **Svelte** (compiled) | Reactive, small bundle, optional |

---

## File Structure

```
cedartoy/
├── cedartoy/
│   ├── server/                    # NEW: Web server package
│   │   ├── __init__.py
│   │   ├── app.py                 # FastAPI application
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── shaders.py         # Shader listing/loading
│   │   │   ├── config.py          # Config CRUD
│   │   │   ├── audio.py           # Audio upload/processing
│   │   │   └── render.py          # Render control
│   │   └── websocket.py           # WebSocket handlers
│   ├── cli.py                     # Add 'ui' subcommand
│   └── ...existing modules...
├── web/                           # Frontend assets
│   ├── index.html                 # Main entry
│   ├── css/
│   │   ├── main.css
│   │   └── components.css
│   ├── js/
│   │   ├── app.js                 # Main application
│   │   ├── api.js                 # REST client
│   │   ├── websocket.js           # WebSocket client
│   │   ├── components/
│   │   │   ├── shader-browser.js
│   │   │   ├── config-editor.js
│   │   │   ├── preview-panel.js
│   │   │   ├── audio-viz.js
│   │   │   └── render-panel.js
│   │   └── webgl/
│   │       ├── renderer.js        # WebGL shader renderer
│   │       └── audio-texture.js   # Audio data → texture
│   └── assets/
│       └── icons/
```

---

## API Design

### REST Endpoints

#### Shaders
```
GET  /api/shaders                    # List all shaders
GET  /api/shaders/{path}             # Get shader source
POST /api/shaders/validate           # Validate GLSL syntax
```

#### Config
```
GET  /api/config/schema              # Get options_schema as JSON
GET  /api/config/defaults            # Get default values
POST /api/config/load                # Load from YAML/JSON file
POST /api/config/save                # Save to file
GET  /api/config/presets             # List saved presets
POST /api/config/presets             # Save current as preset
```

#### Audio
```
POST /api/audio/upload               # Upload audio file
GET  /api/audio/info                 # Get loaded audio metadata
GET  /api/audio/waveform             # Get waveform data (downsampled)
GET  /api/audio/fft/{frame}          # Get FFT data for frame
```

#### Render
```
POST /api/render/start               # Start render with config
POST /api/render/cancel              # Cancel current render
GET  /api/render/status              # Get current render status
```

### WebSocket Messages

#### Client → Server
```json
{"type": "preview_start", "shader": "path/to/shader.glsl", "config": {...}}
{"type": "preview_stop"}
{"type": "preview_seek", "time": 5.2}
{"type": "subscribe", "channels": ["render_progress", "preview_audio"]}
```

#### Server → Client
```json
{"type": "render_progress", "frame": 127, "total": 300, "eta_sec": 42}
{"type": "render_log", "level": "info", "message": "Rendering tile 2/4..."}
{"type": "render_complete", "output_dir": "D:\\renders\\output"}
{"type": "render_error", "message": "Shader compilation failed", "details": "..."}
{"type": "audio_data", "fft": [...], "waveform": [...], "time": 5.2}
```

---

## Component Specifications

### 1. Shader Browser

**Features:**
- List shaders from `shaders/` directory
- Search/filter by name
- Thumbnail preview (cached, generated on first load)
- Click to load into config editor
- Show shader metadata (if present in comments)

**Implementation:**
- Scan `shaders/` recursively for `.glsl` files
- Parse header comments for `// Name:`, `// Author:`, `// Description:`
- Generate thumbnails via quick render (128x128, 1 frame) or placeholder

### 2. Config Editor

**Features:**
- Auto-generated form from `options_schema.py`
- Grouped by category (Output, Quality, Camera, Audio, etc.)
- Real-time validation
- Import/Export YAML
- Preset management (save/load named configs)
- Collapsible sections for advanced options

**Implementation:**
- Fetch schema from `/api/config/schema`
- Generate form controls based on `type`:
  - `int`, `float` → number input with min/max
  - `str` → text input
  - `bool` → toggle switch
  - `choice` → dropdown select
  - `path` → text input + file picker button
- Two-way binding to config state
- Debounced validation on change

**Form Layout:**
```
┌─ Output ──────────────────────────────────┐
│ Output Directory   [D:\renders        ][📁]│
│ Output Pattern     [frame_{frame:05d}    ] │
│ Format             [PNG ▼] Bit Depth [8 ▼] │
└───────────────────────────────────────────┘
┌─ Resolution & Timing ─────────────────────┐
│ Width  [1920]  Height [1080]  FPS [60  ]  │
│ Duration (sec) [10.0]                      │
│ Frame Range    [0   ] to [    ] (optional) │
└───────────────────────────────────────────┘
┌─ Quality ─────────────────────────────────┐
│ Spatial Supersampling  [1.0 ▼]            │
│ Temporal Samples       [1   ]             │
│ Shutter Angle          [0.5 ]             │
│ Tiles X [1]  Y [1]                        │
└───────────────────────────────────────────┘
▶ Camera (collapsed)
▶ Audio (collapsed)
▶ Multipass (collapsed)
```

### 3. Preview Panel

**Features:**
- WebGL2 shader preview (Shadertoy-compatible)
- Low resolution (480p default, configurable)
- Play/pause/seek controls
- Sync with audio playback
- Time scrubbing
- FPS counter

**Implementation:**
- WebGL2 context on `<canvas>`
- Port shader header uniforms to WebGL
- `requestAnimationFrame` loop
- Audio sync via Web Audio API `currentTime`

**Shadertoy Uniform Mapping:**
```glsl
// Supported in preview
uniform vec3 iResolution;      // Viewport resolution
uniform float iTime;           // Playback time
uniform float iTimeDelta;      // Frame delta
uniform int iFrame;            // Frame counter
uniform vec4 iMouse;           // Mouse position (click drag)
uniform sampler2D iChannel0;   // Audio texture (FFT + waveform)

// NOT supported in preview (render-only)
// - Tiling uniforms
// - Stereo/VR uniforms
// - Multipass buffers (simplified single-pass only)
```

**Preview Limitations (documented in UI):**
- Single-pass only (multipass renders correctly in final output)
- No stereo/VR modes
- No tiling
- Lower precision than ModernGL render

### 4. Audio Visualization

**Features:**
- Waveform overview (full audio length)
- Spectrogram view (optional toggle)
- Playhead indicator synced with preview
- Click to seek
- Current FFT bars (real-time)

**Implementation:**
- Upload audio via `/api/audio/upload`
- Fetch downsampled waveform for overview
- Web Audio API `AnalyserNode` for real-time FFT
- Canvas 2D rendering for waveform/spectrogram
- Sync playhead with WebGL preview time

**Layout:**
```
┌─ Audio ───────────────────────────────────────────┐
│ 🎵 music.wav                        [Choose File] │
│ ┌───────────────────────────────────────────────┐ │
│ │▁▂▃▅▆▇█▇▆▅▃▂▁▁▂▄▆█▇▅▃▂▁▁▂▃▅▇█▆▄▂▁│ │ Waveform  │
│ │              ▲ playhead                       │ │
│ └───────────────────────────────────────────────┘ │
│ ┌─────────┐                                       │
│ │ █ █   █ │ Real-time FFT bars                   │
│ │ █ █ █ █ │                                       │
│ │█████████│                                       │
│ └─────────┘                                       │
└───────────────────────────────────────────────────┘
```

### 5. Render Panel

**Features:**
- Start/Cancel render button
- Progress bar with percentage
- ETA display
- Current frame / total frames
- Log output (scrolling, filterable)
- Output directory link (open in Explorer)

**Implementation:**
- POST to `/api/render/start` with current config
- Subscribe to WebSocket `render_progress` channel
- Parse progress from render subprocess stdout
- Cancel via `/api/render/cancel` (sends SIGTERM)

**States:**
1. **Idle**: [Start Render] button enabled
2. **Rendering**: Progress bar, [Cancel] button, live logs
3. **Complete**: Success message, [Open Output] button
4. **Error**: Error message, logs expanded

**Render Progress Protocol:**
Modify `render.py` to output structured progress:
```
[PROGRESS] {"frame": 127, "total": 300, "elapsed_sec": 84.2}
[LOG] INFO: Rendering tile 2/4...
[COMPLETE] {"output_dir": "D:\\renders\\output", "frames": 300}
[ERROR] {"message": "...", "traceback": "..."}
```

---

## UI Layout

### Desktop Layout (≥1200px)
```
┌────────────────────────────────────────────────────────────────────────┐
│  🌲 CedarToy                                        [Docs] [GitHub]    │
├────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐ ┌─────────────────────┐ ┌───────────────────────────┐ │
│ │              │ │                     │ │                           │ │
│ │   Shader     │ │   Config Editor     │ │     Preview Canvas        │ │
│ │   Browser    │ │                     │ │                           │ │
│ │              │ │   [Form controls]   │ │     ┌───────────────┐     │ │
│ │  - shader1   │ │                     │ │     │               │     │ │
│ │  - shader2   │ │                     │ │     │   WebGL       │     │ │
│ │  - shader3   │ │                     │ │     │               │     │ │
│ │              │ │                     │ │     └───────────────┘     │ │
│ │              │ │                     │ │     [▶] advancement ──○── │ │
│ │              │ │                     │ │                           │ │
│ │              │ │                     │ │  ┌─ Audio ─────────────┐  │ │
│ │              │ │                     │ │  │ waveform viz        │  │ │
│ │              │ │                     │ │  │ FFT bars            │  │ │
│ │              │ │                     │ │  └─────────────────────┘  │ │
│ └──────────────┘ └─────────────────────┘ └───────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │ [Start Render]  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  Idle               │ │
│ │ Logs:                                                               │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

### Color Scheme
```css
:root {
  --bg-primary: #1a1a2e;        /* Dark blue-gray */
  --bg-secondary: #16213e;      /* Darker panel bg */
  --bg-tertiary: #0f3460;       /* Accent bg */
  --accent: #e94560;            /* Red accent */
  --accent-secondary: #533483;  /* Purple accent */
  --text-primary: #eaeaea;
  --text-secondary: #a0a0a0;
  --success: #4ecca3;
  --warning: #ffc107;
  --error: #e94560;
}
```

---

## Implementation Phases

### Phase 1: Foundation (Backend + Basic UI)
- [ ] FastAPI server setup with static file serving
- [ ] REST endpoints: `/api/shaders`, `/api/config/schema`, `/api/config/defaults`
- [ ] Basic HTML/CSS layout structure
- [ ] Config editor form generation from schema
- [ ] Import/export YAML config

### Phase 2: Render Integration
- [ ] Render subprocess management
- [ ] WebSocket server for progress
- [ ] Progress parsing from render output
- [ ] Render panel UI (start/cancel/progress)
- [ ] Log output display

### Phase 3: Preview System
- [ ] WebGL2 shader renderer
- [ ] Shadertoy uniform compatibility
- [ ] Play/pause/seek controls
- [ ] Basic preview (no audio)

### Phase 4: Audio Integration
- [ ] Audio upload endpoint
- [ ] Waveform extraction and display
- [ ] Web Audio API FFT analysis
- [ ] Audio texture for WebGL preview
- [ ] Synced audio playback

### Phase 5: Polish
- [ ] Shader browser with search
- [ ] Thumbnail generation
- [ ] Preset management
- [ ] Error handling improvements
- [ ] Documentation

---

## Design Decisions

1. **Multipass Preview**: Single-pass only with disclaimer. Multipass renders correctly in final output.

2. **File Picker**: Server-side directory browser for selecting output paths (more reliable than native file picker)

3. **Shader Editing**: Include CodeMirror for quick shader tweaks in-browser

4. **Session Persistence**: Auto-save config to localStorage for seamless workflow

5. **Thumbnail Cache**: Generate thumbnails on-demand when hovering (lazy loading)

---

## Dependencies to Add

```
# requirements.txt additions
fastapi>=0.100.0
uvicorn>=0.23.0
python-multipart>=0.0.6   # File uploads
websockets>=11.0
```

---

## CLI Integration

New subcommand:
```bash
python -m cedartoy.cli ui [--port 8080] [--no-browser]
```

- Starts FastAPI server
- Opens default browser to `http://localhost:8080`
- `--no-browser` flag to skip auto-open

---

## Security Considerations

Since this runs on localhost for local use:
- No authentication required
- File access limited to project directory
- Render output paths validated (no path traversal)
- Audio uploads stored in temp directory, cleaned on exit
