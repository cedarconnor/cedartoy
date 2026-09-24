"""Shadertoy/WebAudio-style audio texture (row 0 spectrum, row 1 waveform)."""
import numpy as np
import pytest

sf = pytest.importorskip("soundfile")

from cedartoy.audio import (
    AudioProcessor,
    magnitudes_to_unit,
    smooth_magnitudes,
    smoothing_tau_for_fps,
    smoothing_warmup_frames,
)

SR = 44100


def _processor(tmp_path, signal, fps=30.0, name="a.wav"):
    path = tmp_path / name
    sf.write(str(path), signal, SR)
    return AudioProcessor(path, fps)


def _tone(amp, freq=1000.0, seconds=2.0):
    t = np.arange(int(SR * seconds)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def test_silence_is_zero_spectrum_and_centred_waveform(tmp_path):
    ap = _processor(tmp_path, np.zeros(SR * 2))
    tex = ap.get_shadertoy_texture(20)
    assert tex.shape == (2, 512)
    assert np.all(tex[0] == 0.0)
    assert np.allclose(tex[1], 0.5)


def test_loudness_is_preserved(tmp_path):
    quiet = _processor(tmp_path, _tone(0.001), name="q.wav").get_shadertoy_texture(30)
    loud = _processor(tmp_path, _tone(0.05), name="l.wav").get_shadertoy_texture(30)
    # Same frequency peak (1 kHz -> bin ~46 at 2048-pt FFT)...
    assert abs(int(np.argmax(quiet[0])) - 46) <= 1
    assert abs(int(np.argmax(loud[0])) - 46) <= 1
    # ...but no per-frame normalisation: louder tone -> higher value.
    assert loud[0].max() > quiet[0].max() + 0.1
    assert quiet[0].max() < 1.0


def test_first_512_bins_cover_about_11khz(tmp_path):
    ap = _processor(tmp_path, _tone(0.01, freq=10000.0))
    tex = ap.get_shadertoy_texture(30)
    assert abs(int(np.argmax(tex[0])) - round(10000 / (SR / 2048))) <= 1


def test_smoothing_decays_after_sound_stops(tmp_path):
    sig = np.concatenate([_tone(0.05, seconds=1.0), np.zeros(SR)])
    ap = _processor(tmp_path, sig)
    peak_on = ap.get_shadertoy_texture(25)[0].max()
    after = [ap.get_shadertoy_texture(f)[0].max() for f in (32, 33, 34)]
    assert peak_on > after[0] > after[1] > after[2] > 0.0


def test_uncached_frame_matches_sequential(tmp_path):
    ap = _processor(tmp_path, _tone(0.02))
    cached = ap.get_shadertoy_texture(40).copy()
    del ap._precomputed_textures[40]
    np.testing.assert_allclose(ap.get_shadertoy_texture(40), cached, atol=1e-3)


def test_waveform_row_is_512_consecutive_samples(tmp_path):
    ramp = np.linspace(-0.5, 0.5, SR * 2)
    ap = _processor(tmp_path, ramp)
    row = ap.get_shadertoy_texture(30)[1]
    diffs = np.diff(row.astype(np.float64))
    step = 0.5 * (1.0 / (SR * 2 - 1))
    assert np.allclose(diffs, step, atol=1e-4)


def test_helpers():
    assert smoothing_tau_for_fps(60.0) == pytest.approx(0.8)
    assert smoothing_tau_for_fps(30.0) == pytest.approx(0.64)
    m = np.array([1e-6, 10 ** (-65 / 20), 1.0])
    np.testing.assert_allclose(magnitudes_to_unit(m), [0.0, 0.5, 1.0], atol=1e-6)
    np.testing.assert_allclose(
        smooth_magnitudes(np.ones(3), np.zeros(3), 0.8), np.full(3, 0.2))


@pytest.mark.parametrize("fps", [24.0, 60.0, 240.0])
def test_warmup_scales_with_fps(fps):
    n = smoothing_warmup_frames(fps)
    assert smoothing_tau_for_fps(fps) ** n < 1e-3
    # Constant ~0.5 s of audio history regardless of render rate.
    assert 0.3 < n / fps < 0.7


def test_uncached_frame_matches_sequential_at_high_fps(tmp_path):
    sig = np.concatenate([_tone(0.5, seconds=0.5), np.zeros(SR)])
    ap = _processor(tmp_path, sig, fps=240.0)
    frame = int(0.5 * 240) + 40  # 40 frames into the decay tail
    cached = ap.get_shadertoy_texture(frame).copy()
    del ap._precomputed_textures[frame]
    np.testing.assert_allclose(ap.get_shadertoy_texture(frame), cached, atol=1e-3)
