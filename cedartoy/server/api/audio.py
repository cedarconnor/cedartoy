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
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix, mode='wb')
    content = await file.read()
    temp_file.write(content)
    temp_file.close()

    # Process audio
    try:
        # Use 60 fps for preview (will be overridden for actual renders)
        from pathlib import Path as PathLib
        processor = AudioProcessor(PathLib(temp_file.name), fps=60.0)
        audio_state["processor"] = processor
        audio_state["file_path"] = temp_file.name
        audio_state["metadata"] = {
            "duration": processor.meta.duration_sec,
            "sample_rate": processor.meta.sample_rate,
            "channels": processor.meta.channels,
            "frames": processor.meta.frame_count,
        }

        return {
            "status": "success",
            "metadata": audio_state["metadata"]
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
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
