import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import sys

try:
    import yaml
except ImportError:
    yaml = None

from .options_schema import OPTIONS

def load_defaults() -> Dict[str, Any]:
    defaults = {}
    for opt in OPTIONS:
        defaults[opt.name] = opt.default
    return defaults

def load_from_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        if path.suffix.lower() in ['.yaml', '.yml']:
            if yaml is None:
                print(f"Warning: YAML config found at {path} but PyYAML is not installed. Skipping.", file=sys.stderr)
                return {}
            return yaml.safe_load(f) or {}
        elif path.suffix.lower() == '.json':
            return json.load(f)
    return {}

def merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    # Shallow merge for now, deep merge if we have nested dicts in options
    # The options are mostly flat, except maybe camera_params which is constructed later?
    # Or maybe we should do deep merge if needed.
    res = base.copy()
    for k, v in override.items():
        if v is not None:
            res[k] = v
    return res

def build_config(config_path: Optional[Path] = None, cli_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = load_defaults()
    
    if config_path:
        file_cfg = load_from_file(config_path)
        cfg = merge_configs(cfg, file_cfg)
        
    if cli_args:
        cfg = merge_configs(cfg, cli_args)
        
    return cfg
