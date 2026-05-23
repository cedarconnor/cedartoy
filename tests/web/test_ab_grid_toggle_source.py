from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ab_grid_mounted_and_toggled():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "<ab-grid>" in html
    assert 'id="ab-toggle"' in html
    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "ab-grid.js" in appjs
    assert "ab-mode" in appjs
    assert "setActive" in appjs               # grid told when active
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "ab-mode" in css
    assert ".ab-grid" in css
