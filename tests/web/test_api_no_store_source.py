from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "web/js/api.js"


def test_get_shader_fetches_no_store():
    s = SRC.read_text(encoding="utf-8")
    # the getShader fetch must opt out of the HTTP cache
    assert "getShader" in s
    assert "no-store" in s
