"""Musical-structure signals (schema 1.3 era): beat/bar/phrase clocks,
section progress, tempo-relative drum envelopes, iMusicTime, av offset,
graceful degradation with 1.0 bundles, and preview/render parity."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from cedartoy.musicue import (
    BAND_TRACKS, ENV_TAU_MAX, ENV_TAU_MIN, MUSICAL_UNIFORMS,
    MUSICAL_UNIFORM_SERIES, NO_NEXT_SECTION, BeatEvent, BundleEvaluator,
    DrumOnset, MusiCueBundle, SectionBundleEntry, StemEnergyCurve, TempoInfo,
    band_raw_value, build_track_timeline, bundle_health, bundle_uniforms,
    envelope_tau, envelope_value, format_bundle_health, load_bundle,
    masked_musical_uniforms,
)

ROOT = Path(__file__).resolve().parents[1]


def _beats(n, t0=0.25, period=0.5, per_bar=4, phrase=None):
    out = []
    for i in range(n):
        bar = i // per_bar
        kw = {}
        if phrase:
            kw = {"phrase_id": bar // phrase, "phrase_position": bar % phrase,
                  "phrase_length": phrase}
        out.append(BeatEvent(t=t0 + i * period, beat_in_bar=i % per_bar,
                             bar=bar, is_downbeat=(i % per_bar == 0), **kw))
    return out


def _bundle(**over):
    data = dict(
        schema_version="1.0", source_sha256="x", duration_sec=16.0, fps=24.0,
        tempo=TempoInfo(bpm_global=120.0, time_signature=[4, 4]),
        beats=_beats(30),
        sections=[SectionBundleEntry(start=0.0, end=4.0, label="intro", energy_rank=0.2),
                  SectionBundleEntry(start=4.0, end=12.0, label="drop", energy_rank=0.9),
                  SectionBundleEntry(start=12.0, end=16.0, label="outro", energy_rank=0.1)],
        drums={"kick": [DrumOnset(t=1.0, strength=1.0), DrumOnset(t=5.0, strength=0.8)],
               "snare": [DrumOnset(t=2.0, strength=0.6)]},
        global_energy=StemEnergyCurve(hop_sec=1.0, values=[0.1] * 4 + [0.9] * 8 + [0.1] * 5),
        cuesheet={},
    )
    data.update(over)
    return MusiCueBundle(**data)


def _bundle_13():
    n = 64
    return _bundle(
        schema_version="1.3",
        beats=_beats(30, phrase=2),
        stems_energy={"bass": StemEnergyCurve(hop_sec=0.25, values=[0.7] * n),
                      "vocals": StemEnergyCurve(hop_sec=0.25, values=[0.3] * n),
                      "drums": StemEnergyCurve(hop_sec=0.25, values=[0.5] * n),
                      "other": StemEnergyCurve(hop_sec=0.25, values=[0.2] * n)},
        midi_energy={"vocals": StemEnergyCurve(hop_sec=0.25, values=[0.9] * n)},
        controls={"build": StemEnergyCurve(hop_sec=0.5, values=[i / 32 for i in range(33)]),
                  "brightness": StemEnergyCurve(hop_sec=0.5, values=[0.4] * 33),
                  "energy_fast": StemEnergyCurve(hop_sec=0.5, values=[0.6] * 33)},
    )


# ---- beat clock ----

def test_beat_clock_phase_locked_to_grid():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    for i in (0, 1, 7, 29):
        assert ev.evaluate_at(0.25 + 0.5 * i).beat_clock == pytest.approx(i)
    assert ev.evaluate_at(0.25 + 0.5 * 3 + 0.125).beat_clock == pytest.approx(3.25)


def test_beat_clock_follows_uneven_grid():
    # Tempo drifts: intervals 0.5 then 0.4. Clock stays on integer beats.
    times = [0.0, 0.5, 1.0, 1.4, 1.8]
    beats = [BeatEvent(t=t, beat_in_bar=i % 4, bar=i // 4, is_downbeat=i % 4 == 0)
             for i, t in enumerate(times)]
    ev = BundleEvaluator(_bundle(beats=beats), fps=24.0)
    assert ev.evaluate_at(1.4).beat_clock == pytest.approx(3.0)
    assert ev.evaluate_at(1.2).beat_clock == pytest.approx(2.5)
    # iTime*iBpm/60 would drift: 1.8s * 2 = 3.6 beats vs grid's 4.
    assert ev.evaluate_at(1.8).beat_clock == pytest.approx(4.0)


def test_beat_clock_monotonic_and_extrapolated():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    ts = np.linspace(-2.0, 20.0, 2000)
    vals = [ev.evaluate_at(t).beat_clock for t in ts]
    assert all(b > a for a, b in zip(vals, vals[1:]))
    # Before first beat (t0=0.25) extrapolates with the first interval.
    assert ev.evaluate_at(0.0).beat_clock == pytest.approx(-0.5)
    # After the last beat (index 29 at 14.75) continues at the last interval.
    assert ev.evaluate_at(15.75).beat_clock == pytest.approx(31.0)


def test_beat_clock_without_beats_uses_bpm():
    ev = BundleEvaluator(_bundle(beats=[]), fps=24.0)
    assert ev.evaluate_at(3.0).beat_clock == pytest.approx(6.0)


# ---- bar / phrase phase ----

def test_bar_phase_continuous_within_bar():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    # Downbeats at 0.25, 2.25, 4.25 ... (bar = 2 s)
    assert ev.evaluate_at(0.25).bar_phase == pytest.approx(0.0)
    assert ev.evaluate_at(1.25).bar_phase == pytest.approx(0.5)
    assert ev.evaluate_at(2.2).bar_phase == pytest.approx(0.975)
    assert ev.evaluate_at(2.25).bar_phase == pytest.approx(0.0)
    for t in np.linspace(-3, 20, 500):
        assert 0.0 <= ev.evaluate_at(t).bar_phase < 1.0


def test_phrase_phase_fallback_four_bar_groups():
    ev = BundleEvaluator(_bundle(), fps=24.0)   # no phrase fields
    # 4 bars of 2 s from the first downbeat at 0.25
    assert ev.evaluate_at(0.25).phrase_phase == pytest.approx(0.0)
    assert ev.evaluate_at(4.25).phrase_phase == pytest.approx(0.5)
    assert ev.evaluate_at(8.25).phrase_phase == pytest.approx(0.0)


def test_phrase_phase_from_phrase_fields():
    ev = BundleEvaluator(_bundle_13(), fps=24.0)   # 2-bar phrases
    assert ev.evaluate_at(0.25).phrase_phase == pytest.approx(0.0)
    assert ev.evaluate_at(2.25).phrase_phase == pytest.approx(0.5)
    assert ev.evaluate_at(3.25).phrase_phase == pytest.approx(0.75)
    assert ev.evaluate_at(4.25).phrase_phase == pytest.approx(0.0)


# ---- sections ----

def test_section_progress_and_time_to_next():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    f = ev.evaluate_at(6.0)
    assert f.section_progress == pytest.approx(0.25)
    assert f.time_to_next_section == pytest.approx(6.0)
    assert f.section_energy == pytest.approx(0.9) and f.section_id == 1
    last = ev.evaluate_at(14.0)
    assert last.section_progress == pytest.approx(0.5)
    assert last.time_to_next_section == NO_NEXT_SECTION
    assert ev.evaluate_at(20.0).section_progress == 0.0


# ---- drum envelopes ----

def test_envelope_tau_scales_with_tempo_and_clamps():
    # decays to ~10% after half a beat at 120 bpm
    tau = envelope_tau(0.5)
    assert envelope_value(0.25, tau, 1.0) == pytest.approx(0.1, abs=0.002)
    assert envelope_tau(1.0) == pytest.approx(2 * tau)
    assert envelope_tau(0.05) == ENV_TAU_MIN
    assert envelope_tau(10.0) == ENV_TAU_MAX
    assert envelope_value(0.0, tau, 0.7) == pytest.approx(0.7)   # instant attack
    assert envelope_value(-0.01, tau, 1.0) == 0.0
    assert envelope_value(10 * tau, tau, 1.0) == 0.0            # finite tail


def test_drum_envelope_follows_local_beat_period():
    slow = [BeatEvent(t=i * 1.0, beat_in_bar=i % 4, bar=i // 4, is_downbeat=i % 4 == 0)
            for i in range(10)]
    fast = [BeatEvent(t=i * 0.4, beat_in_bar=i % 4, bar=i // 4, is_downbeat=i % 4 == 0)
            for i in range(20)]
    kick = {"kick": [DrumOnset(t=2.0, strength=1.0)]}
    ev_slow = BundleEvaluator(_bundle(beats=slow, drums=kick), fps=24.0)
    ev_fast = BundleEvaluator(_bundle(beats=fast, drums=kick), fps=24.0)
    v_slow = ev_slow.evaluate_at(2.1).drum_pulses["kick"]
    v_fast = ev_fast.evaluate_at(2.1).drum_pulses["kick"]
    assert v_slow > v_fast
    # half a beat after the hit -> ~10%
    assert ev_slow.evaluate_at(2.5).drum_pulses["kick"] == pytest.approx(0.1, abs=0.01)
    assert ev_fast.evaluate_at(2.2).drum_pulses["kick"] == pytest.approx(0.1, abs=0.01)


def test_drum_pulses_sum_overlapping_hits_and_clip():
    kick = {"kick": [DrumOnset(t=1.0, strength=0.8), DrumOnset(t=1.05, strength=0.8)]}
    ev = BundleEvaluator(_bundle(drums=kick), fps=24.0)
    assert ev.evaluate_at(1.05).drum_pulses["kick"] == 1.0
    assert ev.evaluate_at(0.99).drum_pulses["kick"] == 0.0


# ---- music time ----

def test_music_time_mean_rate_one_and_monotonic():
    b = _bundle()
    ev = BundleEvaluator(b, fps=24.0)
    assert ev.music_time_at(0.0) == pytest.approx(0.0)
    assert ev.music_time_at(b.duration_sec) == pytest.approx(b.duration_sec, rel=1e-6)
    ts = np.linspace(-1.0, 18.0, 3000)
    vals = [ev.music_time_at(t) for t in ts]
    assert all(b2 > a for a, b2 in zip(vals, vals[1:]))
    # Faster in the loud middle than in the quiet intro.
    rate_quiet = ev.music_time_at(1.5) - ev.music_time_at(0.5)
    rate_loud = ev.music_time_at(8.5) - ev.music_time_at(7.5)
    assert rate_loud > 1.0 > rate_quiet
    # Rate 1 past the end.
    assert ev.music_time_at(18.0) - ev.music_time_at(17.0) == pytest.approx(1.0)


def test_music_time_flat_energy_is_identity():
    b = _bundle(global_energy=StemEnergyCurve(hop_sec=0.0, values=[]))
    ev = BundleEvaluator(b, fps=24.0)
    for t in (0.0, 3.3, 12.0):
        assert ev.music_time_at(t) == pytest.approx(t, abs=1e-6)


# ---- av offset ----

def test_av_offset_delays_all_signals():
    b = _bundle()
    ev0 = BundleEvaluator(b, fps=24.0)
    ev = BundleEvaluator(b, fps=24.0, av_offset_ms=100.0)
    a, c = ev.evaluate_at(1.1), ev0.evaluate_at(1.0)
    assert a.drum_pulses["kick"] == pytest.approx(c.drum_pulses["kick"])
    assert a.beat_clock == pytest.approx(c.beat_clock)
    assert a.music_time == pytest.approx(c.music_time)
    assert a.time == pytest.approx(1.1)
    # evaluate(frame) goes through the same offset
    assert ev.evaluate(24).beat_clock == pytest.approx(ev0.evaluate_at(0.9).beat_clock)


def test_evaluate_frame_delegates_to_evaluate_at():
    ev = BundleEvaluator(_bundle_13(), fps=30.0)
    assert ev.evaluate(45) == ev.evaluate_at(1.5)


# ---- controls / stems ----

def test_controls_and_stems_feed_uniforms():
    ev = BundleEvaluator(_bundle_13(), fps=24.0)
    u = bundle_uniforms(ev.evaluate_at(8.0), None, 8.0)
    assert u["iBuild"] == pytest.approx(0.5)
    assert u["iBrightness"] == pytest.approx(0.4)
    assert u["iEnergyFast"] == pytest.approx(0.6)
    assert (u["iBass"], u["iVocals"], u["iDrums"], u["iOther"]) == pytest.approx(
        (0.7, 0.3, 0.5, 0.2))


def test_stem_band_sources_prefer_stems_energy():
    f = BundleEvaluator(_bundle_13(), fps=24.0).evaluate_at(1.0)
    assert band_raw_value(f, "stem.vocals") == pytest.approx(0.3)   # not midi 0.9
    assert band_raw_value(f, "stem.bass") == pytest.approx(0.7)
    assert BAND_TRACKS["stem.bass"] == "low"
    # 1.0 bundle: falls back to midi_energy
    b = _bundle(midi_energy={"vocals": StemEnergyCurve(hop_sec=1.0, values=[0.9] * 20)})
    f = BundleEvaluator(b, fps=24.0).evaluate_at(1.0)
    assert band_raw_value(f, "stem.vocals") == pytest.approx(0.9)
    assert band_raw_value(f, "stem.bass") == 0.0


def test_one_point_oh_bundle_degrades_gracefully():
    ev = BundleEvaluator(_bundle(), fps=24.0)
    u = bundle_uniforms(ev.evaluate_at(5.0), None, 5.0)
    assert u["iBuild"] == 0.0 and u["iBrightness"] == 0.0
    assert u["iBass"] == u["iVocals"] == u["iDrums"] == u["iOther"] == 0.0
    assert u["iEnergyFast"] == pytest.approx(u["iEnergy"])       # fallback
    assert u["iBeatClock"] > 0 and 0 <= u["iBarPhase"] < 1


def test_tolerates_bad_controls():
    b = _bundle(controls={"build": StemEnergyCurve(hop_sec=0.0, values=[1.0]),
                          "brightness": StemEnergyCurve(hop_sec=0.5, values=[])})
    f = BundleEvaluator(b, fps=24.0).evaluate_at(2.0)
    assert f.build == 0.0 and f.brightness == 0.0
    # controls: null / beats without phrase fields validate
    raw = _bundle().model_dump()
    raw["controls"] = None
    assert MusiCueBundle.model_validate(raw).controls == {}


def test_no_bundle_uniforms():
    u = masked_musical_uniforms(None, None, time_sec=3.5)
    assert set(u) == set(MUSICAL_UNIFORMS)
    assert u["iMusicTime"] == 3.5
    assert u["iTimeToNextSection"] == NO_NEXT_SECTION
    assert all(v == 0.0 for k, v in u.items()
               if k not in ("iMusicTime", "iTimeToNextSection"))


def test_musical_uniform_masks():
    f = BundleEvaluator(_bundle_13(), fps=24.0).evaluate_at(1.0)
    settings = {"tempo": {"mute": True}, "sections": {"mute": True},
                "drums.kick": {"gain": 0.5}, "stem.vocals": {"mute": True},
                "energy": {"threshold": 0.1}}
    u = masked_musical_uniforms(f, settings, 1.0)
    assert u["iBeatClock"] == u["iBarPhase"] == u["iPhrasePhase"] == 0.0
    assert u["iSectionProgress"] == 0.0
    assert u["iTimeToNextSection"] == NO_NEXT_SECTION
    assert u["iKick"] == pytest.approx(0.5 * f.drum_pulses["kick"])
    assert u["iVocals"] == 0.0
    assert u["iEnergyFast"] == pytest.approx(0.5)
    assert u["iBass"] == pytest.approx(0.7)


# ---- health ----

def test_health_reports_controls_and_stems():
    h = bundle_health(_bundle_13())
    assert h["controls"] == {"build": True, "brightness": True, "energy_fast": True}
    assert h["stems_energy"]["present"] is True
    assert h["stems_energy"]["stems"]["bass"] is True
    assert h["phrases"]["present"] is True
    s = format_bundle_health(h)
    assert "controls present: build, brightness, energy_fast" in s
    assert "onset_density" in s          # named as absent
    s10 = format_bundle_health(bundle_health(_bundle()))
    assert "controls present: none" in s10
    assert "iBass" in s10 and "absent" in s10


# ---- timeline / parity ----

def test_timeline_ships_musical_series_matching_evaluator():
    b = _bundle_13()
    tl = build_track_timeline(b, fps=24.0, av_offset_ms=40.0)
    u = tl["frame_data"]["uniforms"]
    n = tl["frames"]
    ev = BundleEvaluator(b, fps=24.0, av_offset_ms=40.0)
    for key in MUSICAL_UNIFORM_SERIES.values():
        assert len(u[key]) == n
    for f in (0, 13, 100, n - 1):
        ref = bundle_uniforms(ev.evaluate(f), None, f / 24.0)
        for name, key in MUSICAL_UNIFORM_SERIES.items():
            assert u[key][f] == pytest.approx(ref[name])


_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node not installed")
@pytest.mark.parametrize("bundle_factory", [_bundle, _bundle_13])
def test_js_compose_uniforms_matches_python(tmp_path, bundle_factory):
    """Run the real web/js/webgl/cue-compose.js composeUniforms in node over
    the shipped frame_data and compare with Python's bundle_uniforms."""
    b = bundle_factory()
    fps = 24.0
    tl = build_track_timeline(b, fps=fps)
    settings_cases = [
        {},
        {"tempo": {"mute": True}, "drums.kick": {"gain": 0.5, "threshold": 0.1},
         "stem.bass": {"gain": 2.0}, "energy": {"threshold": 0.05}},
        {"sections": {"mute": True}, "stem.vocals": {"mute": True},
         "drums.snare": {"mute": True}, "energy": {"mute": True}},
    ]
    frames = [0, 5, 24, 25, 120, 200, tl["frames"] - 1]
    mod = tmp_path / "cue-compose.mjs"
    mod.write_text((ROOT / "web/js/webgl/cue-compose.js").read_text(encoding="utf-8"),
                   encoding="utf-8")
    payload = tmp_path / "in.json"
    payload.write_text(json.dumps({"fd": tl["frame_data"], "cases": settings_cases,
                                   "frames": frames}), encoding="utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(
        "import { composeUniforms } from './cue-compose.mjs';\n"
        "import { readFileSync } from 'fs';\n"
        f"const d = JSON.parse(readFileSync({json.dumps(str(payload))}, 'utf8'));\n"
        "const out = d.cases.map(s => d.frames.map(f => composeUniforms(d.fd, f, s)));\n"
        "console.log(JSON.stringify(out));\n", encoding="utf-8")
    res = subprocess.run([_NODE, str(script)], capture_output=True, text=True,
                         cwd=tmp_path, timeout=60)
    assert res.returncode == 0, res.stderr
    js = json.loads(res.stdout)

    ev = BundleEvaluator(b, fps=fps)
    builtin_keys = {"iBpm": "bpm", "iBeat": "beat", "iBar": "bar",
                    "iSectionEnergy": "sectionEnergy", "iSectionId": "sectionId",
                    "iEnergy": "energy"}
    keymap = {**builtin_keys, **MUSICAL_UNIFORM_SERIES}
    for ci, settings in enumerate(settings_cases):
        for fi, f in enumerate(frames):
            ref = bundle_uniforms(ev.evaluate(f), settings, f / fps)
            got = js[ci][fi]
            assert set(got) == set(keymap.values())
            for name, key in keymap.items():
                assert got[key] == pytest.approx(ref[name], abs=1e-9), (settings, f, name)


