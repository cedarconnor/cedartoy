from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_validate_toggle_and_track_timeline_present():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "<track-timeline>" in html              # graph mounted in the page
    assert 'id="validate-toggle"' in html          # mode toggle button

    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "track-timeline.js" in appjs            # component imported
    assert "validate-mode" in appjs                # toggle wires the class

    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "validate-mode" in css                  # mode styles exist
