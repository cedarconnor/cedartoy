# Track Reactivity — Phase 4: Calibration Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-track **gain / threshold / smoothing** calibration. Gain and threshold already apply (Phase 1, stateless); this phase adds **smoothing** (a causal one-pole, deferred from Phase 1) and per-lane calibration controls — and keeps preview and render bit-for-bit aligned.

**Architecture:** Smoothing is the only stateful piece. We model the effective per-track value as a **pure function of (raw per-frame series, setting)**: `threshold → one-pole smooth → gain → mute`. Both the headless render and the browser preview build this series and index it by frame, so they match by construction. When `smoothing == 0` the series reduces *exactly* to the current per-frame `apply_setting`, so the no-smoothing path is unchanged (regression-safe, pinned by a reduction test).

**Tech Stack:** Python 3.11, numpy, FastAPI, pytest, Playwright; vanilla JS ES modules.

---

## Background facts (read before starting)

- **One-pole filter (the contract):** `sm[0] = x[0]`; for `f>0`, `sm[f] = (1-a)*x[f] + a*sm[f-1]`, where `a = smoothing ∈ [0,1]`. `a=0` ⇒ `sm[f]=x[f]` (no effect). Applied to the **thresholded** series, then gain, then mute. Order matches spec §3.1: `v' = smooth(max(0, v - threshold)) * gain`, mute ⇒ 0.
- **Phase 1 stateless path:** `apply_setting(value, setting)` in `cedartoy/musicue.py` does `threshold→gain→mute` per scalar. `MusicalSpectrumSynth.synthesize(frame, settings)` sums per-band Hann envelopes of `apply_setting(raw, setting)`; `_BIN_RANGES` low 0:32 / low_mid 32:96 / mid_hi 96:256 / high 256:512; `BAND_TRACKS` + `_BAND_TRACK_SOURCE` map track→band and track→(EvalFrame field,key). Row0 also `+= 0.1*section_energy` (raw) then clip; row1 = heartbeat.
- **Render per-frame** (`cedartoy/render.py:1059-1064`): `eval_frame = self.bundle_eval.evaluate(frame_idx)`; `cued_aud = self.spectrum_synth.synthesize(eval_frame, self.track_settings)`. Bundle init at `render.py:240-259` (`self.bundle_eval`, `self.spectrum_synth`, `self.track_settings`). Render covers frames `0..job.frame_end`.
- **Preview** (`web/js/components/preview-panel.js`): `_composeAndRender(t)` → `composeRow0(tl.frame_data, f, this._effSettings)`. `cue-compose.js` exports `applySetting`, `composeRow0`, `composeUniforms`, `effectiveSettings`, `BAND_TRACKS`, `BAND_RANGES`. `tl.frame_data.tracks[trackId]` is the per-frame raw scalar array (Phase 2).
- **`track_settings`** persists already (Phase 1 config + Phase 2 UI). Calibration just writes `gain`/`threshold`/`smoothing` into the same per-track objects. `TrackSetting` model already validates them (`gain≥0`, `threshold/smoothing∈[0,1]`).
- **Scope:** smoothing applies to **band tracks** (drums/stems → texture). Uniform tracks (tempo/sections/energy) keep mute + gain/threshold on energy-like uniforms (Phase 1); **smoothing of uniform tracks is out of scope** for this phase (document it). The `0.1*section_energy` texture floor stays on raw section energy (unchanged), as pinned by the Phase-2 contract test.
- **Test project (drums):** `D:\MusiCue\exports\hair dye` (low drum strengths — gain is the obvious calibration to demo). No JS unit runner — source-assertion + Playwright + Python parity.

---

## Task 1: `apply_settings_series` — threshold → one-pole → gain → mute

