"""Native OS folder picker, surfaced as POST /api/dialog/pick-folder.

The actual dialog runs in tkinter. tkinter is part of Python's stdlib so
no extra dependency is needed. FastAPI runs synchronous route handlers
in a worker thread, so the dialog blocks only this request — other
requests keep flowing.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class PickFolderRequest(BaseModel):
    initial_dir: str | None = Field(default=None)


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
