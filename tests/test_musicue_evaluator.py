import pytest

from cedartoy.musicue import (
    BeatEvent,
    BundleEvaluator,
    EvalFrame,
    MusiCueBundle,
    StemEnergyCurve,
    TempoInfo,
)


def _bundle(*, beats=None, tempo_bpm=120.0, duration=4.0) -> MusiCueBundle:
    return MusiCueBundle(
        schema_version="1.0",
        source_sha256="x" * 64,
        duration_sec=duration,
        fps=24.0,
        tempo=TempoInfo(bpm_global=tempo_bpm),
        beats=beats or [],
        global_energy=StemEnergyCurve(hop_sec=0.04, values=[]),
        cuesheet={},
    )


def test_bpm_from_global():
    ev = BundleEvaluator(_bundle(tempo_bpm=128.0), fps=24.0)
    assert ev.evaluate(0).bpm == pytest.approx(128.0)


def test_beat_phase_advances_linearly():
    beats = [
        BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
        BeatEvent(t=0.5, beat_in_bar=1, bar=0, is_downbeat=False),
        BeatEvent(t=1.0, beat_in_bar=2, bar=0, is_downbeat=False),
    ]
    ev = BundleEvaluator(_bundle(beats=beats), fps=24.0)
    assert ev.evaluate(int(round(0.25 * 24.0))).beat_phase == pytest.approx(0.5, abs=0.05)


def test_bar_from_downbeats():
    beats = [
        BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
        BeatEvent(t=2.0, beat_in_bar=0, bar=1, is_downbeat=True),
    ]
    ev = BundleEvaluator(_bundle(beats=beats), fps=24.0)
    assert ev.evaluate(int(round(0.5 * 24.0))).bar == 0
    assert ev.evaluate(int(round(2.5 * 24.0))).bar == 1


def test_bar_fallback_when_no_downbeats():
    ev = BundleEvaluator(_bundle(tempo_bpm=120.0), fps=24.0)
    assert ev.evaluate(int(round(0.0 * 24.0))).bar == 0
    assert ev.evaluate(int(round(2.5 * 24.0))).bar == 1


def test_empty_bundle_returns_zero_phase():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    frame = ev.evaluate(0)
    assert frame.beat_phase == 0.0
    assert frame.bar == 0