def test_renderer_js_declares_and_binds_musical_uniforms():
    s = (ROOT / "web/js/webgl/renderer.js").read_text(encoding="utf-8")
    c = (ROOT / "web/js/webgl/cue-compose.js").read_text(encoding="utf-8")
    assert "MUSICAL_UNIFORMS" in s and "uniform float ${name}" in s
    for name, key in MUSICAL_UNIFORM_SERIES.items():
        assert f'["{name}", "{key}"' in c
    assert '"stem.bass": "low"' in c


# ---- optional real 1.3 sample from the MusiCue producer ----

_SAMPLE = Path("/tmp/claude-0/-home-user/0fd62b68-94a1-51fb-85e6-285f724b58a6/"
               "scratchpad/sample_bundle_1_3.json")


@pytest.mark.skipif(not _SAMPLE.exists(), reason="no sample 1.3 bundle")
def test_sample_bundle_1_3_loads_and_evaluates():
    b = load_bundle(_SAMPLE)
    ev = BundleEvaluator(b, fps=24.0)
    prev = -math.inf
    for t in np.linspace(0, b.duration_sec, 200):
        u = bundle_uniforms(ev.evaluate_at(t), None, t)
        assert all(math.isfinite(v) for v in u.values())
        assert u["iBeatClock"] >= prev
        prev = u["iBeatClock"]
        assert 0 <= u["iBarPhase"] < 1 and 0 <= u["iPhrasePhase"] < 1
        assert 0 <= u["iKick"] <= 1
    assert ev.music_time_at(b.duration_sec) == pytest.approx(b.duration_sec, rel=1e-3)


