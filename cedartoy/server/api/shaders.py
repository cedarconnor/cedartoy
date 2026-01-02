from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
from typing import List, Dict
import re
from PIL import Image
import io

router = APIRouter()

SHADERS_DIR = Path(__file__).parent.parent.parent.parent / "shaders"
THUMBNAIL_CACHE_DIR = Path("thumbnails")
THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True)

@router.get("/", response_model=List[Dict])
async def list_shaders():
    """List all available shader files"""
    shaders = []
    for shader_path in SHADERS_DIR.rglob("*.glsl"):
        relative_path = shader_path.relative_to(SHADERS_DIR)

        # Parse metadata from shader comments
        metadata = _parse_shader_metadata(shader_path)

        shaders.append({
            "path": str(relative_path).replace("\\", "/"),
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

@router.get("/thumbnail")
async def get_thumbnail(path: str):
    """Generate or retrieve cached shader thumbnail"""
    # Check cache
    safe_name = path.replace('/', '_').replace('\\', '_').replace('..', '')
    cache_path = THUMBNAIL_CACHE_DIR / f"{safe_name}.png"

    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/png")

    # Generate thumbnail using renderer
    shader_path = SHADERS_DIR / path

    if not shader_path.exists():
        raise HTTPException(status_code=404, detail="Shader not found")

    try:
        from cedartoy.render import Renderer
        from cedartoy.types import RenderJob, MultipassGraphConfig
        import tempfile
        import shutil

        # Create minimal render job for thumbnail
        output_dir = tempfile.mkdtemp()

        job = RenderJob(
            shader=str(shader_path),
            output_dir=output_dir,
            output_pattern="thumb.png",
            width=256,
            height=144,
            fps=1,
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
            audio_path=None,
            audio_mode="shadertoy",
            camera_mode="2d",
            camera_stereo="none",
            camera_fov=90.0,
            camera_tilt_deg=0.0,
            camera_ipd=0.064,
            multipass_graph=None
        )

        # Render single frame
        renderer = Renderer(job)
        renderer.render_frame(0, time=0.0)

        # Read generated image
        thumb_path = Path(output_dir) / "thumb_00000.png"
        if thumb_path.exists():
            # Copy to cache
            shutil.copy(thumb_path, cache_path)
            # Clean up temp dir
            shutil.rmtree(output_dir, ignore_errors=True)
            return FileResponse(cache_path, media_type="image/png")
        else:
            raise HTTPException(status_code=500, detail="Thumbnail generation failed")

    except Exception as e:
        print(f"Thumbnail error: {e}")
        # Return placeholder on error
        img = Image.new('RGB', (256, 144), color=(26, 26, 46))
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return Response(content=buffer.getvalue(), media_type="image/png")

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
                if not line.startswith("//"):
                    break

                # Parse patterns like: // Name: My Shader
                match = re.match(r'^//\s*(\w+):\s*(.+)$', line)
                if match:
                    key = match.group(1).lower()
                    value = match.group(2).strip()
                    metadata[key] = value
    except Exception:
        pass

    return metadata
