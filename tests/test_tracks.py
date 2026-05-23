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


from cedartoy.musicue import (
    build_track_timeline, bundle_health, MusiCueBundle, TempoInfo,
    BeatEvent, SectionBundleEntry, DrumOnset, StemEnergyCurve,
)


def _bundle():
    return MusiCueBundle(
        schema_version="1.0", source_sha256="x", duration_sec=4.0, fps=24.0,
        tempo=TempoInfo(bpm_global=120.0, time_signature=[4, 4]),
        beats=[BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
               BeatEvent(t=0.5, beat_in_bar=1, bar=0, is_downbeat=False)],
        sections=[SectionBundleEntry(start=0.0, end=2.0, label="verse",
                                     energy_rank=0.3),
                  SectionBundleEntry(start=2.0, end=4.0, label="chorus",
                                     energy_rank=0.9)],
        drums={"kick": [DrumOnset(t=0.0, strength=0.9),
                        DrumOnset(t=1.0, strength=0.7)],
               "hat": []},
        midi={}, midi_energy={"vocals": StemEnergyCurve(hop_sec=0.5,
                                                        values=[0.1, 0.2, 0.3])},
        stems_energy={},
        global_energy=StemEnergyCurve(hop_sec=0.5, values=[0.2, 0.4]),
        cuesheet={},
    )


def test_build_track_timeline_shape():
    tl = build_track_timeline(_bundle(), fps=24.0)
    assert tl["fps"] == 24.0 and tl["duration_sec"] == 4.0
    assert tl["bands"] == ["low", "low_mid", "mid_hi", "high"]
    assert tl["tracks"]["drums.kick"]["band"] == "low"
    assert len(tl["tracks"]["drums.kick"]["onsets"]) == 2
    assert tl["tracks"]["drums.kick"]["onsets"][0] == {"t": 0.0, "strength": 0.9}
    assert tl["tracks"]["stem.vocals"]["curve"]["values"] == [0.1, 0.2, 0.3]
    assert tl["tracks"]["sections"]["blocks"][1]["label"] == "chorus"
    assert tl["tracks"]["tempo"]["bpm"] == 120.0


def test_bundle_health_flags_empty_fields():
    h = bundle_health(_bundle())
    assert h["beats"] == {"present": True, "count": 2}
    assert h["sections"] == {"present": True, "count": 2}
    assert h["drums"]["kick"] == 2
    assert h["drums"]["hat"] == 0
    assert h["midi_energy"]["vocals"] is True
    assert h["midi_energy"].get("bass", False) is False
    assert h["stems_energy"]["present"] is False


def test_timeline_includes_per_frame_arrays():
    b = _bundle()                      # duration 4.0s, fps 24 -> 96 frames
    tl = build_track_timeline(b, fps=24.0)
    n = tl["frames"]
    assert n == 96
    fr = tl["frame_data"]
    # band tracks each carry an n-length scalar array
    assert len(fr["tracks"]["drums.kick"]) == n
    assert len(fr["tracks"]["stem.vocals"]) == n
    # uniform series present and n-length
    for key in ("bpm", "beat", "bar", "sectionEnergy", "sectionId", "energy"):
        assert len(fr["uniforms"][key]) == n
    # kick fires at t=0 (frame 0) with strength ~0.9 (ADSR peak)
    assert fr["tracks"]["drums.kick"][0] > 0.5


def test_timeline_frame_scalars_match_evaluator():
    from cedartoy.musicue import BundleEvaluator
    b = _bundle()
    tl = build_track_timeline(b, fps=24.0)
    ev = BundleEvaluator(b, fps=24.0)
    f10 = ev.evaluate(10)
    assert abs(tl["frame_data"]["tracks"]["drums.kick"][10]
               - f10.drum_pulses.get("kick", 0.0)) < 1e-6
    assert abs(tl["frame_data"]["uniforms"]["energy"][10]
               - f10.global_energy) < 1e-6


def test_frame_data_composes_to_synth_output():
    from cedartoy.musicue import (
        MusicalSpectrumSynth, EvalFrame, BAND_TRACKS, _BIN_RANGES,
        _hann_envelope, apply_setting,
    )
    b = _bundle()
    tl = build_track_timeline(b, fps=24.0)
    fr = tl["frame_data"]
    synth = MusicalSpectrumSynth()
    settings = {"drums.kick": {"gain": 0.5}, "stem.vocals": {"mute": True}}
    envelopes = {n: _hann_envelope(e - s) for n, (s, e) in _BIN_RANGES.items()}

    for f in (0, 5, 10, 40):
        # Compose row0 the way the browser will: sum band-filled scalars.
        row0 = np.zeros(512, dtype=np.float32)
        for tid, band in BAND_TRACKS.items():
            v = apply_setting(fr["tracks"][tid][f], settings.get(tid))
            s, e = _BIN_RANGES[band]
            if v > 0:
                row0[s:e] += envelopes[band] * v
        row0 += 0.1 * fr["uniforms"]["sectionEnergy"][f]
        np.clip(row0, 0.0, 1.0, out=row0)

        # Reference: the canonical synth for the same frame + settings.
        ev_frame = EvalFrame(
            section_energy=fr["uniforms"]["sectionEnergy"][f],
            drum_pulses={k.split(".")[1]: fr["tracks"][k][f]
                         for k in BAND_TRACKS if k.startswith("drums.")},
            midi_energy={k.split(".")[1]: fr["tracks"][k][f]
                         for k in BAND_TRACKS if k.startswith("stem.")},
        )
        ref = synth.synthesize(ev_frame, settings)
        assert np.allclose(row0, ref[0], atol=1e-6)
