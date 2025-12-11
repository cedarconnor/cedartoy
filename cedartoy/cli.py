import argparse
import sys
from pathlib import Path
from .config import build_config
from .ui import run_wizard
from .render import Renderer
from .webserver import run_server
from .types import RenderJob, MultipassGraphConfig, BufferConfig, AudioMeta
from .options_schema import OPTIONS

def create_default_multipass(shader_path: Path) -> MultipassGraphConfig:
    # Single pass "Image"
    return MultipassGraphConfig(
        buffers={
            "Image": BufferConfig(
                name="Image",
                shader=shader_path,
                outputs_to_screen=True,
                channels={},
                output_format=None,
                bit_depth=None
            )
        },
        execution_order=["Image"]
    )

def config_to_job(cfg: dict) -> RenderJob:
    # Handle paths
    shader_path = Path(cfg.get("shader", "shaders/image.glsl")) # Default?
    # "shader_main" in RenderJob vs "shader" in options?
    # Options schema doesn't have "shader" explicitly in the list I made earlier!
    # I missed adding "shader_path" to options_schema.
    # But usually it's a positional arg or required opt.
    
    # We'll assume 'shader_path' is passed or we look for it.
    
    audio_path = Path(cfg["audio_path"]) if cfg.get("audio_path") else None
    
    # Construct RenderJob
    # We need to map config keys to RenderJob fields
    
    # Multipass: if config has "multipass", use it. Else default.
    # For now, default.
    mp = create_default_multipass(shader_path)
    
    return RenderJob(
        shader_main=shader_path,
        shader_buffers={}, # TODO: Parse from multipass or separate files
        output_dir=Path(cfg["output_dir"]),
        output_pattern=cfg["output_pattern"],
        width=cfg["width"],
        height=cfg["height"],
        fps=cfg["fps"],
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
        audio_fps=cfg["fps"], # Use video FPS for audio processing?
        audio_meta=None, # Will be filled by Renderer or AudioProcessor
        camera_mode=cfg["camera_mode"],
        camera_stereo=cfg["camera_stereo"],
        camera_fov=cfg["camera_fov"],
        camera_params={
            "tilt_deg": cfg["camera_tilt_deg"],
            "ipd": cfg["camera_ipd"]
        },
        multipass_graph=mp
    )

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

    args = parser.parse_args()
    
    if args.command == "wizard":
        run_wizard()
        return
        
    if args.command == "serve":
        run_server(port=args.port)
        return
        
    if args.command == "render":
        if not args.shader and not args.config:
            # Maybe shader is in config?
            pass
            
        # Build config dict
        cli_args = {}
        for opt in OPTIONS:
            val = getattr(args, opt.name, None)
            if val is not None:
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