from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_render_config_includes_track_settings():
    # The render panel sends the WHOLE config-editor config, and getConfig()
    # returns this.config unfiltered — so track_settings (persisted by
    # preview-panel on mute/solo) is included in the render request.
    rp = (ROOT / "web/js/components/render-panel.js").read_text(encoding="utf-8")
    ce = (ROOT / "web/js/components/config-editor.js").read_text(encoding="utf-8")
    pv = (ROOT / "web/js/components/preview-panel.js").read_text(encoding="utf-8")

    # render panel pulls the full config object.
    assert "getConfig()" in rp and "startRender(config)" in rp
    # getConfig returns the unfiltered config (no key cherry-picking).
    assert "return this.config" in ce
    # preview-panel writes mutes into config.track_settings.
    assert "config.track_settings" in pv
