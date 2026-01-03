from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import subprocess
import json
import sys
import queue
from pathlib import Path
from typing import Optional

router = APIRouter()

active_connections = []

@router.websocket("/render")
async def websocket_render(websocket: WebSocket):
    """WebSocket endpoint for render progress"""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "start_render":
                await handle_render(websocket, data)
            elif msg_type == "subscribe":
                # Client subscribes to render progress
                await websocket.send_json({"type": "subscribed", "channels": ["render_progress"]})

    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)

async def handle_render(websocket: WebSocket, data):
    """Execute render and stream progress using thread-safe queue"""
    from .api.render import render_state

    config_file = data.get("config_file")
    if not config_file:
        await websocket.send_json({
            "type": "render_error",
            "message": "No config file provided"
        })
        return

    # Build command
    cmd = [sys.executable, "-m", "cedartoy.cli", "render", "--config", config_file]

    try:
        # Start subprocess with pipes
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        render_state["process"] = process
        render_state["active"] = True

        # Use a thread-safe queue for communication
        message_queue: queue.Queue = queue.Queue()

        import threading

        def read_stream(stream, prefix: str):
            """Read from stream and put lines in queue. Drains properly."""
            try:
                for line in iter(stream.readline, ''):
                    if line:
                        message_queue.put((prefix, line.strip()))
                stream.close()
            except Exception as e:
                message_queue.put(("error", str(e)))

        # Start threads to read both stdout and stderr (prevents deadlock)
        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, "stdout"),
            daemon=True
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, "stderr"),
            daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()

        # Process messages from queue while process runs
        while process.poll() is None or not message_queue.empty():
            try:
                # Non-blocking get with timeout
                prefix, line = message_queue.get(timeout=0.1)
                await process_log_line(websocket, line)
            except queue.Empty:
                # No message available, continue waiting
                await asyncio.sleep(0.05)

        # Wait for threads to finish draining
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

        # Process any remaining messages
        while not message_queue.empty():
            try:
                prefix, line = message_queue.get_nowait()
                await process_log_line(websocket, line)
            except queue.Empty:
                break

        # Process finished
        return_code = process.returncode

        if return_code == 0:
            await websocket.send_json({"type": "render_complete", "code": return_code})
        else:
            await websocket.send_json({
                "type": "render_error",
                "message": f"Render process exited with code {return_code}"
            })

        render_state["active"] = False
        render_state["process"] = None

    except Exception as e:
        import traceback
        traceback.print_exc()
        await websocket.send_json({
            "type": "render_error",
            "message": f"Render error: {str(e)}"
        })
        render_state["active"] = False
        render_state["process"] = None

async def process_log_line(websocket: WebSocket, line: str):
    """Process a single log line from render output"""
    line = line.strip()

    try:
        if line.startswith("[PROGRESS]"):
            progress_data = json.loads(line[10:].strip())
            # Calculate ETA
            if progress_data["frame"] > 0 and progress_data["elapsed_sec"] > 0:
                frames_per_sec = progress_data["frame"] / progress_data["elapsed_sec"]
                remaining_frames = progress_data["total"] - progress_data["frame"]
                eta_sec = remaining_frames / frames_per_sec if frames_per_sec > 0 else 0
                progress_data["eta_sec"] = round(eta_sec, 1)

            await websocket.send_json({
                "type": "render_progress",
                **progress_data
            })

        elif line.startswith("[LOG]"):
            message = line[5:].strip()
            await websocket.send_json({
                "type": "render_log",
                "message": message
            })

        elif line.startswith("[COMPLETE]"):
            complete_data = json.loads(line[10:].strip())
            await websocket.send_json({
                "type": "render_complete",
                **complete_data
            })

        elif line.startswith("[ERROR]"):
            error_data = json.loads(line[7:].strip())
            await websocket.send_json({
                "type": "render_error",
                **error_data
            })
        else:
            # Regular stderr output
            if line:
                await websocket.send_json({
                    "type": "render_log",
                    "message": line
                })

    except json.JSONDecodeError:
        # If JSON parsing fails, just send as regular log
        await websocket.send_json({
            "type": "render_log",
            "message": line
        })
    except Exception as e:
        print(f"Error processing log line: {e}", file=sys.stderr)
