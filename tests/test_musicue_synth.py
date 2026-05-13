import numpy as np
import pytest

from cedartoy.musicue import EvalFrame, MusicalSpectrumSynth


def test_shape_and_dtype():
    tex = MusicalSpectrumSynth().synthesize(EvalFrame())
    assert tex.shape == (2, 512)
    assert tex.dtype == np.float32


def test_kick_drives_low_bins():
    tex = MusicalSpectrumSynth().synthesize(EvalFrame(drum_pulses={"kick": 1.0}))
    assert tex[0, 0:32].max() > 0.5
    assert tex[0, 96:256].max() < 0.1


def test_snare_and_tom_drive_low_mid():
    tex = MusicalSpectrumSynth().synthesize(
        EvalFrame(drum_pulses={"snare": 0.7, "tom": 0.3})
    )
    assert tex[0, 32:96].max() > 0.5


def test_hat_and_cymbal_drive_mid_high():
    tex = MusicalSpectrumSynth().synthesize(
        EvalFrame(drum_pulses={"hat": 0.6, "cymbal": 0.5})
    )
    assert tex[0, 96:256].max() > 0.5
    assert tex[0, 0:32].max() < 0.1


def test_midi_drives_high_bins():
    tex = MusicalSpectrumSynth().synthesize(
        EvalFrame(midi_energy={"vocals": 0.8, "other": 0.2})
    )
    assert tex[0, 256:512].max() > 0.5
    assert tex[0, 0:96].max() < 0.1


def test_section_energy_baseline_tilt():
    quiet = MusicalSpectrumSynth().synthesize(EvalFrame())
    loud = MusicalSpectrumSynth().synthesize(EvalFrame(section_energy=0.8))
    assert loud[0].mean() > quiet[0].mean()
    assert loud[0].mean() == pytest.approx(0.08, abs=0.02)


def test_waveform_row_locked_to_beat_phase():
    at_zero = MusicalSpectrumSynth().synthesize(
        EvalFrame(beat_phase=0.0, global_energy=1.0)
    )
    quarter = MusicalSpectrumSynth().synthesize(
        EvalFrame(beat_phase=0.25, global_energy=1.0)
    )
    assert at_zero[1].mean() == pytest.approx(0.5, abs=0.01)
    assert quarter[1].mean() == pytest.approx(1.0, abs=0.01)


def test_clamped_to_unit_range():
    saturated = EvalFrame(
        drum_pulses={"kick": 1.0, "snare": 1.0, "tom": 1.0, "hat": 1.0, "cymbal": 1.0},
        midi_energy={"vocals": 1.0, "other": 1.0},
        section_energy=1.0, global_energy=1.0,
    )
    tex = MusicalSpectrumSynth().synthesize(saturated)
    assert tex.min() >= 0.0
    assert tex.max() <= 1.0
