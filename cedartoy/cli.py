import argparse
import sys
import webbrowser
import threading
import time
from pathlib import Path
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional
from .config import build_config
from .ui import run_wizard
from .render import Renderer
from .webserver import run_server
from .types import RenderJob, MultipassGraphConfig, BufferConfig, AudioMeta
from .options_schema import OPTIONS

def create_default_multipass(shader_path: Path, channels: Optional[Dict[int, str]] = None) -> MultipassGraphConfig:
    # Single pass "Image"
    return MultipassGraphConfig(
        buffers={
            "Image": BufferConfig(
                name="Image",
                shader=shader_path,
                outputs_to_screen=True,
                channels=channels or {},
                output_format=None,
                bit_depth=None
            )
        },
        execution_order=["Image"]
    )

def _normalize_channels(raw: Any) -> Dict[int, str]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        return {i: str(v) for i, v in enumerate(raw) if v is not None}
    if isinstance(raw, dict):
        out = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except Exception:
                continue
            if v is not None:
                out[idx] = str(v)
        return out
    return {}

def _topo_sort(buffers: Dict[str, BufferConfig]) -> List[str]:
    deps: Dict[str, set] = {name: set() for name in buffers}
    rev: Dict[str, set] = defaultdict(set)
    for name, buf in buffers.items():
        for _, src in (buf.channels or {}).items():
            if not isinstance(src, str):
                continue
            if src == name:
                # Self-reference is treated as feedback and ignored for ordering.
                continue
            if src in buffers:
                deps[name].add(src)
                rev[src].add(name)

    indegree = {name: len(deps[name]) for name in buffers}
    q = deque([n for n, d in indegree.items() if d == 0])
    order: List[str] = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in rev.get(n, []):
            indegree[m] -= 1
            if indegree[m] == 0:
                q.append(m)

    if len(order) != len(buffers):
        raise ValueError("Cycle detected in multipass graph.")
    return order

def parse_multipass(cfg: dict, shader_main_path: Path) -> MultipassGraphConfig:
    mp_cfg = cfg.get("multipass")
    if not isinstance(mp_cfg, dict):
        raise ValueError("multipass must be a mapping.")

    buffers_raw = mp_cfg.get("buffers")
    if buffers_raw is None:
        buffers_raw = {k: v for k, v in mp_cfg.items() if k not in ("execution_order", "buffers")}
    if not isinstance(buffers_raw, dict) or not buffers_raw:
        raise ValueError("multipass.buffers must be a non-empty mapping.")

    buffers: Dict[str, BufferConfig] = {}
    for name, braw in buffers_raw.items():
        if not isinstance(braw, dict):
            raise ValueError(f"Buffer '{name}' must be a mapping.")
        shader_val = braw.get("shader")
        shader_path = Path(shader_val) if shader_val else (shader_main_path if name == "Image" else None)
        if shader_path is None:
            raise ValueError(f"Buffer '{name}' is missing a shader path.")
        if not shader_path.exists():
            raise FileNotFoundError(f"Shader file not found for buffer '{name}': {shader_path}")

        outputs_to_screen = bool(braw.get("outputs_to_screen", name == "Image"))
        channels = _normalize_channels(braw.get("channels"))
        buffers[name] = BufferConfig(
            name=name,
            shader=shader_path,
            outputs_to_screen=outputs_to_screen,
            channels=channels,
            output_format=braw.get("output_format"),
            bit_depth=braw.get("bit_depth"),
        )

    screen_buffers = [n for n, b in buffers.items() if b.outputs_to_screen]
    if len(screen_buffers) != 1:
        raise ValueError(f"Expected exactly one outputs_to_screen buffer, got {screen_buffers}.")

    order_raw = mp_cfg.get("execution_order")
    if order_raw:
        if not isinstance(order_raw, list):
            raise ValueError("multipass.execution_order must be a list.")
        order = [str(n) for n in order_raw]
        missing = [n for n in order if n not in buffers]
        if missing:
            raise ValueError(f"execution_order references unknown buffers: {missing}")
    else:
        order = _topo_sort(buffers)

    if screen_buffers[0] != order[-1]:
        raise ValueError(f"outputs_to_screen buffer '{screen_buffers[0]}' must be last in execution_order.")

    return MultipassGraphConfig(buffers=buffers, execution_order=order)

