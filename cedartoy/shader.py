import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

HEADER_PATH = Path(__file__).parent.parent / "shaders" / "common" / "header.glsl"

FOOTER = """
// --- Main Wrapper ---
out vec4 fragColor_out;
void main() {
    vec4 color = vec4(0.0);
    // Apply tile offset and subpixel jitter to fragCoord
    // iTileOffset: for tiled rendering (default 0,0)
    // iJitter: subpixel offset for AA (Halton sequence, range [-0.5, 0.5])
    mainImage(color, gl_FragCoord.xy + iTileOffset + iJitter);
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


# `// @param name type default min max "label"` — shared by the shader
# listing API, the modulation matrix and the renderer (default binding).
# Mirrors web/js/webgl/renderer.js::_parseShaderParams.
_PARAM_RE = re.compile(
    r'^[ \t]*//[ \t]*@param[ \t]+(\w+)[ \t]+(\w+)[ \t]+(\S+)[ \t]+(\S+)'
    r'[ \t]+(\S+)[ \t]+(.+?)[ \t]*$',
    re.MULTILINE,
)


def parse_params(src: str) -> List[Dict[str, Any]]:
    """Parse ``@param`` declarations anywhere in a shader source.

    Only ``float`` / ``int`` params with numeric default/min/max are kept;
    anything else (prose that happens to start with ``// @param``) is
    ignored. The first declaration of a name wins.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for m in _PARAM_RE.finditer(src or ""):
        name, ptype, p_def, p_min, p_max, label = m.groups()
        if ptype not in ("float", "int") or name in seen:
            continue
        conv = float if ptype == "float" else int
        try:
            default, lo, hi = conv(p_def), conv(p_min), conv(p_max)
        except ValueError:
            continue
        if len(label) >= 2 and label.startswith('"') and label.endswith('"'):
            label = label[1:-1]
        seen.add(name)
        out.append({"name": name, "type": ptype, "default": default,
                    "min": lo, "max": hi, "label": label})
    return out
