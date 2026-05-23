from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/transport-strip.js"


def test_transport_section_loop_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "loop-toggle" in s                     # listens for the toggle
    assert "loop-region-change" in s              # reports loop state
    assert "_loopRegion" in s                     # holds the region
    # tick wraps playback at region end
    assert "currentTime" in s and ".end" in s and ".start" in s
