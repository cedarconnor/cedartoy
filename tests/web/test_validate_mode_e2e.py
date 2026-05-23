import socket
import pytest

URL = "http://127.0.0.1:8080"
PROJECT = None  # set to a folder containing audio + sibling .musicue.json with drums


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

        # Compose low-band energy at frame 0 directly via the module.
        low_before = page.evaluate("""async () => {
            const m = await import('/js/webgl/cue-compose.js');
            const tl = document.querySelector('preview-panel')._timeline;
            const eff = m.effectiveSettings({}, null);
            const row = m.composeRow0(tl.frame_data, 0, eff);
            let s = 0; for (let i = 0; i < 32; i++) s += row[i]; return s;
        }""")

        low_after = page.evaluate("""async () => {
            const m = await import('/js/webgl/cue-compose.js');
            const tl = document.querySelector('preview-panel')._timeline;
            const eff = m.effectiveSettings({'drums.kick': {mute: true}}, null);
            const row = m.composeRow0(tl.frame_data, 0, eff);
            let s = 0; for (let i = 0; i < 32; i++) s += row[i]; return s;
        }""")

        browser.close()
        assert low_before > 0.0
        assert low_after < low_before
