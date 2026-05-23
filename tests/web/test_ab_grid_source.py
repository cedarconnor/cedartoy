from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/ab-grid.js"


def test_ab_grid_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('ab-grid'" in s
    # four labeled panels
    for label in ("raw", "cued", "blend", "no-audio"):
        assert label in s
    # owns ShaderRenderers + reuses composition
    assert "ShaderRenderer" in s
    assert "composeRow0FromValues" in s and "composeUniforms" in s
    assert "applySettingsSeries" in s
    # synchronized + reactive to inputs
    assert "transport-frame" in s
    assert "audio-data" in s
    assert "shader-select" in s
    assert "track-settings-change" in s
    # only works while active (cheap when off)
    assert "active" in s
