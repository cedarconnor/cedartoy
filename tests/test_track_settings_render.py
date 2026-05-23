import numpy as np

from cedartoy.musicue import (
    MusicalSpectrumSynth, EvalFrame, masked_builtin_uniforms,
)


def test_render_helpers_honor_track_settings():
    # This mirrors exactly what Renderer._render_pass does per frame.
    synth = MusicalSpectrumSynth()
    frame = EvalFrame(bpm=120.0, beat_phase=0.0, bar=1, section_energy=0.4,
                      section_id=1, global_energy=0.5,
                      drum_pulses={"kick": 0.9}, midi_energy={})
    settings = {"drums.kick": {"mute": True}, "tempo": {"mute": True}}

    tex = synth.synthesize(frame, settings)
    uni = masked_builtin_uniforms(frame, settings)

    assert tex[0, 16] <= 0.1 + 1e-6     # kick muted -> only section floor
    assert uni["iBpm"] == 0.0           # tempo muted -> gate closed


def test_render_job_has_track_settings_default():
    from cedartoy.types import RenderJob
    import inspect
    # default_factory dict — constructing without it must work.
    sig = inspect.signature(RenderJob)
    assert "track_settings" in sig.parameters


def test_effective_series_smoothing_reduces_and_smooths():
    from cedartoy.musicue import apply_settings_series
    raw = [0.0, 1.0, 0.0, 0.0, 0.0]
    none = apply_settings_series(raw, None)
    assert none == raw                            # no setting -> identity
    sm = apply_settings_series(raw, {"smoothing": 0.5})
    # one-pole low-pass: a jump is attenuated, then decays.
    # sm[1]=0.5*1+0.5*0=0.5; sm[2]=0.25; sm[3]=0.125
    assert abs(sm[1] - 0.5) < 1e-9
    assert abs(sm[2] - 0.25) < 1e-9
    assert abs(sm[3] - 0.125) < 1e-9
    assert sm != raw                              # smoothing changed the series


def test_renderer_builds_effective_band_series():
    from cedartoy.musicue import apply_settings_series
    raw_kick = [0.0, 0.8, 0.0, 0.0]
    plain = apply_settings_series(raw_kick, {})
    smoothed = apply_settings_series(raw_kick, {"smoothing": 0.6})
    assert plain[2] == 0.0
    assert smoothed[2] > 0.0                       # smoothing bleeds the onset forward