**Files:**
- Modify: `cedartoy/musicue.py`
- Test: `tests/test_tracks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
def test_apply_settings_series_reduces_to_apply_setting_when_no_smoothing():
    from cedartoy.musicue import apply_settings_series, apply_setting
    raw = [0.0, 0.9, 0.3, 0.05, 0.6]
    setting = {"threshold": 0.1, "gain": 2.0}     # smoothing defaults to 0
    series = apply_settings_series(raw, setting)
    assert series == [apply_setting(v, setting) for v in raw]


def test_apply_settings_series_one_pole_smoothing():
    from cedartoy.musicue import apply_settings_series
    raw = [1.0, 0.0, 0.0, 0.0]
    s = apply_settings_series(raw, {"smoothing": 0.5})
    # sm[0]=1; sm[1]=0.5*0+0.5*1=0.5; sm[2]=0.25; sm[3]=0.125
    assert abs(s[0] - 1.0) < 1e-9
    assert abs(s[1] - 0.5) < 1e-9
    assert abs(s[2] - 0.25) < 1e-9
    assert abs(s[3] - 0.125) < 1e-9


def test_apply_settings_series_threshold_before_smooth_then_gain_then_mute():
    from cedartoy.musicue import apply_settings_series
    raw = [0.5, 0.5]
    # threshold 0.1 -> 0.4 each; smoothing 0 -> 0.4; gain 2 -> 0.8
    assert apply_settings_series(raw, {"threshold": 0.1, "gain": 2.0}) == [0.8, 0.8]
    # mute zeroes the whole series
    assert apply_settings_series(raw, {"mute": True, "gain": 2.0}) == [0.0, 0.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k apply_settings_series -v`
Expected: FAIL — `cannot import name 'apply_settings_series'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, add right after `apply_setting`:

```python
def apply_settings_series(raw: "List[float]", setting: Optional[dict]) -> "List[float]":
    """Effective per-frame series for one track: threshold -> one-pole smooth
    -> gain -> mute. Pure function of (raw, setting) so render and preview
    match. smoothing == 0 reduces exactly to per-element apply_setting."""
    n = len(raw)
    if not setting:
        return [float(v) for v in raw]
    if setting.get("mute", False):
        return [0.0] * n
    threshold = float(setting.get("threshold", 0.0))
    gain = float(setting.get("gain", 1.0))
    a = float(setting.get("smoothing", 0.0))
    out = [0.0] * n
    prev = 0.0
    for i in range(n):
        x = max(0.0, float(raw[i]) - threshold)
        sm = x if i == 0 else (1.0 - a) * x + a * prev
        prev = sm
        out[i] = sm * gain
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracks.py -k apply_settings_series -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(tracks): apply_settings_series with causal one-pole smoothing"
```

---

## Task 2: `synthesize_effective` core + delegate `synthesize`

**Files:**
- Modify: `cedartoy/musicue.py` (`MusicalSpectrumSynth`)
- Test: `tests/test_tracks.py`

`synthesize_effective` takes already-effective per-track band scalars; `synthesize(frame, settings)` keeps its signature/behavior by computing stateless per-frame values and delegating (so all Phase 1-3 tests stay green).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
def test_synthesize_effective_matches_synthesize_for_same_values():
    from cedartoy.musicue import MusicalSpectrumSynth, EvalFrame, BAND_TRACKS, apply_setting
    synth = MusicalSpectrumSynth()
    frame = EvalFrame(section_energy=0.4, global_energy=0.5, beat_phase=0.25,
                      drum_pulses={"kick": 0.9, "snare": 0.3},
                      midi_energy={"vocals": 0.7})
    settings = {"drums.kick": {"gain": 0.5}}
    ref = synth.synthesize(frame, settings)
    # Build the same effective band values the delegating path uses.
    band_values = {}
    for tid in BAND_TRACKS:
        field, key = {
            "drums.kick": ("drum_pulses", "kick"), "drums.snare": ("drum_pulses", "snare"),
            "drums.tom": ("drum_pulses", "tom"), "drums.hat": ("drum_pulses", "hat"),
            "drums.cymbal": ("drum_pulses", "cymbal"), "drums.other": ("drum_pulses", "other"),
            "stem.vocals": ("midi_energy", "vocals"), "stem.other": ("midi_energy", "other"),
            "stem.bass": ("midi_energy", "bass"),
        }[tid]
        raw = getattr(frame, field).get(key, 0.0)
        band_values[tid] = apply_setting(raw, settings.get(tid))
    out = synth.synthesize_effective(band_values, frame.section_energy,
                                     frame.beat_phase, frame.global_energy)
    import numpy as np
    assert np.allclose(out, ref, atol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k synthesize_effective -v`