def config_to_job(cfg: dict) -> RenderJob:
    # Handle paths
    shader_value = cfg.get("shader")
    if not shader_value:
        raise ValueError("Shader path is required (positional arg or in config as 'shader').")
    shader_path = Path(shader_value)
    if not shader_path.exists():
        raise FileNotFoundError(f"Shader file not found: {shader_path}")
    
    audio_path = Path(cfg["audio_path"]) if cfg.get("audio_path") else None
    
    # Construct RenderJob
    # We need to map config keys to RenderJob fields
    
    # Multipass: if config has "multipass", parse it. Else default single-pass.
    if "multipass" in cfg and cfg["multipass"] is not None:
        mp = parse_multipass(cfg, shader_path)
    else:
        top_channels = _normalize_channels(cfg.get("iChannel_paths") or cfg.get("channels"))
        # Convert top-level file channels to file sources
        file_channels = {i: f"file:{p}" for i, p in top_channels.items()}
        mp = create_default_multipass(shader_path, channels=file_channels)

    shader_buffers = {name: buf.shader for name, buf in mp.buffers.items() if name != "Image"}
    
    return RenderJob(
        shader_main=shader_path,
        shader_buffers=shader_buffers,
        output_dir=Path(cfg["output_dir"]),
        output_pattern=cfg["output_pattern"],
        width=cfg["width"],
        height=cfg["height"],
        fps=cfg["fps"],
        duration_sec=cfg["duration_sec"],
        frame_start=cfg["frame_start"],
        frame_end=cfg["frame_end"],
        tiles_x=cfg["tiles_x"],
        tiles_y=cfg["tiles_y"],
        ss_scale=cfg["ss_scale"],
        temporal_samples=cfg["temporal_samples"],
        shutter=cfg["shutter"],
        default_output_format=cfg["default_output_format"],
        default_bit_depth=cfg["default_bit_depth"],
        iMouse=(0.0, 0.0, 0.0, 0.0),
        iChannel_paths={},
        defines={},
        audio_path=audio_path,
        audio_mode=cfg["audio_mode"],
        audio_fps=cfg["fps"], # Use video FPS for audio processing?
        audio_meta=None, # Will be filled by Renderer or AudioProcessor
        camera_mode=cfg["camera_mode"],
        camera_stereo=cfg["camera_stereo"],
        camera_fov=cfg["camera_fov"],
        camera_params={
            "tilt_deg": cfg["camera_tilt_deg"],
            "ipd": cfg["camera_ipd"]
        },
        disk_streaming=cfg.get("disk_streaming"),
        multipass_graph=mp
    )

def run_ui_server(args):
    """Start the FastAPI web UI server"""
    try:
        import uvicorn
        from cedartoy.server.app import app
    except ImportError:
        print("Error: FastAPI dependencies not installed. Run: pip install fastapi uvicorn[standard]")
        sys.exit(1)

    # Open browser automatically unless disabled
    if not args.no_browser:
        def open_browser():
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open(f'http://localhost:{args.port}')

        threading.Thread(target=open_browser, daemon=True).start()

    print(f"Starting CedarToy Web UI on http://localhost:{args.port}")
    print("Press Ctrl+C to stop")

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")

def main():
    parser = argparse.ArgumentParser(description="CedarToy Renderer")
    subparsers = parser.add_subparsers(dest="command")
    
    # Render
    render_parser = subparsers.add_parser("render", help="Render a shader")
    render_parser.add_argument("shader", nargs="?", help="Path to shader file")
    render_parser.add_argument("--config", help="Path to config file")
    
    # Add CLI overrides from OPTIONS
    for opt in OPTIONS:
        # Skip some complex ones or handle them
        arg_name = f"--{opt.name.replace('_', '-')}"
        if opt.type == "bool":
            render_parser.add_argument(arg_name, action="store_true" if not opt.default else "store_false")
        elif opt.type == "int":
            render_parser.add_argument(arg_name, type=int, help=opt.help_text or opt.label)
        elif opt.type == "float":
            render_parser.add_argument(arg_name, type=float, help=opt.help_text or opt.label)
        else:
            render_parser.add_argument(arg_name, type=str, help=opt.help_text or opt.label)

    # Wizard
    wizard_parser = subparsers.add_parser("wizard", help="Run configuration wizard")
    
    # Serve
    serve_parser = subparsers.add_parser("serve", help="Start web preview server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")

    # UI
    ui_parser = subparsers.add_parser("ui", help="Start web UI server")
    ui_parser.add_argument("--port", type=int, default=8080, help="Server port")
    ui_parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    args = parser.parse_args()
    
    if args.command == "wizard":
        run_wizard()
        return
        
    if args.command == "serve":
        run_server(port=args.port)
        return

    if args.command == "ui":
        run_ui_server(args)
        return

    if args.command == "render":
        if not args.shader and not args.config:
            parser.error("render requires a shader path or --config with a 'shader' entry.")
            
        # Build config dict
        cli_args = {}
        for opt in OPTIONS:
            val = getattr(args, opt.name, None)
            if val is not None:
                # Handle special conversions for choice type with None/True/False
                if opt.name == "disk_streaming" and isinstance(val, str):
                    if val.lower() == "none":
                        val = None
                    elif val.lower() == "true":
                        val = True
                    elif val.lower() == "false":
                        val = False
                cli_args[opt.name] = val
        
        # Shader path from positional arg overrides
        if args.shader:
            cli_args["shader"] = args.shader
            
        cfg = build_config(Path(args.config) if args.config else None, cli_args)
        
        # Create Job
        job = config_to_job(cfg)
        
        # Render
        renderer = Renderer(job)
        renderer.render()
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
