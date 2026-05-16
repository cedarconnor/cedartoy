"""Playwright smoke test for Plan B's unified preview-sync.

Walks: project load -> no audio-viz Choose-File input -> play ->
playhead moves -> click scrubber -> seek lands on audio + scrubber.
Requires a running CedarToy UI server on http://127.0.0.1:8080 and
a project folder at D:/temp/cedartoy_browser_test_export.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

PROJECT_PATH = "D:/temp/cedartoy_browser_test_export"
URL = "http://127.0.0.1:8080/"


pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright


def _skip_if_no_project():
    if not Path(PROJECT_PATH).exists():
        pytest.skip(f"Test project not at {PROJECT_PATH}")


def test_unified_sync_workflow():
    _skip_if_no_project()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")

        # 1) Load project.
        page.fill("#project-path-input", PROJECT_PATH)
        page.click("#project-load-btn")
        page.wait_for_function(
            "() => !!document.querySelector('transport-strip')?.audio",
            timeout=10000,
        )

        # 2) Legacy <audio-viz> must be gone.
        audio_viz_count = page.evaluate("document.querySelectorAll('audio-viz').length")
        assert audio_viz_count == 0, "audio-viz should be removed"

        # 3) Hit play (the click is the user gesture Web Audio needs).
        page.wait_for_function(
            "() => !document.querySelector('#ts-play').disabled",
            timeout=10000,
        )
        page.click("#ts-play")
        time.sleep(0.8)

        # 4) Playhead has moved.
        current_time = page.evaluate(
            "() => document.querySelector('transport-strip').audio.currentTime"
        )
        assert current_time > 0.2, (
            f"transport-strip should advance audio currentTime, got {current_time}"
        )

        # 5) Click cue-scrubber at ~50% via a dispatched MouseEvent (Playwright's
        #    .click() centers on the element by default which is what we want,
        #    but we use a synthesized MouseEvent for the exact midpoint).
        page.evaluate(
            """
            (() => {
              const hit = document.querySelector('#scrub-hit');
              const r = hit.getBoundingClientRect();
              const ev = new MouseEvent('click', {
                clientX: r.left + r.width * 0.5,
                clientY: r.top + r.height * 0.5,
                bubbles: true,
              });
              hit.dispatchEvent(ev);
            })();
            """
        )
        time.sleep(0.4)

        # 6) Audio currentTime jumped near 50% of duration.
        duration = page.evaluate("document.querySelector('transport-strip').audio.duration")
        seeked = page.evaluate("document.querySelector('transport-strip').audio.currentTime")
        assert abs(seeked - duration * 0.5) < max(0.5, duration * 0.05), (
            f"seek should land near 50%: duration={duration} seeked={seeked}"
        )

        browser.close()
