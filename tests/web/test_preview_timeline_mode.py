from pathlib import Path


ROOT = Path(__file__).parents[2]
PREVIEW_PANEL = ROOT / "web" / "js" / "components" / "preview-panel.js"
TRANSPORT_STRIP = ROOT / "web" / "js" / "components" / "transport-strip.js"


def test_preview_panel_exposes_audio_timeline_toggle():
    source = PREVIEW_PANEL.read_text(encoding="utf-8")

    assert 'id="preview-use-timeline"' in source
    assert "Use audio timeline" in source


def test_preview_panel_defaults_to_free_run_without_audio():
    source = PREVIEW_PANEL.read_text(encoding="utf-8")

    assert "this.useAudioTimeline = false" in source
    assert "document.addEventListener('project-loaded'" in source
    assert "this._setUseAudioTimeline(!!e.detail?.audio_url)" in source


def test_preview_panel_ignores_transport_when_free_running():
    source = PREVIEW_PANEL.read_text(encoding="utf-8")

    assert "if (!this.useAudioTimeline) return" in source
    assert "this.renderer.play()" in source
    assert "this.renderer.pause()" in source


def test_timeline_mode_requests_current_transport_frame_when_connected():
    preview_source = PREVIEW_PANEL.read_text(encoding="utf-8")
    transport_source = TRANSPORT_STRIP.read_text(encoding="utf-8")

    assert "transport-sync-request" in preview_source
    assert "transport-sync-request" in transport_source
    assert "_emitCurrentFrame()" in transport_source
