from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cue_compose_series_exports():
    s = (ROOT / "web/js/webgl/cue-compose.js").read_text(encoding="utf-8")
    assert "export function applySettingsSeries" in s
    assert "export function composeRow0FromValues" in s
    assert "smoothing" in s                       # one-pole present
    # one-pole recurrence form
    assert "1 - a" in s or "(1-a)" in s or "1.0 - a" in s


def test_preview_precomputes_effective_series():
    s = (ROOT / "web/js/components/preview-panel.js").read_text(encoding="utf-8")
    assert "applySettingsSeries" in s
    assert "_effSeries" in s
    assert "composeRow0FromValues" in s