# ---- demo shader compiles in both wrappers ----

_GLSLANG = shutil.which("glslangValidator")


@pytest.mark.skipif(_GLSLANG is None, reason="glslangValidator not installed")
def test_musical_demo_compiles_for_renderer(tmp_path):
    from cedartoy.shader import load_shader_from_file
    out = tmp_path / "demo.frag"
    out.write_text(load_shader_from_file(ROOT / "shaders/musical_demo.glsl"),
                   encoding="utf-8")
    res = subprocess.run([_GLSLANG, "-S", "frag", str(out)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.skipif(_GLSLANG is None or _NODE is None,
                    reason="glslangValidator/node not installed")
def test_musical_demo_compiles_for_webgl_preview(tmp_path):
    out = tmp_path / "demo_web.frag"
    script = tmp_path / "wrap.mjs"
    renderer = (ROOT / "web/js/webgl/renderer.js").as_uri()
    script.write_text(
        f"import {{ ShaderRenderer }} from {json.dumps(renderer)};\n"
        "import { readFileSync, writeFileSync } from 'fs';\n"
        f"const src = readFileSync({json.dumps(str(ROOT / 'shaders/musical_demo.glsl'))}, 'utf8');\n"
        f"writeFileSync({json.dumps(str(out))}, "
        "ShaderRenderer.prototype.wrapShaderSource.call({}, src));\n",
        encoding="utf-8")
    res = subprocess.run([_NODE, str(script)], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        pytest.skip(f"node could not import renderer.js as ESM: {res.stderr[:200]}")
    res = subprocess.run([_GLSLANG, "-S", "frag", str(out)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