Expected: FAIL — `no attribute 'synthesize_effective'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, replace the body of `MusicalSpectrumSynth.synthesize` and add `synthesize_effective`. Replace the existing `synthesize` method with:

```python
    def synthesize_effective(
        self, band_values: Dict[str, float], section_energy: float,
        beat_phase: float, global_energy: float,
    ) -> np.ndarray:
        """Compose the 2x512 texture from already-effective per-track band
        scalars (settings/smoothing already applied)."""
        tex = np.zeros((2, 512), dtype=np.float32)
        for tid, band in BAND_TRACKS.items():
            v = band_values.get(tid, 0.0)
            if v > 0:
                s, e = _BIN_RANGES[band]
                tex[0][s:e] += self._envelopes[band] * v
        tex[0] += 0.1 * float(section_energy)
        np.clip(tex[0], 0.0, 1.0, out=tex[0])
        wave = 0.5 + 0.5 * float(global_energy) * math.sin(
            2.0 * math.pi * float(beat_phase))
        tex[1, :] = max(0.0, min(1.0, wave))
        return tex

    def synthesize(
        self, frame: "EvalFrame", settings: Optional[Dict[str, dict]] = None
    ) -> np.ndarray:
        settings = settings or {}
        band_values = {
            tid: apply_setting(self._raw_value(frame, tid), settings.get(tid))
            for tid in BAND_TRACKS
        }
        return self.synthesize_effective(
            band_values, frame.section_energy, frame.beat_phase, frame.global_energy)
```

(Keep `track_band_contributions` and `_raw_value` as they are — the Phase-2 contract test still uses `track_band_contributions`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracks.py -v`
Expected: PASS (new test + all existing track tests, including the Phase-2 contract test).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(synth): synthesize_effective core; synthesize delegates"
```

---

## Task 3: Render composes from precomputed effective series

**Files:**
- Modify: `cedartoy/render.py`
- Test: `tests/test_track_settings_render.py`

At bundle init, precompute each band track's effective series over `0..frame_end` (smoothing is causal from frame 0). Per frame, compose via `synthesize_effective`. With `smoothing==0` the series equals the stateless path, so output is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_track_settings_render.py`:

```python
def test_effective_series_smoothing_reduces_and_smooths():
    from cedartoy.musicue import apply_settings_series
    # render uses apply_settings_series to precompute per-track series.
    raw = [0.0, 1.0, 0.0, 0.0, 0.0]
    none = apply_settings_series(raw, None)
    assert none == raw                            # no setting -> identity
    sm = apply_settings_series(raw, {"smoothing": 0.5})
    assert sm[1] == 1.0 and sm[2] == 0.5 and sm[3] == 0.25   # decays after onset
    assert sm != raw                              # smoothing changed the series


def test_renderer_builds_effective_band_series(monkeypatch, tmp_path):
    # Build the series the way Renderer does, asserting smoothing produces a
    # different low-band scalar than no-smoothing at a post-onset frame.
    from cedartoy.musicue import apply_settings_series
    raw_kick = [0.0, 0.8, 0.0, 0.0]
    plain = apply_settings_series(raw_kick, {})
    smoothed = apply_settings_series(raw_kick, {"smoothing": 0.6})
    assert plain[2] == 0.0
    assert smoothed[2] > 0.0                       # smoothing bleeds the onset forward
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest tests/test_track_settings_render.py -k "effective_series or builds_effective" -v`
Expected: PASS immediately (these assert the series helper Task 1 added). If FAIL, fix Task 1. (The render wiring below has no isolated unit test without a GL context; it is covered by the Task 6 live smoke + the reduction guarantee.)

- [ ] **Step 3: Write the render wiring**

In `cedartoy/render.py`, extend the bundle-init block (after `self.spectrum_synth = MusicalSpectrumSynth()`, ~line 255) to precompute the effective series:

