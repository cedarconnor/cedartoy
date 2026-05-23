from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/components/track-timeline.js"


def test_track_timeline_component_contract():
    s = SRC.read_text(encoding="utf-8")
    assert "customElements.define('track-timeline'" in s
    # fetches the Phase-1 endpoint
    assert "/api/reactivity/track-timeline" in s
    # per-lane mute/solo controls
    assert 'data-action="mute"' in s and 'data-action="solo"' in s
    # native shapes: onsets, curve, section blocks, beats
    assert "onsets" in s and "curve" in s and "blocks" in s and "beats" in s
    # emits settings change + reuses transport-seek
    assert "track-settings-change" in s
    assert "transport-seek" in s
    # muted lanes are visually dimmed
    assert "dim" in s.lower() or "opacity" in s.lower()
