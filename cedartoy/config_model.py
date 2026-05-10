from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CameraMode = Literal["2d", "equirect", "ll180"]
StereoMode = Literal["none", "sbs", "tb"]
AudioMode = Literal["shadertoy", "history", "both"]
OutputFormat = Literal["png", "exr"]
BitDepth = Literal["8", "16f", "32f"]


class CedarToyConfig(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    shader: Path
    width: int = 1920
    height: int = 1080
    fps: float = 60.0
    duration_sec: float = 10.0
    frame_start: int = 0
    frame_end: int = 0
    tiles_x: int = 1
    tiles_y: int = 1
    ss_scale: float = 1.0
    temporal_samples: int = 1
    shutter: float = 0.5
    default_output_format: OutputFormat = "png"
    default_bit_depth: BitDepth = "8"
    audio_path: Optional[Path] = None
    audio_mode: AudioMode = "both"
    camera_mode: CameraMode = "2d"
    camera_stereo: StereoMode = "none"
    camera_fov: float = 90.0
    camera_tilt_deg: float = 65.0
    camera_ipd: float = 0.064
    output_dir: Path = Path("renders")
    output_pattern: str = "frame_{frame:05d}.{ext}"
    disk_streaming: Optional[bool] = None
    shader_parameters: Dict[str, Any] = Field(default_factory=dict)
    channels: Optional[Dict[int, str]] = None
    iChannel_paths: Optional[Dict[int, str]] = None
    multipass: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        camera_params = migrated.get("camera_params")
        if isinstance(camera_params, dict):
            if "camera_tilt_deg" not in migrated and "tilt_deg" in camera_params:
                migrated["camera_tilt_deg"] = camera_params["tilt_deg"]
            if "camera_ipd" not in migrated and "ipd" in camera_params:
                migrated["camera_ipd"] = camera_params["ipd"]
        return migrated

    @field_validator("width", "height", "tiles_x", "tiles_y", "temporal_samples")
    @classmethod
    def positive_int(cls, value: int, info):
        if value < 1:
            raise ValueError(f"{info.field_name} must be at least 1")
        return value

    @field_validator("fps", "ss_scale")
    @classmethod
    def positive_float(cls, value: float, info):
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value

    @field_validator("shutter")
    @classmethod
    def shutter_range(cls, value: float):
        if value < 0 or value > 1:
            raise ValueError("shutter must be between 0 and 1")
        return value

    @property
    def camera_params(self) -> Dict[str, float]:
        return {"tilt_deg": self.camera_tilt_deg, "ipd": self.camera_ipd}

    def to_runtime_dict(self) -> Dict[str, Any]:
        data = self.model_dump(mode="python")
        data["camera_params"] = self.camera_params
        return data


def normalize_config(raw: Dict[str, Any]) -> CedarToyConfig:
    return CedarToyConfig.model_validate(raw)