```python
                self.spectrum_synth = MusicalSpectrumSynth()
                from .musicue import BAND_TRACKS, _BAND_TRACK_SOURCE, apply_settings_series
                n = int(self.job.frame_end) + 1
                raw_series = {tid: [] for tid in BAND_TRACKS}
                for fi in range(n):
                    ef = self.bundle_eval.evaluate(fi)
                    for tid in BAND_TRACKS:
                        field, key = _BAND_TRACK_SOURCE[tid]
                        raw_series[tid].append(float(getattr(ef, field).get(key, 0.0)))
                self._eff_band_series = {
                    tid: apply_settings_series(raw_series[tid], self.track_settings.get(tid))
                    for tid in BAND_TRACKS
                }
                self._eff_series_len = n
```

Change the per-frame synth call (`render.py:1060-1061`) from `synthesize(eval_frame, self.track_settings)` to compose from the precomputed series:

```python
                    eval_frame = self.bundle_eval.evaluate(frame_idx)
                    from .musicue import BAND_TRACKS
                    idx = min(frame_idx, self._eff_series_len - 1)
                    band_values = {tid: self._eff_band_series[tid][idx] for tid in BAND_TRACKS}
                    cued_aud = self.spectrum_synth.synthesize_effective(
                        band_values, eval_frame.section_energy,
                        eval_frame.beat_phase, eval_frame.global_energy)
```

