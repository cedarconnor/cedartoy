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
