from pathlib import Path

def resolve_output_path(output_dir: Path, pattern: str, frame_idx: int, ext: str = "png") -> Path:
    """
    Resolves the output filename based on a pattern.
    Supports Python format syntax (e.g. "frame_{frame:05d}.{ext}")
    and basic C-style/Nuke-style syntax conversion if needed in future.
    
    For now, we strictly support Python f-string style keys: {frame}, {ext}.
    """
    # Simple formatting
    # We might want to support "image.####.png" style later.
    
    # Check if pattern has frame placeholders
    if "{frame" not in pattern and "%" not in pattern and "#" not in pattern:
        # Static name? Append frame number default
        filename = f"{pattern}_{frame_idx:05d}.{ext}"
    else:
        # Handle '#' conversion to python format? 
        # e.g. "image.####.png" -> "image.{frame:04d}.png"
        if "#" in pattern:
            # count hashes
            import re
            def replace_hashes(match):
                n = len(match.group(0))
                return f"{{frame:0{n}d}}"
            pattern = re.sub(r"#+", replace_hashes, pattern)
            
        try:
            filename = pattern.format(frame=frame_idx, ext=ext)
        except KeyError:
            # Fallback if user messed up format string
            filename = f"out_{frame_idx:05d}.{ext}"
            
    return output_dir / filename
