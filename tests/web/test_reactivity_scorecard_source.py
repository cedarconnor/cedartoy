from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web/js/components/reactivity-scorecard.js"


def test_scorecard_component_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('reactivity-scorecard'" in s
    assert "Score reactivity" in s
    assert "/api/scorecard/start" in s and "/api/scorecard/${" in s
    assert "summary" in s and "source_active" in s
    # bars colored by visual feature
    for f in ("L:", "M:", "H:"):
        assert f in s.split("FEATURE_COLORS")[1].split(";")[0]
    # summary lines inserted as text, not HTML
    assert "li.textContent = line" in s


def test_scorecard_mounted_imported_and_styled():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "<reactivity-scorecard>" in html
    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "reactivity-scorecard.js" in appjs
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "body.validate-mode .reactivity-scorecard" in css
