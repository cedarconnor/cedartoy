from pathlib import Path

import pytest

from cedartoy.config_model import CedarToyConfig, normalize_config


def test_defaults_match_current_runtime_contract():
    cfg = CedarToyConfig(shader=Path("shaders/test.glsl"))

    assert cfg.width == 1920
    assert cfg.height == 1080
    assert cfg.fps == 60.0
    assert cfg.output_dir == Path("renders")
    assert cfg.output_pattern == "frame_{frame:05d}.{ext}"
    assert cfg.camera_mode == "2d"
    assert cfg.camera_params["tilt_deg"] == 65.0
    assert cfg.camera_params["ipd"] == 0.064


def test_migrates_legacy_camera_params_to_flat_fields():
    raw = {
        "shader": "shaders/test.glsl",
        "camera_params": {"tilt_deg": 12.5, "ipd": 0.07},
    }

    cfg = normalize_config(raw)

    assert cfg.camera_tilt_deg == 12.5
    assert cfg.camera_ipd == 0.07
    assert cfg.camera_params == {"tilt_deg": 12.5, "ipd": 0.07}


def test_rejects_invalid_render_dimensions():
    with pytest.raises(ValueError, match="width"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), width=0)

    with pytest.raises(ValueError, match="height"):
        CedarToyConfig(shader=Path("shaders/test.glsl"), height=-1)


def test_preserves_nested_multipass_config():
    raw = {
        "shader": "shaders/test.glsl",
        "multipass": {
            "buffers": {
                "A": {"shader": "shaders/test.glsl", "channels": {0: "A"}},
                "Image": {
                    "shader": "shaders/test.glsl",
                    "outputs_to_screen": True,
                    "channels": {0: "A"},
                },
            }
        },
    }

    cfg = normalize_config(raw)

    assert cfg.multipass["buffers"]["A"]["channels"] == {0: "A"}
    assert cfg.multipass["buffers"]["Image"]["outputs_to_screen"] is True
