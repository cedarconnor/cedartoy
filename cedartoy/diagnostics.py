from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, List


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class DiagnosticItem:
    severity: DiagnosticSeverity
    code: str
    message: str


@dataclass
class DiagnosticResult:
    items: List[DiagnosticItem]

    @property
    def ok(self) -> bool:
        return not any(item.severity == DiagnosticSeverity.ERROR for item in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "items": [
                {"severity": item.severity, "code": item.code, "message": item.message}
                for item in self.items
            ],
        }


def run_preflight_checks(config: Dict[str, Any]) -> DiagnosticResult:
    items: List[DiagnosticItem] = []
    shader = Path(str(config.get("shader", "")))

    if not shader.exists():
        items.append(DiagnosticItem(
            DiagnosticSeverity.ERROR,
            "shader.missing",
            f"Shader file not found: {shader}",
        ))
    elif not shader.is_file():
        items.append(DiagnosticItem(
            DiagnosticSeverity.ERROR,
            "shader.not_file",
            f"Shader path is not a file: {shader}",
        ))

    width = int(config.get("width", 1920))
    height = int(config.get("height", 1080))
    ss_scale = float(config.get("ss_scale", 1.0))
    tiles_x = int(config.get("tiles_x", 1))
    tiles_y = int(config.get("tiles_y", 1))

    internal_width = max(1, int(round(width * ss_scale)))
    internal_height = max(1, int(round(height * ss_scale)))
    full_rgba32_bytes = internal_width * internal_height * 4 * 4
    tile_rgba32_bytes = (
        ((internal_width + tiles_x - 1) // tiles_x)
        * ((internal_height + tiles_y - 1) // tiles_y)
        * 4
        * 4
    )

    if full_rgba32_bytes > 4 * 1024**3 and tiles_x * tiles_y == 1:
        gb = full_rgba32_bytes / 1024**3
        items.append(DiagnosticItem(
            DiagnosticSeverity.WARNING,
            "memory.estimate.high",
            f"Estimated full-frame RGBA32 accumulation buffer is {gb:.2f} GB. "
            "Increase tiles_x/tiles_y or enable disk_streaming for safer long renders.",
        ))

    if tile_rgba32_bytes > 1024**3:
        gb = tile_rgba32_bytes / 1024**3
        items.append(DiagnosticItem(
            DiagnosticSeverity.WARNING,
            "memory.tile.high",
            f"Estimated per-tile RGBA32 buffer is {gb:.2f} GB. Use more tiles for lower peak memory.",
        ))

    output_dir = Path(str(config.get("output_dir", "renders")))
    if output_dir.exists() and not output_dir.is_dir():
        items.append(DiagnosticItem(
            DiagnosticSeverity.ERROR,
            "output.not_directory",
            f"Output path exists and is not a directory: {output_dir}",
        ))

    return DiagnosticResult(items)
