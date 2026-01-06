from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
from typing import List, Dict
import re
from PIL import Image
import io
import tempfile
import shutil

router = APIRouter()

SHADERS_DIR = Path(__file__).parent.parent.parent.parent / "shaders"
THUMBNAIL_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "thumbnails"
THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True)

# Note: Route order matters! Specific routes must come before catch-all routes.
# /thumbnail must be defined before /{shader_path:path}

@router.get("/thumbnail")
async def get_thumbnail(path: str):
    """Generate or retrieve cached shader thumbnail"""
    # Sanitize path for cache filename
    safe_name = path.replace('/', '_').replace('\\', '_').replace('..', '')
    cache_path = THUMBNAIL_CACHE_DIR / f"{safe_name}.png"

    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png")

    # Generate thumbnail using renderer
    shader_path = SHADERS_DIR / path

    if not shader_path.exists():
        raise HTTPException(status_code=404, detail="Shader not found")

    # Security check
    try:
        shader_path.resolve().relative_to(SHADERS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        from cedartoy.render import Renderer
        from cedartoy.types import RenderJob, BufferConfig, MultipassGraphConfig

        # Create minimal render job for thumbnail
        output_dir = Path(tempfile.mkdtemp())

        # Create simple multipass config for single-pass render
        multipass = MultipassGraphConfig(
            buffers={
                "Image": BufferConfig(
                    name="Image",
                    shader=shader_path,
                    outputs_to_screen=True,
                    channels={}
                )
            },
            execution_order=["Image"]
        )

        job = RenderJob(
            shader_main=shader_path,
            shader_buffers={},
            output_dir=output_dir,
            output_pattern="thumb_{frame:05d}.png",
            width=256,
            height=144,
            fps=1.0,
            duration_sec=0.0,
            frame_start=0,
            frame_end=0,
            ss_scale=1.0,
            temporal_samples=1,
            shutter=0.0,
            tiles_x=1,
            tiles_y=1,
            default_output_format="png",
            default_bit_depth="8",
            iMouse=(0.0, 0.0, 0.0, 0.0),
            iChannel_paths={},
            defines={},
            audio_path=None,
            audio_mode="shadertoy",
            audio_fps=1.0,
            audio_meta=None,
            camera_mode="2d",
            camera_stereo="none",
            camera_fov=90.0,
            camera_params={"tilt_deg": 0.0, "ipd": 0.064},
            multipass_graph=multipass
        )

        # Render single frame
        renderer = Renderer(job)
        renderer.render_frame(0, output_dir)
        renderer.cleanup()

        # Find generated image
        thumb_path = output_dir / "thumb_00000.png"
        if thumb_path.exists():
            # Copy to cache
            shutil.copy(thumb_path, cache_path)
            # Clean up temp dir
            shutil.rmtree(output_dir, ignore_errors=True)
            return FileResponse(cache_path, media_type="image/png")
        else:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail="Thumbnail generation failed")

    except Exception as e:
        print(f"Thumbnail error: {e}")
        import traceback
        traceback.print_exc()
        # Return placeholder on error
        img = Image.new('RGB', (256, 144), color=(26, 26, 46))
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return Response(content=buffer.getvalue(), media_type="image/png")

@router.get("/", response_model=List[Dict])
async def list_shaders():
    """List all available shader files"""
    shaders = []
    for shader_file in SHADERS_DIR.rglob("*.glsl"):
        # Skip common header files
        if "common" in shader_file.parts:
            continue

        relative_path = shader_file.relative_to(SHADERS_DIR)

        # Parse metadata from shader comments
        metadata = _parse_shader_metadata(shader_file)

        shaders.append({
            "path": str(relative_path).replace("\\", "/"),
            "name": metadata.get("name", relative_path.stem),
            "author": metadata.get("author", "Unknown"),
            "description": metadata.get("description", ""),
        })

    return shaders

# Catch-all route must be LAST
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

def _parse_shader_metadata(shader_path: Path) -> Dict:
    """Parse metadata from shader header comments"""
    metadata = {}

    try:
        with open(shader_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if not line.startswith("//"):
                    break

                # Parse patterns like: // Name: My Shader
                match = re.match(r'^//\s*(\w+):\s*(.+)$', line)
                if match:
                    key = match.group(1).lower()
                    value = match.group(2).strip()
                    metadata[key] = value
                
                # Parse params: // @param name type default min max label
                # Example: // @param speed float 1.0 0.0 5.0 "Speed Factor"
                param_match = re.match(r'^//\s*@param\s+(\w+)\s+(\w+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+(.+)$', line)
                if param_match:
                    if "parameters" not in metadata:
                        metadata["parameters"] = []
                    
                    p_name, p_type, p_def, p_min, p_max, p_label = param_match.groups()
                    
                    # Strip quotes from label if present
                    if p_label.startswith('"') and p_label.endswith('"'):
                        p_label = p_label[1:-1]
                        
                    metadata["parameters"].append({
                        "name": p_name,
                        "type": p_type,
                        "default": float(p_def) if p_type == "float" else int(p_def),
                        "min": float(p_min) if p_type == "float" else int(p_min),
                        "max": float(p_max) if p_type == "float" else int(p_max),
                        "label": p_label
                    })
    except Exception:
        pass

    return metadata
