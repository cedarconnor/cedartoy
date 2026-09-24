"""Reactivity scorecard on synthetic frames (no GL)."""
import json
import math
import sys
from pathlib import Path

import imageio.v3 as iio
import numpy as np
import pytest

from cedartoy import scorecard as sc
from cedartoy.musicue import MusiCueBundle

FPS = 24.0
N = 192            # 8 s at 24 fps


def bundle_dict(duration=8.0, quiet_until=None, extra_drums=None):
    """Tiny 1.3-style bundle: 120 bpm beats, kick on every beat, hats on an
    irregular off-grid pattern, a 1.3 controls block."""
    beats = []
    for i in range(int(duration / 0.5)):
        beats.append({"t": 0.5 * i, "beat_in_bar": i % 4, "bar": i // 4,
                      "is_downbeat": i % 4 == 0, "phrase_id": i // 16,
                      "phrase_position": (i // 4) % 4, "phrase_length": 4})
    kicks = [{"t": 0.5 * i, "strength": 1.0} for i in range(int(duration / 0.5))]
    rng = np.random.default_rng(7)
    hat_t = np.sort(rng.uniform(0.1, duration - 0.1, size=int(duration * 2)))
    hats = [{"t": float(t), "strength": 0.8} for t in hat_t]
    n_e = int(duration / 0.25) + 1
    if quiet_until is None:
        energy = [0.6] * n_e
    else:
        energy = [0.05 if i * 0.25 < quiet_until else 0.9 for i in range(n_e)]
    drums = {"kick": kicks, "hat": hats}
    drums.update(extra_drums or {})
    return {
        "schema_version": "1.3", "source_sha256": "x", "duration_sec": duration,
        "fps": FPS, "tempo": {"bpm_global": 120.0, "time_signature": [4, 4]},
        "beats": beats,
        "sections": [{"start": 0.0, "end": duration, "label": "a", "energy_rank": 0.5}],
        "drums": drums, "midi": {}, "midi_energy": {}, "stems_energy": {},
        "global_energy": {"hop_sec": 0.25, "values": energy},
        "controls": {"build": {"hop_sec": 0.5, "values": [i / 16 for i in range(17)]}},
        "cuesheet": {},
    }


def sources_for(bd, n=N, **kw):
    b = MusiCueBundle.model_validate(bd)
    return sc.bundle_sources(b, [i / FPS for i in range(n)], FPS, **kw)


def write_frames(d: Path, values, w=32, h=16, colors=None, start=0):
    d.mkdir(parents=True, exist_ok=True)
    for i, v in enumerate(values):
        if colors is not None:
            img = np.broadcast_to(np.asarray(colors[i], dtype=np.float64), (h, w, 3))
        else:
            img = np.full((h, w, 3), float(v))
        iio.imwrite(d / f"frame_{start + i:05d}.png",
                    np.round(np.clip(img, 0, 1) * 255).astype(np.uint8))
    return d


def score_dir(d, bd, tmp_path, **kw):
    bp = tmp_path / "b.json"
    bp.write_text(json.dumps(bd), encoding="utf-8")
    return sc.score_frames(d, FPS, bundle_path=bp, **kw)


# ---- frames / features ----------------------------------------------------

def test_natural_sort_and_frame_numbers(tmp_path):
    for n in (10, 2, 1):
        iio.imwrite(tmp_path / f"f_{n}.png", np.zeros((2, 2, 3), np.uint8))
    (tmp_path / "notes.txt").write_text("x")
    files, nums = sc.list_frames(tmp_path)
    assert [p.name for p in files] == ["f_1.png", "f_2.png", "f_10.png"]
    assert nums == [1, 2, 10]


def test_box_downsample_limits_width():
    img = np.random.default_rng(0).random((100, 600, 3))
    out = sc.box_downsample(img)
    assert out.shape[1] <= 256 and out.shape[1] == 200
    assert out.mean() == pytest.approx(img[:99, :600].mean(), abs=1e-6)


def test_16bit_and_gray_frames_normalise():
    assert sc.to_rgb_float(np.full((2, 2), 65535, np.uint16)).max() == pytest.approx(1.0)
    assert sc.to_rgb_float(np.zeros((2, 2, 4), np.uint8)).shape == (2, 2, 3)


def test_hue_feature_tracks_hue_rotation():
    frames = []
    for i in range(10):
        h = (i * 0.05) % 1.0
        import colorsys
        frames.append(np.broadcast_to(np.array(colorsys.hsv_to_rgb(h, 1, 1)), (4, 4, 3)))
    f = sc.frame_features(frames)
    assert math.isnan(f["H"][0]) and math.isnan(f["M"][0])
    assert np.allclose(f["H"][1:], 0.05, atol=1e-6)


def test_correlation_undefined_for_constants():
    assert sc.pearson(np.ones(10), np.arange(10.0)) is None
    assert sc.pearson(np.arange(2.0), np.arange(2.0)) is None
    r, lag = sc.lagged_correlation(np.zeros(20), np.arange(20.0))
    assert r is None and lag is None


# ---- scoring --------------------------------------------------------------

def test_brightness_following_kick_scores_kick_high_hats_low(tmp_path):
    bd = bundle_dict()
    kick = sources_for(bd).series["iKick"]
    d = write_frames(tmp_path / "f", 0.1 + 0.8 * kick)
    res = score_dir(d, bd, tmp_path)
    k = res["sources"]["iKick"]["L"]
    assert k["r"] > 0.95 and k["lag"] == 0 and k["via"] == "value"
    assert abs(res["sources"]["iHat"]["L"]["r"]) < 0.3
    assert res["summary"][0].startswith("kick → brightness r=")
    assert any(line == "hats: no visible effect" for line in res["summary"])
    assert res["jitter"]["value"] < 0.1
    json.loads(sc.to_json(res))  # JSON-safe (no NaN)


def test_visuals_lagging_two_frames_report_lag_minus_two(tmp_path):
    bd = bundle_dict()
    kick = sources_for(bd).series["iKick"]
    lagged = np.concatenate([[kick[0]] * 2, kick[:-2]])
    res = score_dir(write_frames(tmp_path / "f", 0.1 + 0.8 * lagged), bd, tmp_path)
    assert res["sources"]["iKick"]["L"]["lag"] == -2
    assert res["sources"]["iKick"]["L"]["r"] > 0.95
    assert "(lag -2)" in res["summary"][0]


def test_random_twitch_clip_has_high_jitter(tmp_path):
    bd = bundle_dict()
    srcs = sources_for(bd)
    events = set(srcs.event_frames)
    rng = np.random.default_rng(3)
    values = np.full(N, 0.3)
    candidates = [t for t in range(3, N - 1)
                  if all(abs(t - e) > 2 for e in events)]
    for t in rng.choice(candidates, size=min(8, len(candidates)), replace=False):
        values[t] = 0.9
    res = score_dir(write_frames(tmp_path / "f", values), bd, tmp_path)
    assert res["jitter"]["value"] > 0.8
    assert res["jitter"]["uncaused_bursts"] >= 1
    assert any(line.startswith("jitter") and line.endswith("high") for line in res["summary"])


def test_static_clip_scores_nothing(tmp_path):
    bd = bundle_dict()
    res = score_dir(write_frames(tmp_path / "f", [0.5] * N), bd, tmp_path)
    for per in res["sources"].values():
        for e in per.values():
            assert e["r"] is None or abs(e["r"]) < 0.1
    assert res["jitter"]["value"] == 0.0
    assert res["summary"][0] == "no visible reaction to any musical source"


def test_loud_quiet_dynamic_range(tmp_path):
    bd = bundle_dict(quiet_until=4.0)
    srcs = sources_for(bd)
    kick = srcs.series["iKick"]
    loud = srcs.energy >= 0.5
    # Reacts only when loud: kick flashes in the loud half, still when quiet.
    ok = np.where(loud, 0.2 + 0.7 * kick, 0.2)
    r_ok = score_dir(write_frames(tmp_path / "ok", ok), bd, tmp_path)
    dr = r_ok["dynamic_range"]
    assert dr["quiet_frames"] > 0 and dr["loud_frames"] > 0
    assert dr["verdict"] == "ok"
    assert any("loud passages hit harder" in s for s in r_ok["summary"])
    # Same flashing everywhere: flat.
    flat = 0.2 + 0.7 * kick
    r_flat = score_dir(write_frames(tmp_path / "flat", flat), bd, tmp_path)
    assert r_flat["dynamic_range"]["verdict"] == "flat"
    assert r_flat["dynamic_range"]["motion_ratio"] == pytest.approx(1.0, abs=0.2)


def test_mute_zeroes_source(tmp_path):
    bd = bundle_dict()
    s = sources_for(bd, track_settings={"drums.kick": {"mute": True},
                                        "tempo": {"mute": True}})
    assert not s.series["iKick"].any()
    assert not s.series["beat_pulse"].any()
    assert sources_for(bd).series["beat_pulse"].max() == pytest.approx(1.0)


def test_av_offset_shifts_sources():
    bd = bundle_dict()
    a = sources_for(bd).series["iKick"]
    b = sources_for(bd, av_offset_ms=1000.0 / FPS * 2).series["iKick"]
    # Equal except where an onset lands exactly on a frame (float round-off
    # decides which side of the hit that frame falls).
    assert np.mean(np.isclose(b[2:], a[:-2], atol=1e-6)) > 0.97


def test_fewer_than_three_frames_errors(tmp_path):
    bd = bundle_dict()
    with pytest.raises(sc.ScorecardError, match="at least 3 frames"):
        score_dir(write_frames(tmp_path / "f", [0.1, 0.2]), bd, tmp_path)


def test_no_bundle_no_audio_errors(tmp_path):
    d = write_frames(tmp_path / "f", [0.1, 0.2, 0.3, 0.4])
    with pytest.raises(sc.ScorecardError, match="nothing to score against"):
        sc.score_frames(d, FPS)


def _write_wav(path, seconds=4.0, sr=8000, loud_from=2.0):
    import soundfile as sf
    t = np.arange(int(seconds * sr)) / sr
    amp = np.where(t >= loud_from, 0.8, 0.02)
    sf.write(str(path), amp * np.sin(2 * np.pi * 220 * t), sr)


def test_audio_rms_proxy_without_bundle(tmp_path):
    wav = tmp_path / "song.wav"
    _write_wav(wav)
    n = int(4.0 * FPS)
    level = np.where(np.arange(n) / FPS >= 2.0, 0.9, 0.1)
    d = write_frames(tmp_path / "f", level)
    res = sc.score_frames(d, FPS, audio_path=wav)
    assert res["mode"] == "audio_rms"
    assert list(res["sources"]) == ["audio_rms"]
    assert res["sources"]["audio_rms"]["L"]["r"] > 0.9
    assert res["meta"]["bundle"] is None


def test_sibling_bundle_found_from_audio(tmp_path):
    wav = tmp_path / "song.wav"
    _write_wav(wav)
    bd = bundle_dict(duration=4.0)
    (tmp_path / "song.musicue.json").write_text(json.dumps(bd), encoding="utf-8")
    kick = sources_for(bd, n=96).series["iKick"]
    res = sc.score_frames(write_frames(tmp_path / "f", 0.1 + 0.8 * kick), FPS, audio_path=wav)
    assert res["mode"] == "bundle"
    assert res["meta"]["bundle"].endswith("song.musicue.json")
    assert res["sources"]["iKick"]["L"]["r"] > 0.95


def test_frames_starting_mid_song_use_frame_numbers(tmp_path):
    bd = bundle_dict()
    kick = sources_for(bd).series["iKick"]
    d = write_frames(tmp_path / "f", 0.1 + 0.8 * kick[48:], start=48)
    res = score_dir(d, bd, tmp_path)
    assert res["meta"]["first_frame"] == 48
    assert res["sources"]["iKick"]["L"]["lag"] == 0
    assert res["jitter"]["value"] < 0.1


# ---- proxy render ---------------------------------------------------------

def _runtime_cfg(tmp_path, **over):
    from cedartoy.config import build_config
    shader = tmp_path / "s.glsl"
    shader.write_text("void mainImage(out vec4 c, in vec2 p){c=vec4(1);}")
    cli = {"shader": str(shader), "width": 3840, "height": 2160, "fps": FPS,
           "tiles_x": 4, "tiles_y": 2, "ss_scale": 2.0, "temporal_samples": 16,
           "default_output_format": "png", "default_bit_depth": "16f",
           "av_offset_ms": 40.0, "track_settings": {"drums.kick": {"gain": 2.0}},
           "shader_parameters": {"warp": 0.3}}
    cli.update(over)
    return build_config(None, cli)


def test_proxy_render_config_is_pure_and_low_res(tmp_path):
    from cedartoy.cli import config_to_job
    cfg = _runtime_cfg(tmp_path)
    before = json.dumps(cfg, default=str, sort_keys=True)
    proxy = sc.proxy_render_config(cfg, tmp_path / "out")
    assert json.dumps(cfg, default=str, sort_keys=True) == before  # input untouched
    job = config_to_job(proxy)
    assert (job.width, job.height) == (512, 256)
    assert job.temporal_samples == 1 and job.ss_scale == 1.0
    assert (job.tiles_x, job.tiles_y) == (1, 1)
    assert job.default_output_format == "png" and job.default_bit_depth == "8"
    assert job.output_dir == tmp_path / "out"
    assert job.av_offset_ms == 40.0 and job.fps == FPS
    assert job.track_settings["drums.kick"]["gain"] == 2.0
    assert job.shader_parameters == {"warp": 0.3}


def test_proxy_strips_per_buffer_output_overrides(tmp_path):
    cfg = _runtime_cfg(tmp_path)
    cfg["multipass"] = {"buffers": {"Image": {"shader": cfg["shader"],
                                              "output_format": "exr", "bit_depth": "32f"}}}
    proxy = sc.proxy_render_config(cfg, tmp_path / "out")
    assert "output_format" not in proxy["multipass"]["buffers"]["Image"]
    assert cfg["multipass"]["buffers"]["Image"]["output_format"] == "exr"


def test_render_and_score_with_fake_renderer(tmp_path):
    bd = bundle_dict()
    bp = tmp_path / "b.json"
    bp.write_text(json.dumps(bd), encoding="utf-8")
    kick = sources_for(bd).series["iKick"]
    cfg = _runtime_cfg(tmp_path, bundle_path=str(bp))
    seen = {}

    def fake_render(proxy):
        seen["dir"] = Path(proxy["output_dir"])
        write_frames(seen["dir"], 0.1 + 0.8 * kick, w=512, h=256)

    res = sc.render_and_score(cfg, fake_render, work_dir=tmp_path)
    assert res["sources"]["iKick"]["L"]["r"] > 0.95
    assert not seen["dir"].exists()  # temp frames cleaned up


# ---- CLI ------------------------------------------------------------------

def _run_cli(monkeypatch, argv):
    from cedartoy import cli
    monkeypatch.setattr(sys, "argv", ["cedartoy"] + argv)
    cli.main()


def test_cli_scorecard_end_to_end(tmp_path, monkeypatch, capsys):
    wav = tmp_path / "song.wav"
    _write_wav(wav, seconds=8.0)
    bd = bundle_dict()
    bp = tmp_path / "custom.json"
    bp.write_text(json.dumps(bd), encoding="utf-8")
    kick = sources_for(bd).series["iKick"]
    d = write_frames(tmp_path / "frames", 0.1 + 0.8 * kick, w=600, h=40)
    out = tmp_path / "score.json"
    _run_cli(monkeypatch, ["scorecard", str(d), "--audio", str(wav), "--bundle", str(bp),
                           "--fps", "24", "--json", str(out)])
    printed = capsys.readouterr().out
    assert "kick → brightness" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sources"]["iKick"]["L"]["r"] > 0.95
    assert data["meta"]["analysis_size"][0] <= 256


def test_cli_scorecard_errors_cleanly(tmp_path, monkeypatch, capsys):
    d = write_frames(tmp_path / "frames", [0.1, 0.2, 0.3])
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["scorecard", str(d), "--fps", "24"])
    assert exc.value.code == 2
    assert "nothing to score against" in capsys.readouterr().err


def test_cli_render_scorecard_uses_proxy(tmp_path, monkeypatch, capsys):
    from cedartoy import cli
    bd = bundle_dict()
    bp = tmp_path / "b.json"
    bp.write_text(json.dumps(bd), encoding="utf-8")
    kick = sources_for(bd).series["iKick"]
    shader = tmp_path / "s.glsl"
    shader.write_text("void mainImage(out vec4 c, in vec2 p){c=vec4(1);}")
    jobs = []

    class FakeRenderer:
        def __init__(self, job):
            jobs.append(job)

        def render(self):
            write_frames(Path(jobs[-1].output_dir), 0.1 + 0.8 * kick)

    monkeypatch.setattr(cli, "Renderer", FakeRenderer)
    _run_cli(monkeypatch, ["render", str(shader), "--fps", "24", "--width", "1920",
                           "--bundle-path", str(bp), "--scorecard"])
    assert (jobs[0].width, jobs[0].height, jobs[0].temporal_samples) == (512, 256, 1)
    assert "kick → brightness" in capsys.readouterr().out
