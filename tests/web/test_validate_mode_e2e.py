import socket
import pytest

URL = "http://127.0.0.1:8080"
PROJECT = r"D:\MusiCue\exports\hair dye"  # audio + sibling .musicue.json with drums


def _server_up():
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _server_up(), reason="UI server not running on :8080")
def test_mute_kick_drops_low_band():
    if not PROJECT:
        pytest.skip("set PROJECT to a drums-bearing project folder")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.fill("#project-path-input", PROJECT)
        page.click("#project-load-btn")
        page.wait_for_function(
            "() => !!document.querySelector('preview-panel')?._timeline",
            timeout=10000)
        page.click("#validate-toggle")

        # Sample a frame where kick is actually active (frame 0 is usually a
        # rest, where the low band is only the section-energy floor). Compose
        # the low band there with kick on vs muted, via the module directly.
        result = page.evaluate("""async () => {
            const m = await import('/js/webgl/cue-compose.js');
            const tl = document.querySelector('preview-panel')._timeline;
            // Pick the strongest kick frame — drum strengths vary per bundle.
            const kick = tl.frame_data.tracks['drums.kick'];
            let f = -1, best = 0;
            for (let i = 0; i < kick.length; i++) {
                if (kick[i] > best) { best = kick[i]; f = i; }
            }
            if (f < 0 || best <= 0) return { f: -1, before: 0, after: 0 };
            const lowSum = (eff) => {
                const row = m.composeRow0(tl.frame_data, f, eff);
                let s = 0; for (let i = 0; i < 32; i++) s += row[i]; return s;
            };
            return {
                f,
                before: lowSum(m.effectiveSettings({}, null)),
                after: lowSum(m.effectiveSettings({'drums.kick': {mute: true}}, null)),
            };
        }""")

        browser.close()
        assert result["f"] >= 0, "no kick-active frame found in timeline"
        assert result["before"] > 0.0
        assert result["after"] < result["before"]
