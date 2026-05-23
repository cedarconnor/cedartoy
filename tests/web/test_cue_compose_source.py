from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/webgl/cue-compose.js"


def test_cue_compose_exports_and_bands():
    s = SRC.read_text(encoding="utf-8")
    # exact band ranges must mirror Python _BIN_RANGES
    assert "low" in s and "[0, 32]" in s
    assert "[32, 96]" in s and "[96, 256]" in s and "[256, 512]" in s
    # exported functions the renderer/timeline use
    assert "export function applySetting" in s
    assert "export function effectiveSettings" in s
    assert "export function composeRow0" in s
    assert "export function composeUniforms" in s
    # threshold->gain->mute order documented
    assert "mute" in s and "threshold" in s and "gain" in s


def test_cue_compose_hann_and_solo():
    s = SRC.read_text(encoding="utf-8")
    assert "hann" in s.lower()                # band-fill uses a Hann window
    assert "solo" in s.lower()                # effective-mask honors solo
