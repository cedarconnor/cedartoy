"""Static wiring checks for the modulation-matrix / Expose-knobs web UI
(no browser in CI: the shaping parity itself is tested in test_modulation)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_preview_wires_modulation_binding():
    renderer = (ROOT / "web/js/webgl/renderer.js").read_text(encoding="utf-8")
    preview = (ROOT / "web/js/components/preview-panel.js").read_text(encoding="utf-8")
    config_editor = (ROOT / "web/js/components/config-editor.js").read_text(encoding="utf-8")
    assert "paramOverrides" in renderer
    assert "modulatedValuesAt" in preview and "'modulation-series'" in preview
    assert "<modulation-panel>" in config_editor and "knobs-prompt-btn" in config_editor


def test_ui_wires_knobs_button_and_drawer_kind():
    ce = (ROOT / "web/js/components/config-editor.js").read_text(encoding="utf-8")
    drawer = (ROOT / "web/js/components/shader-reactivity-drawer.js").read_text(encoding="utf-8")
    assert "Expose knobs ▸" in ce and "/api/reactivity/knobs-prompt" in ce
    assert "prompt-kind-change" in ce and "prompt-kind-change" in drawer
    assert "kind: this._kind" in drawer


def test_modulation_panel_posts_routes_and_persists_them():
    panel = (ROOT / "web/js/components/modulation-panel.js").read_text(encoding="utf-8")
    assert "/api/modulation/series" in panel
    assert "cfg.modulation_routes = " in panel          # persisted into the render config
    assert "delete cfg.modulation_routes" in panel      # reset -> @mod defaults
    for field in ("source", "depth", "curve", "attack_beats", "release_beats",
                  "mode", "enabled"):
        assert f'data-k="{field}"' in panel
    assert "'modulation-series'" in panel and "+ route" in panel
