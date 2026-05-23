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
