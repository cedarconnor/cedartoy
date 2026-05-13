import numpy as np
import pytest

from cedartoy.musicue import EvalFrame
from cedartoy.render import _builtin_uniforms_from_eval, _mix_audio_textures


def test_mix_raw_only():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="raw", blend=0.5), 0.2)


def test_mix_cued_only():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="cued", blend=0.5), 0.8)


def test_mix_blend_50_50():
    raw = np.full((2, 512), 0.2, dtype=np.float32)
    cued = np.full((2, 512), 0.8, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="blend", blend=0.5), 0.5)


def test_mix_blend_weighted():
    raw = np.full((2, 512), 0.0, dtype=np.float32)
    cued = np.full((2, 512), 1.0, dtype=np.float32)
    assert np.allclose(_mix_audio_textures(raw, cued, mode="blend", blend=0.25), 0.25)


def test_builtin_uniforms_from_eval_frame():
    frame = EvalFrame(bpm=128.0, beat_phase=0.25, bar=3,
                      section_energy=0.7, global_energy=0.6)
    uni = _builtin_uniforms_from_eval(frame)
    assert uni["iBpm"] == pytest.approx(128.0)
    assert uni["iBeat"] == pytest.approx(0.25)
    assert uni["iBar"] == 3
    assert uni["iSectionEnergy"] == pytest.approx(0.7)
    assert uni["iEnergy"] == pytest.approx(0.6)


def test_builtin_uniforms_none_returns_defaults():
    uni = _builtin_uniforms_from_eval(None)
    assert uni == {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0, "iSectionEnergy": 0.0, "iEnergy": 0.0}
