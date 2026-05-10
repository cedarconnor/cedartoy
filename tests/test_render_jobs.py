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
