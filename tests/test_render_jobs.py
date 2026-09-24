from cedartoy.server.jobs import JobStatus, RenderJobManager


def test_create_job_assigns_id_and_initial_state(tmp_path):
    manager = RenderJobManager(work_dir=tmp_path)

    job = manager.create_job({"shader": "shaders/test.glsl", "output_dir": str(tmp_path / "out")})

    assert job.id
    assert job.status == JobStatus.QUEUED
    assert job.config["shader"] == "shaders/test.glsl"
    assert job.config_file.exists()


def test_job_state_transitions_are_recorded(tmp_path):
    manager = RenderJobManager(work_dir=tmp_path)
    job = manager.create_job({"shader": "shaders/test.glsl"})

    manager.mark_running(job.id, process_pid=123)
    manager.append_log(job.id, "render started")
    manager.mark_complete(job.id, {"output_dir": str(tmp_path)})

    current = manager.get_job(job.id)
    assert current.status == JobStatus.COMPLETE
    assert current.process_pid == 123
    assert current.logs[-1].message == "render started"
    assert current.result == {"output_dir": str(tmp_path)}


def test_artifacts_are_listed_from_output_dir(tmp_path):
    output_dir = tmp_path / "renders"
    output_dir.mkdir()
    (output_dir / "frame_00001.png").write_bytes(b"png")
    (output_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    manager = RenderJobManager(work_dir=tmp_path)
    job = manager.create_job({"shader": "shaders/test.glsl", "output_dir": str(output_dir)})

    artifacts = manager.list_artifacts(job.id)

    assert artifacts == [{"name": "frame_00001.png", "path": str(output_dir / "frame_00001.png"), "size": 3}]


def test_claim_job_only_succeeds_once(tmp_path):
    manager = RenderJobManager(work_dir=tmp_path)
    job = manager.create_job({"shader": "shaders/test.glsl"})

    assert manager.claim_job(job.id) is True
    assert manager.get_job(job.id).status == JobStatus.RUNNING
    assert manager.claim_job(job.id) is False


def test_claim_job_refuses_cancelled(tmp_path):
    manager = RenderJobManager(work_dir=tmp_path)
    job = manager.create_job({"shader": "shaders/test.glsl"})
    manager.cancel_job(job.id)
    assert manager.claim_job(job.id) is False


def test_websocket_does_not_start_job_twice(monkeypatch):
    from fastapi.testclient import TestClient
    from cedartoy.server import websocket as ws_mod
    from cedartoy.server.app import app

    spawned = []
    monkeypatch.setattr(ws_mod.subprocess, "Popen",
                        lambda *a, **k: spawned.append(a) or (_ for _ in ()).throw(RuntimeError("no spawn in tests")))
    job = ws_mod.job_manager.create_job({"shader": "shaders/test.glsl"})
    assert ws_mod.job_manager.claim_job(job.id)  # someone already started it

    with TestClient(app).websocket_connect("/ws/render") as ws:
        ws.send_json({"type": "start_render", "job_id": job.id})
        msg = ws.receive_json()
    assert msg["type"] == "render_error"
    assert "already" in msg["message"]
    assert spawned == []
