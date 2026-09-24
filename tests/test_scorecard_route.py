"""Scorecard API: proxy render job (mocked) + score, and path safety."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cedartoy.server.api import files
from cedartoy.server.api import scorecard as api
from cedartoy.server.jobs import JobStatus
from tests.test_scorecard import bundle_dict, sources_for, write_frames


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_ALLOWED_ROOTS", {files._PROJECT_ROOT, tmp_path.resolve()})
    monkeypatch.setattr(api, "_SCORECARD_ROOT", tmp_path / "proxy")
    # Completed jobs feed ~/.cedartoy render history; keep tests off it.
    import cedartoy.render_estimate as re_mod
    monkeypatch.setattr(re_mod, "record_history", lambda **kw: None)
    proj = tmp_path / "proj"
    proj.mkdir()
    shader = proj / "s.glsl"
    shader.write_text("void mainImage(out vec4 c, in vec2 p){c=vec4(1);}")
    bd = bundle_dict()
    bundle = proj / "song.musicue.json"
    bundle.write_text(json.dumps(bd), encoding="utf-8")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/scorecard")
    return {"client": TestClient(app), "shader": shader, "bundle": bundle, "bd": bd,
            "tmp": tmp_path}


def _cfg(env, **over):
    cfg = {"shader": str(env["shader"]), "bundle_path": str(env["bundle"]),
           "fps": 24, "width": 1920, "height": 1080, "temporal_samples": 8,
           "track_settings": {"drums.hat": {"mute": True}}}
    cfg.update(over)
    return cfg


def test_start_runs_proxy_render_and_scores(env, monkeypatch):
    kick = sources_for(env["bd"]).series["iKick"]
    seen = {}

    def fake_render(job):
        seen["config"] = dict(job.config)
        write_frames(Path(job.config["output_dir"]), 0.1 + 0.8 * kick)

    monkeypatch.setattr(api, "_render_proxy", fake_render)
    r = env["client"].post("/api/scorecard/start", json={"config": _cfg(env)})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert r.json()["proxy"] == {"width": 512, "height": 256}
    assert seen["config"]["temporal_samples"] == 1
    assert seen["config"]["track_settings"] == {
        "drums.hat": {"gain": 1.0, "mute": True, "threshold": 0.0, "smoothing": 0.0}}

    g = env["client"].get(f"/api/scorecard/{job_id}")
    assert g.status_code == 200
    data = g.json()
    assert data["status"] == JobStatus.COMPLETE
    sc = data["scorecard"]
    assert sc["sources"]["iKick"]["L"]["r"] > 0.95
    assert sc["summary"][0].startswith("kick → brightness")
    assert not Path(seen["config"]["output_dir"]).exists()  # frames cleaned up


def test_render_failure_reported(env, monkeypatch):
    def boom(job):
        raise RuntimeError("proxy render failed (exit 1)")

    monkeypatch.setattr(api, "_render_proxy", boom)
    job_id = env["client"].post("/api/scorecard/start", json={"config": _cfg(env)}).json()["job_id"]
    data = env["client"].get(f"/api/scorecard/{job_id}").json()
    assert data["status"] == JobStatus.ERROR
    assert "exit 1" in data["error"]["message"]
    assert data["scorecard"] is None


def test_unknown_job_404(env):
    assert env["client"].get("/api/scorecard/nope").status_code == 404


@pytest.mark.parametrize("key,value,code", [
    ("shader", "/etc/passwd", 400),                      # wrong extension
    ("shader", "/tmp/../etc/evil.glsl", 403),            # outside allowed roots
    ("bundle_path", "/etc/evil.json", 403),
    ("audio_path", "/etc/evil.wav", 403),
    ("audio_path", "{proj}/song.exe", 400),
    ("bundle_path", "{proj}/missing.json", 404),
])
def test_path_rejection(env, monkeypatch, key, value, code):
    monkeypatch.setattr(api, "_render_proxy", lambda job: pytest.fail("must not render"))
    cfg = _cfg(env, **{key: value.format(proj=env["shader"].parent)})
    r = env["client"].post("/api/scorecard/start", json={"config": cfg})
    assert r.status_code == code, r.text


def test_channel_file_outside_roots_rejected(env, monkeypatch):
    monkeypatch.setattr(api, "_render_proxy", lambda job: pytest.fail("must not render"))
    cfg = _cfg(env, iChannel_paths={"0": "/etc/secret.png", "1": "audio"})
    r = env["client"].post("/api/scorecard/start", json={"config": cfg})
    assert r.status_code == 403


def test_scorecard_router_mounted():
    from cedartoy.server.app import app
    paths = set(app.openapi()["paths"])
    assert "/api/scorecard/start" in paths and "/api/scorecard/{job_id}" in paths


def test_render_subprocess_progress_and_command(env, monkeypatch):
    """The real _render_proxy path with a fake CLI subprocess."""
    import io
    import yaml

    kick = sources_for(env["bd"]).series["iKick"]
    calls = []

    class FakeProc:
        pid = 4242

        def __init__(self, cmd, **kw):
            calls.append(cmd)
            cfg = yaml.safe_load(Path(cmd[-1]).read_text(encoding="utf-8"))
            write_frames(Path(cfg["output_dir"]), 0.1 + 0.8 * kick)
            self.stdout = io.StringIO(
                '[LOG] Renderer init\n'
                '[PROGRESS] {"frame": 192, "total": 192, "elapsed_sec": 2.0}\n')

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(api.subprocess, "Popen", FakeProc)
    job_id = env["client"].post("/api/scorecard/start",
                                json={"config": _cfg(env)}).json()["job_id"]
    assert calls[0][1:5] == ["-m", "cedartoy.cli", "render", "--config"]
    data = env["client"].get(f"/api/scorecard/{job_id}").json()
    assert data["status"] == JobStatus.COMPLETE, data
    assert data["progress"]["frame"] == 192
    assert data["scorecard"]["sources"]["iKick"]["L"]["r"] > 0.95
