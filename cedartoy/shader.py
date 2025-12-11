import os
from pathlib import Path
from typing import Optional

HEADER_PATH = Path(__file__).parent.parent / "shaders" / "common" / "header.glsl"

FOOTER = """
// --- Main Wrapper ---
out vec4 fragColor_out;
void main() {
    vec4 color = vec4(0.0);
    // Apply tile offset to fragCoord
    // Default iTileOffset is (0,0) if not set, so this is safe.
    mainImage(color, gl_FragCoord.xy + iTileOffset);
    fragColor_out = color;
}
"""

def load_header() -> str:
    if not HEADER_PATH.exists():
        return ""
    with open(HEADER_PATH, 'r', encoding='utf-8') as f:
        return f.read()

def assemble_shader(user_source: str, defines: Optional[dict] = None) -> str:
    """
    Assembles the final fragment shader source.
    1. Version
    2. Defines
    3. Header (Uniforms, Helpers)
    4. User Source (mainImage)
    5. Footer (main)
    """
    parts = []
    
    # We already have #version 430 core in header, but maybe we should strip it or ensure it's first.
    # The header has it.
    
    header = load_header()
    
    # Split header to inject defines after version
    lines = header.splitlines()
    version_line = ""
    rest_header = []
    for line in lines:
        if line.strip().startswith("#version"):
            version_line = line
        else:
            rest_header.append(line)
            
    parts.append(version_line if version_line else "#version 430 core")
    
    if defines:
        for k, v in defines.items():
            if v is None:
                parts.append(f"#define {k}")
            else:
                parts.append(f"#define {k} {v}")
                
    parts.append("\n".join(rest_header))
    parts.append("\n// --- User Shader ---\n")
    parts.append(user_source)
    parts.append(FOOTER)
    
    return "\n".join(parts)

def load_shader_from_file(path: Path, defines: Optional[dict] = None) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Shader file not found: {path}")
        
    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()
        
    return assemble_shader(source, defines)
