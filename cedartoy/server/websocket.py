from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import subprocess
import json
import sys
import queue

from .api.render import job_manager
from .jobs import JobStatus


router = APIRouter()

active_connections = []


@router.websocket("/render")
async def websocket_render(websocket: WebSocket):
    """WebSocket endpoint for render progress."""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "start_render":
                await handle_render(websocket, data)
            elif msg_type == "subscribe":
                await websocket.send_json({"type": "subscribed", "channels": ["render_progress"]})

    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


async def handle_render(websocket: WebSocket, data):
    """Execute a queued render job and stream progress using a thread-safe queue."""
    job_id = data.get("job_id")
    if not job_id:
        await websocket.send_json({"type": "render_error", "message": "No job_id provided"})
        return

    try:
        job = job_manager.get_job(job_id)
    except KeyError:
        await websocket.send_json({"type": "render_error", "message": "Render job not found", "job_id": job_id})
        return

    cmd = [sys.executable, "-m", "cedartoy.cli", "render", "--config", str(job.config_file)]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        job_manager.mark_running(job_id, process.pid, process=process)

        message_queue: queue.Queue = queue.Queue()

        import threading

        def read_stream(stream, prefix: str):
            """Read from stream and put lines in queue. Drains properly."""
            try:
                for line in iter(stream.readline, ""):
                    if line:
                        message_queue.put((prefix, line.strip()))
                stream.close()
            except Exception as e:
                message_queue.put(("error", str(e)))

        stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        while process.poll() is None or not message_queue.empty():
            try:
                _prefix, line = message_queue.get(timeout=0.1)
                await process_log_line(websocket, job_id, line)
            except queue.Empty:
                await asyncio.sleep(0.05)

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

        while not message_queue.empty():
            try:
                _prefix, line = message_queue.get_nowait()
                await process_log_line(websocket, job_id, line)
            except queue.Empty:
                break

        return_code = process.returncode
        current = job_manager.get_job(job_id)

        if current.status == JobStatus.CANCELLED:
            await websocket.send_json({"type": "render_cancelled", "job_id": job_id})
            return

        if return_code == 0:
            if current.status != JobStatus.COMPLETE:
                complete_data = {"code": return_code, "output_dir": str(current.config.get("output_dir", "renders"))}
                job_manager.mark_complete(job_id, complete_data)
                await websocket.send_json({"type": "render_complete", "job_id": job_id, **complete_data})
        else:
            error_data = {"message": f"Render process exited with code {return_code}"}
            job_manager.mark_error(job_id, error_data)
            await websocket.send_json({"type": "render_error", "job_id": job_id, **error_data})

    except Exception as e:
        import traceback

        traceback.print_exc()
        error_data = {"message": f"Render error: {str(e)}"}
        try:
            job_manager.mark_error(job_id, error_data)
        except KeyError:
            pass
        await websocket.send_json({"type": "render_error", "job_id": job_id, **error_data})


async def process_log_line(websocket: WebSocket, job_id: str, line: str):
    """Process a single log line from render output."""
    line = line.strip()

    try:
        if line.startswith("[PROGRESS]"):
            progress_data = json.loads(line[10:].strip())
            if progress_data["frame"] > 0 and progress_data["elapsed_sec"] > 0:
                frames_per_sec = progress_data["frame"] / progress_data["elapsed_sec"]
                remaining_frames = progress_data["total"] - progress_data["frame"]
                eta_sec = remaining_frames / frames_per_sec if frames_per_sec > 0 else 0
                progress_data["eta_sec"] = round(eta_sec, 1)

            job_manager.update_progress(job_id, progress_data)
            await websocket.send_json({"type": "render_progress", "job_id": job_id, **progress_data})

        elif line.startswith("[LOG]"):
            message = line[5:].strip()
            job_manager.append_log(job_id, message)
            await websocket.send_json({"type": "render_log", "job_id": job_id, "message": message})

        elif line.startswith("[COMPLETE]"):
            complete_data = json.loads(line[10:].strip())
            job_manager.mark_complete(job_id, complete_data)
            await websocket.send_json({"type": "render_complete", "job_id": job_id, **complete_data})

        elif line.startswith("[ERROR]"):
            error_data = json.loads(line[7:].strip())
            job_manager.mark_error(job_id, error_data)
            await websocket.send_json({"type": "render_error", "job_id": job_id, **error_data})
        elif line:
            job_manager.append_log(job_id, line)
            await websocket.send_json({"type": "render_log", "job_id": job_id, "message": line})

    except json.JSONDecodeError:
        job_manager.append_log(job_id, line)
        await websocket.send_json({"type": "render_log", "job_id": job_id, "message": line})
    except Exception as e:
        print(f"Error processing log line: {e}", file=sys.stderr)
