"""Unit tests for render-budget estimation math."""
from __future__ import annotations

import pytest

from cedartoy.render_estimate import (
    DEFAULT_FRAME_TIME_SEC,
    RenderEstimate,
    bytes_per_frame,
    estimate_render,
)


def test_bytes_per_frame_png_8bit():
    n = bytes_per_frame("png", 8, 1920, 1080)
    assert 8_000_000 < n < 9_000_000


def test_bytes_per_frame_exr_16f():
    n = bytes_per_frame("exr", 16, 1920, 1080)
    assert 16_000_000 < n < 17_000_000


def test_bytes_per_frame_exr_32f():
    n = bytes_per_frame("exr", 32, 1920, 1080)
    assert 33_000_000 < n < 34_000_000


def test_bytes_per_frame_unknown_raises():
    with pytest.raises(ValueError, match="unknown"):
        bytes_per_frame("tiff", 8, 100, 100)


def test_estimate_render_with_no_history_uses_default():
    est = estimate_render(
        shader_basename="auroras",
        width=1920, height=1080,
        fps=60, duration_sec=10.0,
        tile_count=1, ss_scale=1.0,
        format="png", bit_depth=8,
        history={},
    )
    assert est.frame_time_sec == pytest.approx(DEFAULT_FRAME_TIME_SEC)
    assert est.total_frames == 600
    assert est.total_seconds == pytest.approx(DEFAULT_FRAME_TIME_SEC * 600)
    assert est.output_bytes > 0
    assert est.history_hit is False


def test_estimate_render_uses_history_when_available():
    history = {"auroras::1920x1080": {"mean_frame_time": 0.5}}
    est = estimate_render(
        shader_basename="auroras",
        width=1920, height=1080,
        fps=30, duration_sec=10.0,
        tile_count=1, ss_scale=1.0,
        format="png", bit_depth=8,
        history=history,
    )
    assert est.frame_time_sec == pytest.approx(0.5)
    assert est.total_seconds == pytest.approx(0.5 * 300)
    assert est.history_hit is True


def test_estimate_render_scales_by_tile_count_and_ss():
    history = {"auroras::1920x1080": {"mean_frame_time": 1.0}}
    base = estimate_render(shader_basename="auroras", width=1920, height=1080,
                           fps=60, duration_sec=1.0, tile_count=1, ss_scale=1.0,
                           format="png", bit_depth=8, history=history)
    tiled = estimate_render(shader_basename="auroras", width=1920, height=1080,
                            fps=60, duration_sec=1.0, tile_count=4, ss_scale=2.0,
                            format="png", bit_depth=8, history=history)
    assert tiled.frame_time_sec == pytest.approx(base.frame_time_sec * 16)


def test_estimate_exceeds_thresholds():
    est = RenderEstimate(
        frame_time_sec=10.0, total_frames=600, total_seconds=6000.0,
        output_bytes=200 * 1024**3, history_hit=False,
    )
    assert est.exceeds_time_threshold(3600)
    assert est.exceeds_size_threshold(50 * 1024**3)
    assert not est.exceeds_time_threshold(6001)


def test_record_history_ema(tmp_path):
    from cedartoy.render_estimate import load_history, record_history, estimate_render
    p = tmp_path / "history.json"

    record_history(shader_basename="auroras", width=1920, height=1080,
                   mean_frame_time=10.0, path=p)
    record_history(shader_basename="auroras", width=1920, height=1080,
                   mean_frame_time=20.0, path=p)

    history = load_history(p)
    # EMA with alpha=0.3: 0.7*10 + 0.3*20 = 13.0
    assert history["auroras::1920x1080"]["mean_frame_time"] == pytest.approx(13.0)

    est = estimate_render(
        shader_basename="auroras", width=1920, height=1080,
        fps=60, duration_sec=10.0, tile_count=1, ss_scale=1.0,
        format="png", bit_depth=8, history=history,
    )
    assert est.frame_time_sec == pytest.approx(13.0)
    assert est.history_hit is True


def test_load_history_missing_returns_empty(tmp_path):
    from cedartoy.render_estimate import load_history
    assert load_history(tmp_path / "nope.json") == {}
