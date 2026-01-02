from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict
import os
import string
import platform

router = APIRouter()

@router.get("/browse")
async def browse_directory(path: str = "."):
    """Browse filesystem for directory/file selection"""
    try:
        target_path = Path(path).resolve()

        # Security: restrict to reasonable paths
        # Don't allow browsing system directories
        restricted = ['C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)', '/etc', '/usr', '/bin', '/sys', '/proc']
        if any(str(target_path).startswith(r) for r in restricted):
            raise HTTPException(status_code=403, detail="Access denied")

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
    """Get available drives (Windows only)"""
    if platform.system() != "Windows":
        return {"drives": ["/"]}

    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)

    return {"drives": drives}
