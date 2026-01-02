from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
from pathlib import Path
import yaml
import json

router = APIRouter()

class ConfigData(BaseModel):
    config: Dict[str, Any]

@router.get("/schema")
async def get_schema():
    """Get options schema for form generation"""
    from cedartoy.options_schema import OPTIONS

    schema = []
    for opt in OPTIONS:
        opt_dict = {
            "name": opt.name,
            "label": opt.label,
            "type": opt.type,
            "default": opt.default,
            "help_text": opt.help_text,
        }

        # Add choices if available
        if hasattr(opt, 'choices') and opt.choices:
            opt_dict["choices"] = opt.choices

        schema.append(opt_dict)

    return {"options": schema}

@router.get("/defaults")
async def get_defaults():
    """Get default configuration values"""
    from cedartoy.config import load_defaults

    defaults = load_defaults()
    return {"config": defaults}

@router.post("/save")
async def save_config(data: ConfigData, filepath: str = "cedartoy.yaml"):
    """Save configuration to YAML file"""
    try:
        path = Path(filepath)
        with open(path, 'w') as f:
            yaml.dump(data.config, f, default_flow_style=False)
        return {"status": "success", "path": str(path.resolve())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/load")
async def load_config(filepath: str):
    """Load configuration from YAML/JSON file"""
    try:
        path = Path(filepath)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        with open(path, 'r') as f:
            if path.suffix in ['.yaml', '.yml']:
                config = yaml.safe_load(f)
            elif path.suffix == '.json':
                config = json.load(f)
            else:
                raise HTTPException(status_code=400, detail="Unsupported file format")

        return {"config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/presets")
async def list_presets():
    """List saved preset configurations"""
    presets_dir = Path("presets")
    if not presets_dir.exists():
        return {"presets": []}

    presets = []
    for preset_file in presets_dir.glob("*.yaml"):
        presets.append({
            "name": preset_file.stem,
            "path": str(preset_file)
        })

    return {"presets": presets}

@router.post("/presets")
async def save_preset(data: ConfigData, name: str):
    """Save current config as a named preset"""
    presets_dir = Path("presets")
    presets_dir.mkdir(exist_ok=True)

    # Sanitize preset name
    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_'))
    preset_path = presets_dir / f"{safe_name}.yaml"

    with open(preset_path, 'w') as f:
        yaml.dump(data.config, f, default_flow_style=False)

    return {"status": "success", "path": str(preset_path)}
