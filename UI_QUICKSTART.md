# CedarToy Web UI - Quick Start Guide

## Starting the UI

### Option 1: Double-click the batch file (Easiest!)
Simply double-click `start_ui.bat` in the cedartoy folder.

### Option 2: Command line
```bash
cd D:\cedartoy
python -m cedartoy.cli ui
```

### Option 3: Custom port
```bash
python -m cedartoy.cli ui --port 3000
```

## First Time Setup

If you haven't installed dependencies yet:
```bash
pip install -r requirements.txt
```

## Accessing the UI

Once started, the server will automatically open your browser to:
**http://localhost:8080**

If it doesn't open automatically, just paste that URL into your browser.

## UI Overview

The CedarToy UI is divided into four main sections:

### 1. Shader Browser (Left Panel)
- **Browse Shaders**: Lists all `.glsl` files in the `shaders/` folder
- **Search**: Filter shaders by name or path
- **Select Shader**: Click a shader to select it and update the config
- **Edit Shader**: Double-click a shader to open the built-in editor

### 2. Configuration Editor (Center Panel)
- **Shader Path**: Currently selected shader (auto-updates on selection)
- **Output Directory**: Where rendered frames will be saved
- **Resolution**: Width and height in pixels (e.g., 1920x1080)
- **Frame Rate**: FPS for the animation (e.g., 30, 60)
- **Duration**: Length of the animation in seconds
- **Auto-save**: Config is automatically saved to browser localStorage

### 3. Preview Panel (Right Panel)
- **Live Preview**: WebGL preview of your shader (single-pass only)
- **Play/Pause**: Control animation playback
- **Timeline Scrubber**: Seek to any point in the animation
- **Time Display**: Shows current time / total duration
- **Audio Upload**: Upload audio files for audio-reactive shaders
- **Waveform Visualization**: See the audio waveform and click to seek
- **FFT Visualization**: Real-time frequency spectrum display

### 4. Render Panel (Bottom Panel)
- **Start Render**: Begin rendering frames to disk
- **Real-time Progress**: Live progress bar with frame count and ETA
- **Render Logs**: See detailed output from the render engine
- **Cancel Render**: Stop the current render job
- **Open Output Folder**: Quick link to view rendered frames

## Features Guide

### Shader Selection and Preview

1. **Browse** shaders in the left panel
2. **Click** a shader to select it
3. The **preview** will update automatically
4. **Press Play** to see the shader animate

### Shader Editing

1. **Double-click** any shader in the browser
2. The **CodeMirror editor** opens with syntax highlighting
3. **Edit** the GLSL code
4. **Click Save** to save changes
5. The **preview updates** automatically with your changes

### Audio-Reactive Shaders

1. In the preview panel, click **"Choose File"** under Audio
2. Select an audio file (MP3, WAV, OGG, etc.)
3. The **waveform** displays at the top
4. The **FFT bars** show real-time frequency data
5. **Click the waveform** to seek to a specific time
6. **Play the preview** to see shader react to audio
7. Audio data is available in shaders via `iChannel0` uniform

### Rendering to File

1. **Select your shader** from the browser
2. **Configure settings**:
   - Set output directory (e.g., `D:\cedartoy\renders\my_project`)
   - Set resolution (higher = better quality, slower render)
   - Set FPS (30 for web, 60 for smooth)
   - Set duration in seconds
3. **Click "Start Render"** at the bottom
4. **Watch progress** in real-time with ETA
5. **Frames are saved** as PNG files in the output directory
6. **Click "Open Folder"** when complete to view frames

### Configuration Persistence

- Your config is **automatically saved** to browser localStorage
- When you reload the page, your settings are **restored**
- You can export/import configs as YAML files (coming in Phase 5+)

## Keyboard Shortcuts

- **Space**: Play/Pause preview
- **Left/Right Arrow**: Seek backward/forward 1 second
- **Escape**: Close shader editor

## Troubleshooting

### "Port already in use" error
Kill any existing Python processes:
```bash
taskkill /F /IM python.exe
```
Then start again.

### "Module not found" errors
Install dependencies:
```bash
pip install -r requirements.txt
```

### Browser shows "Cannot connect"
1. Check the terminal - server should say "Uvicorn running on http://0.0.0.0:8080"
2. Wait 2-3 seconds after seeing that message
3. Refresh your browser

### Preview shows black screen
- Check the browser console (F12) for shader compilation errors
- Make sure the shader has a `mainImage` function
- Verify the shader uses Shadertoy-compatible uniforms

### Audio not playing
- Make sure you clicked Play in the preview panel
- Check browser permissions for audio playback
- Try a different audio format (MP3 or WAV work best)

### Render is slow
- Lower the resolution for faster rendering
- Reduce FPS if you don't need smooth motion
- Complex shaders with many texture lookups are slower
- Multipass shaders take longer than single-pass

### Shader editor not saving
- Check file permissions on the shader file
- Make sure the shader path doesn't contain invalid characters
- Check the browser console (F12) for error messages

## Available Uniforms (Shadertoy Compatible)

Your shaders can use these uniforms:

```glsl
uniform vec3 iResolution;   // Viewport resolution (x, y, aspect)
uniform float iTime;         // Current time in seconds
uniform float iTimeDelta;    // Time since last frame
uniform int iFrame;          // Current frame number
uniform vec4 iMouse;         // Mouse coordinates (not yet implemented)
uniform sampler2D iChannel0; // Audio texture (512x2: FFT row 0, waveform row 1)
```

## Quick Test

1. Click on `test.glsl` in the shader browser
2. Set Duration to 1.0 seconds (renders faster!)
3. Click "Start Render" at the bottom
4. Watch the progress bar fill up!

Your rendered frames will be in: `D:\cedartoy\renders\`

## What's Next?

### Phase 3: ✅ WebGL Preview - COMPLETE
- Live shader preview in browser
- Play/pause/seek controls
- Shadertoy-compatible uniforms

### Phase 4: ✅ Audio Integration - COMPLETE
- Audio file upload
- Waveform visualization
- Real-time FFT display
- Audio-reactive preview with iChannel0

### Phase 5: 🚧 Polish (Partial)
- ✅ CodeMirror shader editor
- ✅ Shader save functionality
- ⏳ Preset management (API ready, UI pending)
- ⏳ Thumbnail generation on hover
- ⏳ Advanced error handling

## Tips and Tricks

1. **Test shaders quickly**: Set duration to 0.1 seconds for a single frame test
2. **Audio sync**: The preview and audio playback are synchronized - seek one, the other follows
3. **Live editing**: Double-click, edit, save, and the preview updates instantly
4. **Browser localStorage**: Your config persists across sessions automatically
5. **Multiple renders**: Stop a render to start a new one with different settings

## Stopping the Server

Press `Ctrl+C` in the terminal window where the server is running.

## Getting Help

- Check the [main documentation](docs/UI_DESIGN.md) for architecture details
- Report issues on GitHub: [cedartoy/issues](https://github.com/yourusername/cedartoy/issues)
- Read the [build plan](BUILD_PLAN_UI.md) for development details

---

**Version**: 1.0.0
**Last Updated**: December 2024
**Phases Completed**: 1, 2, 3, 4 (Partial 5)
