from cedartoy.diagnostics import DiagnosticSeverity, run_preflight_checks


def test_preflight_reports_missing_shader():
    result = run_preflight_checks({"shader": "missing-file.glsl", "width": 64, "height": 64})

    assert result.ok is False
    assert result.items[0].severity == DiagnosticSeverity.ERROR
    assert "Shader file not found" in result.items[0].message


def test_preflight_warns_about_large_memory_estimate(tmp_path):
    shader = tmp_path / "shader.glsl"
    shader.write_text(
        "void mainImage(out vec4 fragColor, in vec2 fragCoord){ fragColor = vec4(1.0); }",
        encoding="utf-8",
    )

    result = run_preflight_checks({
        "shader": str(shader),
        "width": 16384,
        "height": 16384,
        "ss_scale": 2,
        "tiles_x": 1,
        "tiles_y": 1,
    })

    assert any(item.code == "memory.estimate.high" for item in result.items)


def test_preflight_passes_small_valid_shader(tmp_path):
    shader = tmp_path / "shader.glsl"
    shader.write_text(
        "void mainImage(out vec4 fragColor, in vec2 fragCoord){ fragColor = vec4(1.0); }",
        encoding="utf-8",
    )

    result = run_preflight_checks({"shader": str(shader), "width": 64, "height": 64})

    assert result.ok is True
