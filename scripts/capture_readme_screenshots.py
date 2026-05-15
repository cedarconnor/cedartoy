"""Capture CedarToy UI screenshots for the README.

Assumes the CedarToy UI server is already running on http://127.0.0.1:8080
and that D:/temp/cedartoy_browser_test_export contains a valid
project folder (from MusiCue's send-to-cedartoy).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8080/"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
PROJECT_PATH = "D:/temp/cedartoy_browser_test_export"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 800})
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        time.sleep(0.5)

        # 1) Stage 1, empty (Project panel default).
        page.screenshot(path=str(OUT / "01_project_empty.png"), full_page=False)
        print("wrote 01_project_empty.png")

        # 2) Stage 1, loaded.
        page.fill("#project-path-input", PROJECT_PATH)
        page.click("#project-load-btn")
        page.wait_for_function(
            "() => !!document.querySelector('project-panel')?.project",
            timeout=10000,
        )
        time.sleep(0.5)
        page.screenshot(path=str(OUT / "02_project_loaded.png"), full_page=False)
        print("wrote 02_project_loaded.png")

        # Select a shader so subsequent stages have something to show.
        page.evaluate(
            "document.dispatchEvent(new CustomEvent('shader-select', "
            "{detail: {path: 'auroras.glsl'}}))"
        )
        time.sleep(2.0)  # give preview WebGL a moment

        # 3) Stage 2, Shader (with reactivity readout + button).
        page.click('button.stage-rail-item[data-stage="shader"]')
        time.sleep(1.5)
        page.screenshot(path=str(OUT / "03_shader_stage.png"), full_page=False)
        print("wrote 03_shader_stage.png")

        # 4) Stage 3, Output (with estimate).
        page.click('button.stage-rail-item[data-stage="output"]')
        time.sleep(0.5)
        # Pick the equirect preset to show spherical-first defaults.
        page.select_option("#output-preset", "equirect")
        page.click("#apply-preset")
        time.sleep(1.2)
        page.screenshot(path=str(OUT / "04_output_stage.png"), full_page=False)
        print("wrote 04_output_stage.png")

        # 5) Cue scrubber — preview wrapper scrolls so the scrubber sits below the canvas.
        page.click('button.stage-rail-item[data-stage="project"]')
        time.sleep(0.5)
        page.evaluate(
            "document.querySelector('.preview-panel-wrapper').scrollTop = 9999"
        )
        time.sleep(0.5)
        page.screenshot(path=str(OUT / "05_cue_scrubber.png"), full_page=False)
        print("wrote 05_cue_scrubber.png")

        # 6) Render complete — kick a tiny render at 0.05s @ low res.
        page.click('button.stage-rail-item[data-stage="output"]')
        time.sleep(0.5)
        page.fill("#out-width", "640")
        page.fill("#out-height", "320")
        page.fill("#out-fps", "60")
        page.fill("#out-duration", "0.05")
        page.fill("#out-ss", "1")
        page.fill("#out-temporal", "1")
        page.fill("#out-shutter", "0.5")
        page.fill("#out-tiles-x", "1")
        page.fill("#out-tiles-y", "1")
        # Trigger a change event by tabbing out of the last edited field.
        page.keyboard.press("Tab")
        time.sleep(1.0)

        # Skip the budget guardrail and start render.
        page.evaluate("localStorage.setItem('cedartoy_skip_render_guardrail','1')")
        page.click("#start-render")
        # Wait until logs include "Render complete" or 25s.
        deadline = time.time() + 25
        while time.time() < deadline:
            done = page.evaluate(
                "() => !!document.querySelector('.render-panel-container')?.innerText.match(/Render complete/i)"
            )
            if done:
                break
            time.sleep(0.5)
        time.sleep(0.5)
        page.screenshot(path=str(OUT / "06_render_complete.png"), full_page=False)
        print("wrote 06_render_complete.png")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
