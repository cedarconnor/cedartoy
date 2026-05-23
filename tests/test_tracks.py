from cedartoy.musicue import (
    ALL_TRACK_IDS, BAND_TRACKS, UNIFORM_TRACKS, apply_setting,
)


def test_track_id_inventory():
    assert BAND_TRACKS["drums.kick"] == "low"
    assert BAND_TRACKS["drums.snare"] == "low_mid"
    assert BAND_TRACKS["drums.tom"] == "low_mid"
    assert BAND_TRACKS["drums.hat"] == "mid_hi"
    assert BAND_TRACKS["drums.cymbal"] == "mid_hi"
    assert BAND_TRACKS["drums.other"] == "mid_hi"
    assert BAND_TRACKS["stem.vocals"] == "high"
    assert BAND_TRACKS["stem.other"] == "high"
    assert BAND_TRACKS["stem.bass"] == "high"
    assert UNIFORM_TRACKS == {"tempo", "sections", "energy"}
    # ALL = band + uniform, no duplicates
    assert set(ALL_TRACK_IDS) == set(BAND_TRACKS) | UNIFORM_TRACKS
    assert len(ALL_TRACK_IDS) == len(set(ALL_TRACK_IDS))


def test_apply_setting_threshold_gain_mute():
    assert apply_setting(0.8, None) == 0.8                       # no setting = pass-through
    assert apply_setting(0.8, {"mute": True}) == 0.0             # mute wins
    assert apply_setting(0.8, {"gain": 2.0}) == 1.6              # gain scales
    assert apply_setting(0.05, {"threshold": 0.1}) == 0.0        # below threshold floored
    # threshold subtracts, then gain: (0.8 - 0.1) * 2.0 = 1.4
    assert abs(apply_setting(0.8, {"threshold": 0.1, "gain": 2.0}) - 1.4) < 1e-6


import numpy as np
from cedartoy.musicue import MusicalSpectrumSynth, EvalFrame


def _frame():
    return EvalFrame(
        section_energy=0.4, global_energy=0.5, beat_phase=0.25,
        drum_pulses={"kick": 0.9, "snare": 0.3, "tom": 0.2,
                     "hat": 0.6, "cymbal": 0.1, "other": 0.05},
        midi_energy={"vocals": 0.7, "other": 0.2, "bass": 0.4},
    )


def test_band_contributions_sum_to_synth_output():
    """The select-and-sum model the JS client will use must equal the synth."""
    synth = MusicalSpectrumSynth()
    frame = _frame()

    full = synth.synthesize(frame, settings=None)              # canonical texture

    # Sum per-track contributions + the section_energy floor, same as synth.
    contrib = synth.track_band_contributions(frame, settings=None)
    summed = np.zeros((2, 512), dtype=np.float32)
    for row in contrib.values():
        summed[0] += row
    summed[0] += 0.1 * frame.section_energy
    np.clip(summed[0], 0.0, 1.0, out=summed[0])
    summed[1, :] = full[1, :]   # row 1 (heartbeat) is not per-track

    assert np.allclose(full, summed, atol=1e-6)


def test_muting_kick_removes_low_band():
    synth = MusicalSpectrumSynth()
    frame = _frame()
    muted = synth.synthesize(frame, settings={"drums.kick": {"mute": True}})
    # low band (bins 0:32) must be only the section_energy floor (0.04), no kick
    assert muted[0, 16] <= 0.1 + 1e-6
    full = synth.synthesize(frame, settings=None)
    assert full[0, 16] > muted[0, 16]   # kick contributed before muting


def test_gain_boosts_band():
    synth = MusicalSpectrumSynth()
    frame = _frame()
    base = synth.synthesize(frame, settings=None)
    boosted = synth.synthesize(frame, settings={"stem.vocals": {"gain": 1.5}})
    # high band (bins 256:512) grows with vocal gain (pre-clip headroom assumed)
    assert boosted[0, 300] >= base[0, 300]


from cedartoy.musicue import masked_builtin_uniforms


def test_masked_uniforms_passthrough_and_mute():
    frame = EvalFrame(bpm=128.0, beat_phase=0.5, bar=3,
                      section_energy=0.4, section_id=2, global_energy=0.5)

    u = masked_builtin_uniforms(frame, settings=None)
    assert u == {"iBpm": 128.0, "iBeat": 0.5, "iBar": 3,
                 "iSectionEnergy": 0.4, "iSectionId": 2, "iEnergy": 0.5}

    # muting tempo zeroes bpm/beat/bar (closes the step(1.0,iBpm) gate)
    u = masked_builtin_uniforms(frame, settings={"tempo": {"mute": True}})
    assert u["iBpm"] == 0.0 and u["iBeat"] == 0.0 and u["iBar"] == 0
    assert u["iEnergy"] == 0.5   # other tracks unaffected

    # muting energy zeroes iEnergy; muting sections zeroes section uniforms
    u = masked_builtin_uniforms(frame, settings={"energy": {"mute": True},
                                                 "sections": {"mute": True}})
    assert u["iEnergy"] == 0.0
    assert u["iSectionEnergy"] == 0.0 and u["iSectionId"] == 0


def test_masked_uniforms_none_frame():
    u = masked_builtin_uniforms(None, settings={"tempo": {"mute": True}})
    assert u == {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0,
                 "iSectionEnergy": 0.0, "iSectionId": 0, "iEnergy": 0.0}
