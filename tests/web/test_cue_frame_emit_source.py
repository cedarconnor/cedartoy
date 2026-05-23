from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/preview-panel.js"


def test_preview_emits_cue_frame():
    s = SRC.read_text(encoding="utf-8")
    assert "cue-frame" in s                       # event name
    assert "trackValues" in s                     # per-track effective values
    assert "sectionLabel" in s                    # section label lookup
    assert "bundleMode" in s                      # cued vs free
    assert "applySetting" in s                    # reuses cue-compose, no reimpl
