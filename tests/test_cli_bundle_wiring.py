"""Lock down CLI → RenderJob wiring for MusiCue bundle fields.

This regression test catches the failure where ``--bundle-mode``,
``--bundle-path``, and ``--bundle-blend`` are parsed by argparse and
merged into the config dict, but ``config_to_job()`` silently drops
them before constructing ``RenderJob``. We hit that bug during the
manual A/B visual smoke; this test makes future regressions noisy.
"""
from pathlib import Path

import pytest

from cedartoy.cli import config_to_job
from cedartoy.config import build_config


SHADER = Path("shaders/audio_reactive_simple.glsl")


def _base_cli_args(**overrides):
    """Minimal CLI-style dict that build_config + config_to_job accept."""
    args = {
        "shader": str(SHADER),
    }
    args.update(overrides)
    return args


def test_bundle_defaults_round_trip_when_no_cli_flags():
    cfg = build_config(cli_args=_base_cli_args())
    job = config_to_job(cfg)

    assert job.bundle_path is None
    assert job.bundle_mode == "auto"
    assert job.bundle_blend == 0.5


def test_bundle_mode_cli_flag_reaches_render_job():
    cfg = build_config(cli_args=_base_cli_args(bundle_mode="cued"))
    job = config_to_job(cfg)

    assert job.bundle_mode == "cued"


def test_bundle_mode_raw_distinct_from_cued():
    raw_job = config_to_job(build_config(cli_args=_base_cli_args(bundle_mode="raw")))
    cued_job = config_to_job(build_config(cli_args=_base_cli_args(bundle_mode="cued")))

    assert raw_job.bundle_mode == "raw"
    assert cued_job.bundle_mode == "cued"
    assert raw_job.bundle_mode != cued_job.bundle_mode


def test_bundle_path_cli_flag_reaches_render_job(tmp_path):
    bundle = tmp_path / "song.musicue.json"
    bundle.write_text("{}")
    cfg = build_config(cli_args=_base_cli_args(bundle_path=str(bundle)))
    job = config_to_job(cfg)

    assert job.bundle_path == bundle


def test_bundle_blend_cli_flag_reaches_render_job():
    cfg = build_config(cli_args=_base_cli_args(bundle_blend=0.75))
    job = config_to_job(cfg)

    assert job.bundle_blend == 0.75


def test_bundle_blend_validated_to_unit_range():
    with pytest.raises(ValueError, match="bundle_blend"):
        build_config(cli_args=_base_cli_args(bundle_blend=1.5))


def test_all_three_bundle_fields_round_trip_together(tmp_path):
    bundle = tmp_path / "x.musicue.json"
    bundle.write_text("{}")

    cfg = build_config(cli_args=_base_cli_args(
        bundle_path=str(bundle),
        bundle_mode="blend",
        bundle_blend=0.3,
    ))
    job = config_to_job(cfg)

    assert job.bundle_path == bundle
    assert job.bundle_mode == "blend"
    assert job.bundle_blend == 0.3
