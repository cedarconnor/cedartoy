"""Modulation matrix: routes, @mod parsing, tempo-relative shaping, config
semantics, render/preview parity and the /api/modulation/series endpoint."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from cedartoy.modulation import (
    CURVES, MOD_SOURCES, ModulationEvaluator, Route, SourceTable, apply_curve,
    build_job_modulation, envelope_follow, job_params, parse_mod_comments,
    resolve_routes,
)
from cedartoy.musicue import DrumOnset, TempoInfo
from cedartoy.shader import parse_params
from tests.test_musical_signals import _beats, _bundle, _bundle_13

ROOT = Path(__file__).resolve().parents[1]

PARAMS = [
    {"name": "warp", "type": "float", "default": 0.2, "min": 0.0, "max": 1.0, "label": "Warp"},
    {"name": "phase", "type": "float", "default": 0.0, "min": 0.0, "max": 1.0, "label": "Phase"},
    {"name": "count", "type": "int", "default": 3, "min": 1, "max": 8, "label": "Count"},
]


def _ev(bundle, routes, fps=24.0, **kw):
    return ModulationEvaluator(bundle, fps, routes, PARAMS, **kw)


# ---- Route model / @mod parsing ----

def test_route_model_defaults_and_validation():
    r = Route(target="warp", source="iKick")
    assert (r.depth, r.curve, r.mode, r.enabled) == (1.0, "linear", "add", True)
    assert r.attack_beats == 0.0 and r.release_beats == 0.0
    with pytest.raises(ValueError):
        Route(target="warp", source="iNope")
    with pytest.raises(ValueError):
        Route(target="warp", source="iKick", curve="wiggle")
    with pytest.raises(ValueError):
        Route(target="warp", source="iKick", release_beats=-1)
    with pytest.raises(ValueError):
        Route(target="warp", source="iKick", mode="multiply")


def test_mod_sources_cover_spec():
    for s in ("iEnergy", "iEnergyFast", "iSectionEnergy", "iBuild", "iKick",
              "iSnare", "iHat", "iBass", "iVocals", "iDrums", "iOther",
              "iBrightness", "iBarPhase", "iPhrasePhase", "iSectionProgress",
              "iBeat", "beat_pulse", "downbeat_pulse"):
        assert s in MOD_SOURCES


def test_parse_mod_comments_good_and_malformed():
    src = "\n".join([
        "// @param warp float 0.2 0.0 1.0 \"Warp\"",
        "// @mod warp <- iKick depth=0.5 release=0.5 curve=ease_out",
        "   //@mod phase<-iEnergy depth=1.5 mode=integrate attack_beats=1",
        "// @mod warp <- iHat enabled=false",
        "// @mod warp iKick depth=0.5",                 # no arrow
        "// @mod warp <- iNope depth=0.5",              # unknown source
        "// @mod warp <- iKick curve=wiggle",           # unknown curve
        "// @mod warp <- iKick depth=abc",              # bad number
        "// @mod warp <- iKick speed=2",                # unknown key
        "// @mod warp <- iKick depth=1 depth=2",        # duplicate key
        "// @mod warp <- iKick release=-1",             # negative release
        "// @mod warp <- iKick mode=multiply",          # unknown mode
        "// @mod warp <- iKick enabled=maybe",          # bad bool
        "// @modulate warp <- iKick",                   # different tag
        "int x = 1; // @mod warp <- iKick",             # not a comment line
    ])
    routes = parse_mod_comments(src)
    assert [(r.id, r.target, r.source) for r in routes] == [
        ("mod1", "warp", "iKick"), ("mod2", "phase", "iEnergy"), ("mod3", "warp", "iHat")]
    r1, r2, r3 = routes
    assert r1.depth == 0.5 and r1.release_beats == 0.5 and r1.curve == "ease_out"
    assert r2.mode == "integrate" and r2.depth == 1.5 and r2.attack_beats == 1.0
    assert r3.enabled is False and r3.depth == 1.0


def test_parse_params_shared_and_tolerant():
    src = ("// @param a float 0.5 0.0 1.0 \"A thing\"\n"
           "// @param n int 3 1 8 Count\n"
           "    // @param uniforms and zero here freezes the body.\n"   # prose
           "// @param b float x 0 1 \"bad\"\n"
           "// @param a float 9 0 10 \"dupe\"\n")
    ps = parse_params(src)
    assert [p["name"] for p in ps] == ["a", "n"]
    assert ps[0] == {"name": "a", "type": "float", "default": 0.5, "min": 0.0,
                     "max": 1.0, "label": "A thing"}
    assert ps[1]["default"] == 3 and isinstance(ps[1]["default"], int)


def test_shader_listing_uses_shared_parser():
    from cedartoy.server.api.shaders import _parse_shader_metadata
    meta = _parse_shader_metadata(ROOT / "shaders/luminescence.glsl")
    assert [p["name"] for p in meta["parameters"]] == ["audio_strength", "pulse_speed"]
    assert meta["parameters"] == parse_params(
        (ROOT / "shaders/luminescence.glsl").read_text(encoding="utf-8"))


# ---- shaping ----

@pytest.mark.parametrize("period", [0.5, 1.0])
def test_follower_release_scales_with_beat_period(period):
    dt = 0.005
    n = int(4.0 / dt)
    x = np.zeros(n)
    x[:100] = 1.0
    y = envelope_follow(x, dt, np.full(n, period), attack_beats=0.0, release_beats=1.0)
    assert y[99] == pytest.approx(1.0)
    # One release time constant = 1 beat = `period` seconds after the drop.
    k = 99 + int(round(period / dt))
    assert y[k] == pytest.approx(math.exp(-1.0), rel=1e-3)


@pytest.mark.parametrize("period", [0.5, 1.0])
def test_follower_attack_scales_with_beat_period(period):
    dt = 0.005
    n = int(4.0 / dt)
    x = np.ones(n)
    x[0] = 0.0
    y = envelope_follow(x, dt, np.full(n, period), attack_beats=2.0, release_beats=0.0)
    k = int(round(2.0 * period / dt))
    assert y[k] == pytest.approx(1.0 - math.exp(-1.0), rel=1e-3)


def test_follower_zero_times_is_identity():
    x = np.random.default_rng(0).random(500)
    y = envelope_follow(x, 0.005, np.full(500, 0.5), 0.0, 0.0)
    np.testing.assert_array_equal(x, y)


def test_route_follower_uses_bundle_tempo():
    """Same kick, same route: at 60 bpm the release lasts twice as long in
    seconds as at 120 bpm (release is specified in beats)."""
    def decay_time(bpm):
        period = 60.0 / bpm
        b = _bundle(tempo=TempoInfo(bpm_global=bpm), beats=_beats(40, t0=0.0, period=period),
                    drums={"kick": [DrumOnset(t=2.0, strength=1.0)]})
        # beat_pulse would also scale; iKick decays fast so the follower dominates.
        ev = _ev(b, [Route(target="warp", source="iKick", depth=0.8, release_beats=2.0)])
        ts = np.arange(2.0, 10.0, 0.005)
        v = np.array([ev.evaluate_at(t)["warp"] for t in ts])
        peak = v.max()
        half = 0.2 + 0.5 * (peak - 0.2)
        after = ts[(ts > ts[v.argmax()]) & (v < half)]
        return after[0] - ts[v.argmax()]

    ratio = decay_time(60.0) / decay_time(120.0)
    assert ratio == pytest.approx(2.0, rel=0.1)


def test_curves_endpoints_and_shapes():
    x = np.linspace(0, 1, 101)
    for c in CURVES:
        y = apply_curve(x, c)
        assert y[0] == pytest.approx(0.0, abs=1e-12) and y[-1] == pytest.approx(1.0)
        assert np.all(np.diff(y) >= -1e-12), c
    mid = {c: float(apply_curve(np.array([0.5]), c)[0]) for c in CURVES}
    assert mid["linear"] == pytest.approx(0.5)
    assert mid["pow2"] == pytest.approx(0.25)
    assert mid["sqrt"] == pytest.approx(math.sqrt(0.5))
    assert mid["smoothstep"] == pytest.approx(0.5)
    assert mid["ease_in"] < 0.5 < mid["ease_out"]
    # Out-of-range input is clipped.
    assert apply_curve(np.array([-1.0, 2.0]), "linear").tolist() == [0.0, 1.0]


# ---- add / integrate ----

def test_add_is_clamped_to_param_range():
    b = _bundle()        # energy 0.9 during 4..12 s
    up = _ev(b, [Route(target="warp", source="iEnergy", depth=5.0)])
    down = _ev(b, [Route(target="warp", source="iEnergy", depth=-5.0)])
    assert up.evaluate_at(8.0)["warp"] == 1.0
    assert down.evaluate_at(8.0)["warp"] == 0.0
    small = _ev(b, [Route(target="warp", source="iEnergy", depth=0.5)])
    assert small.evaluate_at(8.0)["warp"] == pytest.approx(0.2 + 0.5 * 0.9)
    # Base comes from shader_parameters.
    based = _ev(b, [Route(target="warp", source="iEnergy", depth=0.1)],
                shader_parameters={"warp": 0.5})
    assert based.evaluate_at(8.0)["warp"] == pytest.approx(0.5 + 0.09)


def test_add_routes_sum_before_clamp():
    b = _bundle()
    ev = _ev(b, [Route(target="warp", source="iEnergy", depth=0.3),
                 Route(target="warp", source="iEnergy", depth=-0.1)])
    assert ev.evaluate_at(8.0)["warp"] == pytest.approx(0.2 + 0.2 * 0.9)


def test_integrate_monotonic_and_unclamped():
    b = _bundle()
    ev = _ev(b, [Route(target="phase", source="iEnergy", depth=1.0, mode="integrate")])
    ts = np.linspace(0, 20, 400)
    v = np.array([ev.evaluate_at(t)["phase"] for t in ts])
    assert np.all(np.diff(v) >= -1e-12)
    assert v[-1] > 1.0                      # exceeds the @param max: not clamped
    # Integral of energy: 4 s at 0.1 then 8 s at 0.9 (linear ramps in between).
    assert ev.evaluate_at(12.0)["phase"] == pytest.approx(0.4 + 7.2, abs=0.1)
    # Past the grid it keeps its last slope instead of freezing.
    assert ev.evaluate_at(40.0)["phase"] > ev.evaluate_at(30.0)["phase"]


def test_disabled_unknown_and_int_targets_are_ignored():
    b = _bundle()
    ev = _ev(b, [Route(target="warp", source="iEnergy", enabled=False),
                 Route(target="nope", source="iEnergy"),
                 Route(target="count", source="iEnergy")])
    assert ev.targets == []
    assert ev.evaluate_at(8.0) == {}


# ---- mutes ----

def test_track_mute_propagates_to_routes():
    b = _bundle()
    route = [Route(target="warp", source="iKick", depth=0.5)]
    live = _ev(b, route)
    muted = _ev(b, route, track_settings={"drums.kick": {"mute": True}})
    assert live.evaluate_at(1.01)["warp"] > 0.5
    assert muted.evaluate_at(1.01)["warp"] == pytest.approx(0.2)
    gained = _ev(b, route, track_settings={"drums.kick": {"gain": 0.5}})
    assert gained.evaluate_at(1.01)["warp"] < live.evaluate_at(1.01)["warp"]


def test_tempo_mute_zeroes_beat_pulses():
    b = _bundle()
    table = SourceTable(b, 24.0)
    muted = SourceTable(b, 24.0, track_settings={"tempo": {"mute": True}})
    assert table.values["beat_pulse"].max() == pytest.approx(1.0, abs=1e-2)
    assert table.values["downbeat_pulse"].max() > 0.9
    assert muted.values["beat_pulse"].max() == 0.0
    assert muted.values["downbeat_pulse"].max() == 0.0
    # Downbeat pulses fire once per bar, beat pulses every beat.
    beat_peaks = np.sum(np.diff(np.sign(np.diff(table.values["beat_pulse"]))) < 0)
    bar_peaks = np.sum(np.diff(np.sign(np.diff(table.values["downbeat_pulse"]))) < 0)
    assert beat_peaks > 3 * bar_peaks > 0


def test_av_offset_delays_modulation():
    b = _bundle()
    route = [Route(target="warp", source="iKick", depth=0.5, release_beats=0.5)]
    ev0 = _ev(b, route)
    ev1 = _ev(b, route, av_offset_ms=100.0)
    for t in (1.0, 1.05, 1.2, 1.5):
        assert ev1.evaluate_at(t + 0.1)["warp"] == pytest.approx(
            ev0.evaluate_at(t)["warp"], abs=1e-9)


def test_sources_are_unit_range():
    table = SourceTable(_bundle_13(), 24.0, track_settings={"stem.bass": {"gain": 4.0}})
    for name in MOD_SOURCES:
        v = table.values[name]
        assert v.min() >= 0.0 and v.max() <= 1.0, name
    assert table.dt <= 1.0 / 200.0
    assert SourceTable(_bundle(), 120.0).dt == pytest.approx(1.0 / 480.0)


# ---- None vs [] semantics / config ----

SRC = ('// @param warp float 0.2 0.0 1.0 "Warp"\n'
       "// @mod warp <- iKick depth=0.5\n")


def test_resolve_routes_none_vs_empty():
    assert [r.source for r in resolve_routes(None, SRC)] == ["iKick"]
    assert resolve_routes([], SRC) == []
    custom = resolve_routes([{"target": "warp", "source": "iHat"}], SRC)
    assert [r.source for r in custom] == ["iHat"]


def _job(tmp_path, routes, src=SRC):
    shader = tmp_path / "s.glsl"
    shader.write_text(src + "void mainImage(out vec4 c, in vec2 f){c=vec4(warp);}\n",
                      encoding="utf-8")
    return SimpleNamespace(shader_main=shader, multipass_graph=None, fps=24.0,
                           modulation_routes=routes, track_settings={},
                           av_offset_ms=0.0, shader_parameters={})


def test_build_job_modulation_semantics(tmp_path):
    b = _bundle()
    ev = build_job_modulation(_job(tmp_path, None), b)
    assert ev is not None and [r.source for r in ev.routes] == ["iKick"]
    assert build_job_modulation(_job(tmp_path, []), b) is None
    ev = build_job_modulation(_job(tmp_path, [{"target": "warp", "source": "iEnergy"}]), b)
    assert [r.source for r in ev.routes] == ["iEnergy"]
    assert job_params(_job(tmp_path, None))[0]["name"] == "warp"


def test_config_round_trip(tmp_path):
    from cedartoy.cli import config_to_job
    from cedartoy.config import build_config
    shader = tmp_path / "s.glsl"
    shader.write_text(SRC, encoding="utf-8")
    routes = [{"id": "r1", "target": "warp", "source": "iKick", "depth": 0.6,
               "curve": "ease_out", "attack_beats": 0.0, "release_beats": 0.5,
               "mode": "add", "enabled": True}]

    cfg = build_config(None, {"shader": str(shader)})
    assert cfg["modulation_routes"] is None
    assert config_to_job(cfg).modulation_routes is None

    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps({"shader": str(shader), "modulation_routes": routes}))
    cfg = build_config(cfg_path, None)
    assert cfg["modulation_routes"] == routes
    job = config_to_job(cfg)
    assert job.modulation_routes == routes

    cfg_path.write_text(json.dumps({"shader": str(shader), "modulation_routes": []}))
    assert config_to_job(build_config(cfg_path, None)).modulation_routes == []

    cfg_path.write_text(json.dumps({"shader": str(shader),
                                    "modulation_routes": [{"target": "w", "source": "bad"}]}))
    with pytest.raises(Exception):
        build_config(cfg_path, None)


def test_render_job_yaml_round_trip(tmp_path):
    """The web render path: job config written as YAML, re-read by the CLI."""
    from cedartoy.config import build_config
    from cedartoy.server.jobs import RenderJobManager
    shader = tmp_path / "s.glsl"
    shader.write_text(SRC, encoding="utf-8")
    routes = [{"target": "warp", "source": "beat_pulse", "depth": -0.2,
               "mode": "integrate"}]
    rec = RenderJobManager(tmp_path / "jobs").create_job(
        {"shader": str(shader), "modulation_routes": routes})
    cfg = build_config(rec.config_file, None)
    assert cfg["modulation_routes"][0]["source"] == "beat_pulse"
    assert cfg["modulation_routes"][0]["mode"] == "integrate"


# ---- parity ----

@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0])
def test_series_matches_evaluate_at_frame_times(fps):
    b = _bundle_13()
    routes = [Route(target="warp", source="iKick", depth=0.7, release_beats=0.5, curve="ease_out"),
              Route(target="warp", source="beat_pulse", depth=0.2, attack_beats=0.25, release_beats=1),
              Route(target="phase", source="iEnergy", depth=1.2, mode="integrate")]
    ev = _ev(b, routes, fps=fps, shader_parameters={"warp": 0.1})
    n = int(round(b.duration_sec * fps))
    series = ev.series(fps, n)
    assert set(series) == {"warp", "phase"}
    for f in range(0, n, 7):
        ref = ev.evaluate_at(f / fps)
        for k in series:
            assert series[k][f] == ref[k]


def _renderer_uniform_params(ev, time_val):
    """Mirror of Renderer._render_pass param injection."""
    uni = {"warp": 0.2, "phase": 0.0, "count": 3}
    uni.update({"warp": 0.1})
    uni.update(ev.evaluate_at(time_val))
    return uni


def test_render_injection_uses_sample_time():
    from cedartoy.render import sample_time, temporal_offsets
    b = _bundle()
    ev = _ev(b, [Route(target="warp", source="iKick", depth=0.8)],
             shader_parameters={"warp": 0.1})
    offs = temporal_offsets(4, 24)
    vals = {_renderer_uniform_params(ev, sample_time(1.0, o, 0.5, 24.0))["warp"] for o in offs}
    assert len(vals) > 1        # motion-blur samples see the envelope move
    assert _renderer_uniform_params(ev, 3.5)["count"] == 3


_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_js_modulated_values_match_python(tmp_path, monkeypatch):
    """The preview's binding (web/js/webgl/modulation-bind.js) picks the same
    values the renderer evaluates at frame times."""
    b = _bundle()
    fps = 24.0
    ev = _ev(b, [Route(target="warp", source="iKick", depth=0.6, release_beats=0.5),
                 Route(target="phase", source="iEnergy", depth=1.0, mode="integrate")])
    n = int(round(b.duration_sec * fps))
    payload = {"fps": fps, "frames": n, "series": ev.series(fps, n)}
    times = [-1.0, 0.0, 0.01, 0.52, 1.0, 1.02, 5.5, 7.77, 15.99, 16.0, 99.0]
    mod = tmp_path / "bind.mjs"
    mod.write_text((ROOT / "web/js/webgl/modulation-bind.js").read_text(encoding="utf-8"),
                   encoding="utf-8")
    data = tmp_path / "in.json"
    data.write_text(json.dumps({"payload": payload, "times": times}), encoding="utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(
        "import { modulatedValuesAt } from './bind.mjs';\n"
        "import { readFileSync } from 'fs';\n"
        f"const d = JSON.parse(readFileSync({json.dumps(str(data))}, 'utf8'));\n"
        "console.log(JSON.stringify(d.times.map(t => modulatedValuesAt(d.payload, t))));\n",
        encoding="utf-8")
    res = subprocess.run([_NODE, str(script)], capture_output=True, text=True,
                         cwd=tmp_path, timeout=60)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    for t, vals in zip(times, got):
        f = min(max(int(math.floor(t * fps + 0.5)), 0), n - 1)
        ref = ev.evaluate_at(f / fps)
        assert vals == pytest.approx(ref, abs=1e-12), t


# ---- API ----

@pytest.fixture
def client():
    return TestClient(__import__("cedartoy.server.app", fromlist=["app"]).app)


def _seed_project(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "song.wav"
    sf.write(str(audio), np.zeros(4410, dtype="float32"), 44100, subtype="PCM_16")
    b = _bundle(duration_sec=4.0,
                global_energy=_bundle().global_energy.model_copy(update={"values": [0.5] * 5}))
    (folder / "song.musicue.json").write_text(b.model_dump_json(), encoding="utf-8")
    return audio


def test_series_endpoint_defaults_custom_and_empty(client, tmp_path):
    audio = _seed_project(tmp_path / "proj")
    assert client.post("/api/project/load", json={"path": str(tmp_path / "proj")}).status_code == 200

    r = client.post("/api/modulation/series", json={
        "shader": "shaders/auroras.glsl", "audio": str(audio), "fps": 24})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bundle_loaded"] is True and body["routes_from"] == "shader"
    assert body["mod_sources"] == list(MOD_SOURCES)
    assert body["frames"] == 96
    src = (ROOT / "shaders/auroras.glsl").read_text(encoding="utf-8")
    assert [x["target"] for x in body["routes"]] == [r.target for r in parse_mod_comments(src)]
    assert set(body["series"]) == {x["target"] for x in body["routes"]}
    assert all(len(v) == 96 for v in body["series"].values())

    # Python evaluator parity for the served series.
    from cedartoy.musicue import load_bundle
    ev = ModulationEvaluator(load_bundle(tmp_path / "proj/song.musicue.json"), 24.0,
                             parse_mod_comments(src), parse_params(src))
    for f in (0, 10, 50, 95):
        for k, v in ev.evaluate_at(f / 24.0).items():
            assert body["series"][k][f] == pytest.approx(v, abs=1e-12)

    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "bundle": str(tmp_path / "proj/song.musicue.json"),
        "routes": [{"id": "x", "target": "star_gain", "source": "iEnergy", "depth": 1.0}],
        "shader_parameters": {"star_gain": 0.5}})
    body = r.json()
    assert body["routes_from"] == "config" and list(body["series"]) == ["star_gain"]
    assert body["series"]["star_gain"][30] == pytest.approx(1.0)

    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "audio": str(audio), "routes": []})
    assert r.json()["routes"] == [] and r.json()["series"] == {}

    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "audio": str(audio),
        "track_settings": {"drums.kick": {"mute": True}},
        "routes": [{"target": "aurora_gain", "source": "iKick", "depth": 1.0}]})
    assert set(r.json()["series"]["aurora_gain"]) == {1.8}


def test_series_endpoint_without_bundle(client):
    r = client.post("/api/modulation/series", json={"shader": "musical_demo.glsl"})
    assert r.status_code == 200
    body = r.json()
    assert body["bundle_loaded"] is False and body["series"] == {}
    assert {p["name"] for p in body["params"]} >= {"fog_density", "swirl_phase"}
    assert len(body["routes"]) == 4


def test_series_endpoint_rejects_bad_paths(client, tmp_path):
    outside = tmp_path / "elsewhere"
    audio = _seed_project(outside)     # never loaded as a project
    r = client.post("/api/modulation/series", json={"shader": "auroras.glsl", "audio": str(audio)})
    assert r.status_code == 403
    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "bundle": str(outside / "song.musicue.json")})
    assert r.status_code == 403
    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "bundle": str(ROOT / "README.md")})
    assert r.status_code == 400
    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "audio": str(ROOT / "requirements.txt")})
    assert r.status_code == 400
    for bad in ("../README.md", "shaders/../README.md", "/etc/passwd", "common/../../x.glsl"):
        r = client.post("/api/modulation/series", json={"shader": bad})
        assert r.status_code == 400, bad
    assert client.post("/api/modulation/series", json={"shader": "nope.glsl"}).status_code == 404
    r = client.post("/api/modulation/series", json={
        "shader": "auroras.glsl", "routes": [{"target": "x", "source": "iBogus"}]})
    assert r.status_code == 422


# ---- example shaders ----

@pytest.mark.parametrize("name", ["auroras.glsl", "musical_demo.glsl"])
def test_example_shaders_declare_knobs_and_routes(name):
    src = (ROOT / "shaders" / name).read_text(encoding="utf-8")
    params = {p["name"]: p for p in parse_params(src)}
    routes = parse_mod_comments(src)
    assert len(params) >= 3 and len(routes) >= 3
    for r in routes:
        assert r.target in params and params[r.target]["type"] == "float"
        assert f"uniform float {r.target};" in src
    for p in params.values():
        assert p["min"] <= p["default"] <= p["max"]


_GLSLANG = shutil.which("glslangValidator")


@pytest.mark.skipif(_GLSLANG is None, reason="glslangValidator not installed")
@pytest.mark.parametrize("name", ["auroras.glsl", "musical_demo.glsl"])
def test_example_shaders_compile_for_renderer(tmp_path, name):
    from cedartoy.shader import load_shader_from_file
    out = tmp_path / "s.frag"
    out.write_text(load_shader_from_file(ROOT / "shaders" / name), encoding="utf-8")
    res = subprocess.run([_GLSLANG, "-S", "frag", str(out)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.skipif(_GLSLANG is None or _NODE is None,
                    reason="glslangValidator/node not installed")
@pytest.mark.parametrize("name", ["auroras.glsl", "musical_demo.glsl"])
def test_example_shaders_compile_for_webgl_preview(tmp_path, name):
    out = tmp_path / "s_web.frag"
    script = tmp_path / "wrap.mjs"
    renderer = (ROOT / "web/js/webgl/renderer.js").as_uri()
    script.write_text(
        f"import {{ ShaderRenderer }} from {json.dumps(renderer)};\n"
        "import { readFileSync, writeFileSync } from 'fs';\n"
        f"const src = readFileSync({json.dumps(str(ROOT / 'shaders' / name))}, 'utf8');\n"
        f"writeFileSync({json.dumps(str(out))}, "
        "ShaderRenderer.prototype.wrapShaderSource.call({}, src));\n",
        encoding="utf-8")
    res = subprocess.run([_NODE, str(script)], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        pytest.skip(f"node could not import renderer.js as ESM: {res.stderr[:200]}")
    res = subprocess.run([_GLSLANG, "-S", "frag", str(out)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
