"""Native OS folder picker, surfaced as POST /api/dialog/pick-folder.

The actual dialog runs in tkinter. tkinter is part of Python's stdlib so
no extra dependency is needed. FastAPI runs synchronous route handlers
in a worker thread, so the dialog blocks only this request — other
requests keep flowing.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class PickFolderRequest(BaseModel):
    initial_dir: str | None = Field(default=None)


class OpenFolderRequest(BaseModel):
    path: str = Field(..., description="Absolute path of the folder to reveal.")


def _ask_directory(*, initial_dir: str | None = None) -> str:
    """Open a native folder picker and return the chosen path.

    Returns "" when the user cancels (matching tkinter's contract).
    Raises tk.TclError when no display is available (headless / CI).
    Isolated as a module-level function so tests can mock it cleanly.
    """
    # tkinter requires a root window. Create + hide + destroy to avoid
    # leaving a leaked Tk instance behind.
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        result = filedialog.askdirectory(
            parent=root,
            title="Pick a CedarToy project folder",
            initialdir=initial_dir or None,
            mustexist=True,
        )
        return result or ""
    finally:
        root.destroy()


@router.post("/pick-folder")
def pick_folder(body: PickFolderRequest) -> dict:
    try:
        chosen = _ask_directory(initial_dir=body.initial_dir)
    except tk.TclError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Native dialog unavailable (no display): {e}",
        ) from e
    return {"path": chosen if chosen else None}


def _reveal_in_file_manager(path: Path) -> None:
    """Open the folder in the OS file manager.

    Browsers block file:// navigation from http:// origins, so this must
    happen server-side. Isolated for test mocking.
    """
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    else:
        subprocess.run(["xdg-open", str(path)], check=True)


@router.post("/open-folder")
def open_folder(body: OpenFolderRequest) -> dict:
    """Reveal a folder in the OS file manager.

    Used by the render-panel's "Open Folder" button after a render completes.
    """
    p = Path(body.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {p}")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {p}")
    try:
        _reveal_in_file_manager(p)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to open folder: {e}") from e
    return {"opened": str(p)}
