from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/preview-panel.js"


def test_preview_uses_cue_compose_when_timeline_present():
    s = SRC.read_text(encoding="utf-8")
    assert "cue-compose.js" in s
    assert "composeRow0" in s and "composeUniforms" in s
    assert "effectiveSettings" in s
    assert "track-settings-change" in s
    assert "/api/reactivity/track-timeline" in s
    # frame index from transport time * fps
    assert "fps" in s