(`masked_builtin_uniforms(eval_frame, self.track_settings)` at line ~1074 stays unchanged — uniform-track smoothing is out of scope.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_track_settings_render.py tests/test_cli_bundle_wiring.py tests/test_tracks.py -v`
Expected: PASS. The reduction property (Task 1/2) guarantees `smoothing==0` renders identically to Phase 3.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/render.py tests/test_track_settings_render.py
git commit -m "feat(render): compose from precomputed effective per-track series"
```

---

## Task 4: JS series composition (smoothing in preview)

**Files:**
- Modify: `web/js/webgl/cue-compose.js`, `web/js/components/preview-panel.js`
- Test: `tests/web/test_cue_compose_series_source.py` (create)

Add `applySettingsSeries(rawArray, setting)` (mirror of Python) + `composeRow0FromValues(bandValues, sectionEnergy)`. The preview precomputes `_effSeries` per track on settings/timeline change and composes from it.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_cue_compose_series_source.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_cue_compose_series_source.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

In `web/js/webgl/cue-compose.js`, add (after `applySetting`):

```javascript
// Effective per-frame series for one track: threshold -> one-pole smooth ->
// gain -> mute. Mirrors cedartoy/musicue.py::apply_settings_series.
export function applySettingsSeries(raw, setting) {
    const n = raw.length;
    const out = new Float32Array(n);
    if (!setting) { for (let i = 0; i < n; i++) out[i] = raw[i]; return out; }
    if (setting.mute) return out;                 // all zeros
    const threshold = setting.threshold || 0.0;
    const gain = setting.gain == null ? 1.0 : setting.gain;
    const a = setting.smoothing || 0.0;
    let prev = 0.0;
    for (let i = 0; i < n; i++) {
        const x = Math.max(0.0, raw[i] - threshold);
        const sm = i === 0 ? x : (1 - a) * x + a * prev;
        prev = sm;
        out[i] = sm * gain;
    }
    return out;
}

// Compose row 0 from already-effective per-track band scalars for one frame.
export function composeRow0FromValues(bandValues, sectionEnergy) {
    const row0 = new Float32Array(512);
    for (const [tid, band] of Object.entries(BAND_TRACKS)) {
        const v = bandValues[tid] || 0.0;
        if (v > 0) {
            const [s] = BAND_RANGES[band];
            const env = ENVELOPES[band];
            for (let i = 0; i < env.length; i++) row0[s + i] += env[i] * v;
        }
    }
    for (let i = 0; i < 512; i++) row0[i] = Math.min(1.0, row0[i] + 0.1 * (sectionEnergy || 0.0));
    return row0;
}
```

In `web/js/components/preview-panel.js`:
- add a field in the constructor: `this._effSeries = {};`
- add a `_rebuildEffSeries()` helper and call it where `_effSettings` is set (in the `project-loaded` timeline fetch after `this._effSettings = ...`, and in the `track-settings-change` handler after `this._effSettings = ...`):

```javascript
    _rebuildEffSeries() {
        this._effSeries = {};
        if (!this._timeline) return;
        const tracks = this._timeline.frame_data.tracks;
        for (const tid of Object.keys(tracks)) {
            this._effSeries[tid] = applySettingsSeries(tracks[tid], this._effSettings[tid]);
        }
    }
```

Add `applySettingsSeries, composeRow0FromValues` to the import from `cue-compose.js`. Then change `_composeAndRender(t)` to use the series:

```javascript
        const bandValues = {};
        for (const tid of Object.keys(this._effSeries)) bandValues[tid] = this._effSeries[tid][f];
        const row0 = composeRow0FromValues(bandValues, tl.frame_data.uniforms.sectionEnergy[f]);
```

(keep `composeRow1`, `composeUniforms` as-is). And in `_emitCueFrame`, set `trackValues[tid] = (this._effSeries[tid] || [])[f] || 0;` instead of the per-frame `applySetting`, so the inspector reflects smoothing. Call `this._rebuildEffSeries()` right after each place `this._effSettings` is assigned.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_cue_compose_series_source.py tests/web/test_preview_compose_source.py tests/web/test_cue_frame_emit_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/webgl/cue-compose.js web/js/components/preview-panel.js tests/web/test_cue_compose_series_source.py
git commit -m "feat(web): preview composes from smoothed per-track series"
```

---

## Task 5: Per-lane calibration controls

**Files:**
- Modify: `web/js/components/track-timeline.js`, `web/css/main.css`
- Test: `tests/web/test_calibration_controls_source.py` (create)

Each lane gutter gets a "⚙" toggle revealing gain / threshold / smoothing range inputs that write into `trackSettings[id]` and emit `track-settings-change`.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_calibration_controls_source.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_calibration_inputs_present():
    s = (ROOT / "web/js/components/track-timeline.js").read_text(encoding="utf-8")
    assert 'data-action="gain"' in s
    assert 'data-action="threshold"' in s
    assert 'data-action="smoothing"' in s
    assert "track-settings-change" in s           # changes propagate
    css = (ROOT / "web/css/main.css").read_text(encoding="utf-8")
    assert "tt-cal" in css                         # calibration row styles
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_calibration_controls_source.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

In `web/js/components/track-timeline.js`, extend the gutter markup in `_gutter(id)` to append a calibration row (after the M/S buttons), reading current values from `this.trackSettings[id]`:

```javascript
    _gutter(id) {
        const muted = this._isMuted(id);
        const soloed = this.soloIds.has(id);
        const cs = this.trackSettings[id] || {};
        const g = cs.gain == null ? 1 : cs.gain;
        const th = cs.threshold || 0;
        const sm = cs.smoothing || 0;
        return `<div class="tt-gutter${muted ? ' dim' : ''}" data-track="${id}">
            <span class="tt-name">${id}</span>
            <button data-action="mute" data-track="${id}" class="tt-btn${muted ? ' on' : ''}">M</button>
            <button data-action="solo" data-track="${id}" class="tt-btn${soloed ? ' on' : ''}">S</button>
            <div class="tt-cal">
              <label>g<input type="range" data-action="gain" data-track="${id}"
                 min="0" max="4" step="0.1" value="${g}"></label>
              <label>t<input type="range" data-action="threshold" data-track="${id}"
                 min="0" max="1" step="0.05" value="${th}"></label>
              <label>s<input type="range" data-action="smoothing" data-track="${id}"
                 min="0" max="1" step="0.05" value="${sm}"></label>
            </div></div>`;
    }
```

Extend `_attach(lanes)` to wire the range inputs (in addition to the existing `.tt-btn` wiring):

```javascript
        this.querySelectorAll('.tt-cal input').forEach((inp) =>
            inp.addEventListener('input', () => this._calibrate(
                inp.dataset.action, inp.dataset.track, parseFloat(inp.value))));
```

Add the `_calibrate` method:

```javascript
    _calibrate(field, id, value) {
        const cur = this.trackSettings[id] || {};
        this.trackSettings[id] = { ...cur, [field]: value };
        document.dispatchEvent(new CustomEvent('track-settings-change', {
            detail: { trackSettings: this.trackSettings, soloIds: this.soloIds },
        }));
    }
```

(Note: `_calibrate` does NOT call `this.draw()` — re-rendering mid-drag would drop the slider's focus. The lane shapes do not depend on calibration values, so leaving the SVG as-is is correct.)

In `web/css/main.css`, append:

```css
.track-timeline .tt-cal { display: none; gap: 4px; }
body.validate-mode .track-timeline .tt-cal { display: flex; }
.track-timeline .tt-cal label { display: flex; align-items: center; gap: 2px;
    font-size: 9px; color: #778; }
.track-timeline .tt-cal input[type="range"] { width: 46px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_calibration_controls_source.py tests/web/test_track_timeline_source.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/js/components/track-timeline.js web/css/main.css tests/web/test_calibration_controls_source.py
git commit -m "feat(web): per-lane gain/threshold/smoothing calibration controls"
```

---

## Task 6: Regression sweep + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Python suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (E2E skips without a server). Confirms the Phase 1-3 behavior is intact and the new series/synth tests pass.

- [ ] **Step 2: Live smoke (start server, drive browser)**

Start the UI (`python -m cedartoy.cli ui`), then with a Playwright script (headless) against `D:\MusiCue\exports\hair dye`: load project → Validate → at the strongest kick frame, read `composeRow0FromValues` low-band sum with `{}` vs `{drums.kick:{gain:3}}` and assert it rises; with `{drums.kick:{smoothing:0.8}}` assert a post-onset frame's low band is non-zero (smoothing bled the onset forward). Confirm the lane calibration inputs exist (`document.querySelectorAll('.tt-cal input').length`).

- [ ] **Step 3: Stop the server and note results**

Stop the UI server. Record the observed gain/smoothing deltas. No code change expected; commit any fix surfaced.

---

## Self-Review

**Spec coverage (Phase 4 of `2026-05-22-track-reactivity-validation-design.md`):**
- §5.6 calibration: per-track gain/threshold/smoothing → Task 5 (controls), Tasks 1-4 (gain/threshold already from Phase 1; smoothing added here).
- §3.1 effective-contribution formula `v' = smooth(max(0, v - threshold)) * gain`, mute⇒0 → Task 1 (`apply_settings_series`), applied in render (Task 3) and preview (Task 4).
- Preview/render parity preserved → smoothing is a pure series function computed identically both sides; `smoothing==0` reduces to the Phase-1 stateless path (Tasks 1-3 reduction tests + the existing Phase-2 contract test).

**Placeholder scan:** No TBD/TODO. Code complete in every step. JS verified by source-assertion + the existing/Task-6 Playwright (no JS unit runner — stated). Task 3 Step 2 is a pass-through check on the helper plus a documented reliance on the reduction guarantee + live smoke (the GL per-frame wiring has no isolated unit without a context — this is the established repo reality).

**Type/contract consistency:** `apply_settings_series(raw, setting)` (Python, Task 1) ≡ `applySettingsSeries(raw, setting)` (JS, Task 4) — same threshold→one-pole→gain→mute, same recurrence `(1-a)*x+a*prev`, same `smoothing==0` reduction. `synthesize_effective(band_values, section_energy, beat_phase, global_energy)` (Task 2) called by both `synthesize` (delegation) and render (Task 3) with identical arg order. `composeRow0FromValues(bandValues, sectionEnergy)` (Task 4) mirrors `synthesize_effective`'s row0 math (band envelopes + `0.1*sectionEnergy` floor + clip). Calibration writes `{gain,threshold,smoothing}` into `trackSettings[id]`, consumed by `effectiveSettings` → `applySettingsSeries` and persisted via the Phase-2 `track-settings-change` → config path.

**Carry-over note:** the `0.1*section_energy` texture floor remains on **raw** section energy in both `synthesize_effective` and `composeRow0FromValues` (unchanged from Phase 1, pinned by the Phase-2 contract test). Smoothing of uniform tracks (tempo/sections/energy) is intentionally out of scope; only band tracks smooth.
