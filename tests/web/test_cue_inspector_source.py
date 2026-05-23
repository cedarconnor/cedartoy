from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web/js/components/cue-inspector.js"


def test_cue_inspector_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('cue-inspector'" in s
    assert "cue-frame" in s                       # consumes preview snapshot
    assert "loop-toggle" in s                     # dispatches loop request
    assert "loop-region-change" in s              # reflects loop state
    # shows the six uniforms + section + per-track values
    assert "iBpm" in s and "iEnergy" in s and "iSectionId" in s
    assert "trackValues" in s


def test_cue_inspector_mounted_and_imported():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "<cue-inspector>" in html
    appjs = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
    assert "cue-inspector.js" in appjs
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "cue-inspector" in css
