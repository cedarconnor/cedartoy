from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict, Set
import os
import string
import platform

router = APIRouter()

# Allowlist of directories that can be browsed
# By default, only allow the project directory
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
_ALLOWED_ROOTS: Set[Path] = {_PROJECT_ROOT}

def add_allowed_root(path: Path):
    """Add a directory to the allowlist of browsable paths"""
    _ALLOWED_ROOTS.add(path.resolve())

def is_path_allowed(target_path: Path) -> bool:
    """Check if a path is within any allowed root directory"""
    resolved = target_path.resolve()
    for allowed_root in _ALLOWED_ROOTS:
        try:
            resolved.relative_to(allowed_root)
            return True
        except ValueError:
            continue
    return False

@router.get("/browse")
async def browse_directory(path: str = "."):
    """Browse filesystem for directory/file selection.

    Security: Only paths within the project directory or explicitly
    allowed roots can be browsed. Use add_allowed_root() to add
    additional paths programmatically.
    """
    try:
        target_path = Path(path).resolve()

        # Security: allowlist approach - only allow paths within approved roots
        if not is_path_allowed(target_path):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Path must be within allowed directories: {[str(p) for p in _ALLOWED_ROOTS]}"
            )

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        items = []

        # Add parent directory entry
        if target_path.parent != target_path:
            items.append({
                "name": "..",
                "path": str(target_path.parent),
                "type": "directory",
                "size": None
            })

        # List directory contents
        try:
            for item in sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "directory" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None
                    })
                except PermissionError:
                    continue  # Skip items we can't access
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        return {
            "current_path": str(target_path),
            "items": items
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/drives")
async def get_drives():
    """Get available drives (Windows only) - filtered to allowed roots only"""
    allowed_drives = set()

    for allowed_root in _ALLOWED_ROOTS:
        # Get the drive letter or root for each allowed path
        if platform.system() == "Windows":
            drive = str(allowed_root)[:3]  # e.g., "D:\\"
            allowed_drives.add(drive)
        else:
            allowed_drives.add("/")

    return {"drives": sorted(list(allowed_drives))}

@router.get("/allowed-roots")
async def get_allowed_roots():
    """Get list of allowed root directories"""
    return {"roots": [str(p) for p in sorted(_ALLOWED_ROOTS)]}

@router.post("/add-allowed-root")
async def add_allowed_root_endpoint(path: str):
    """Add a new allowed root directory (requires valid existing path)"""
    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    add_allowed_root(target)
    return {"status": "success", "allowed_roots": [str(p) for p in sorted(_ALLOWED_ROOTS)]}
