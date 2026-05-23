from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_calibration_inputs_present():
    s = (ROOT / "web/js/components/track-timeline.js").read_text(encoding="utf-8")
    assert 'data-action="gain"' in s
    assert 'data-action="threshold"' in s
    assert 'data-action="smoothing"' in s
    assert "track-settings-change" in s           # changes propagate
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "tt-cal" in css                         # calibration row styles
