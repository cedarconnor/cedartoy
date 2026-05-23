# Track Reactivity — Phase 1: Parity Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical per-track signal foundation: a `track_settings` model that persists into renders, a settings-aware spectrum synth + uniform builder, and a `GET /api/reactivity/track-timeline` endpoint that ships per-track data + bundle health for the UI — all proven by a parity test that the "select-and-sum per track" model equals the render's synth output.

**Architecture:** Python stays the single canonical evaluator. `MusicalSpectrumSynth` is refactored to compose `iChannel0` from per-track band contributions and to honor per-track settings (mute/gain/threshold). The render reads `track_settings` from the job and applies the exact same composition, so preview (Phase 2, which consumes the timeline endpoint) and render match by construction. Smoothing is defined in the model but its filtering is deferred to Phase 4 (calibration) where statefulness is handled — nothing can set it nonzero before then.

**Tech Stack:** Python 3.11, pydantic v2, numpy, FastAPI (+ `fastapi.testclient`), pytest.

---

## Background facts (read before starting)

- The synth currently hardcodes the band mapping in `cedartoy/musicue.py:288-296`: `low=kick`, `low_mid=snare+tom`, `mid_hi=hat+cymbal`, `high=midi_energy.vocals+other`. Bands are defined in `_BIN_RANGES` (`musicue.py:253-258`). `stem.bass` is **not** currently wired into the texture — this phase wires it into the `high` band.
- `EvalFrame` (`musicue.py:149-159`) already carries `drum_pulses: Dict[str,float]` and `midi_energy: Dict[str,float]` per frame — those are the per-track raw values.
- Render builds the texture at `render.py:1059-1069` via `self.spectrum_synth.synthesize(eval_frame)` and the scalar uniforms at `render.py:1074` via `_builtin_uniforms_from_eval(eval_frame)` (`render.py:62-74`).
- `RenderJob` is built in `cedartoy/cli.py:156-195` from a runtime `cfg` dict (produced by `config_model.CedarToyConfig.to_runtime_dict()`, which `model_dump`s nested models to plain dicts). So at runtime `track_settings` is a `Dict[str, dict]`.
- The reactivity router (`cedartoy/server/api/reactivity.py`) is already mounted; a new `@router.get` is auto-included.

**Canonical track IDs (this phase establishes them):**

```
drums.kick, drums.snare, drums.hat, drums.tom, drums.cymbal, drums.other   (band tracks)
stem.vocals, stem.other, stem.bass                                          (band tracks)
tempo, sections, energy                                                     (uniform tracks)
```

Band assignment: `drums.kick→low`; `drums.snare,drums.tom→low_mid`; `drums.hat,drums.cymbal,drums.other→mid_hi`; `stem.vocals,stem.other,stem.bass→high`.

---

## Task 1: `TrackSetting` config model + `track_settings` field

**Files:**
- Modify: `cedartoy/config_model.py`
- Test: `tests/test_config_model.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config_model.py`:

```python
def test_track_settings_defaults_and_roundtrip():
    from cedartoy.config_model import normalize_config, TrackSetting

    cfg = normalize_config({
        "shader": "shaders/foo.glsl",
        "track_settings": {
            "drums.kick": {"mute": True},
            "stem.vocals": {"gain": 2.0, "threshold": 0.1},
        },
    })
    assert cfg.track_settings["drums.kick"].mute is True
    assert cfg.track_settings["drums.kick"].gain == 1.0          # default
    assert cfg.track_settings["drums.kick"].smoothing == 0.0     # default
    assert cfg.track_settings["stem.vocals"].gain == 2.0
    assert cfg.track_settings["stem.vocals"].threshold == 0.1

    # round-trips to plain dicts for the runtime cfg
    runtime = cfg.to_runtime_dict()
    assert runtime["track_settings"]["drums.kick"]["mute"] is True
    assert runtime["track_settings"]["stem.vocals"]["gain"] == 2.0


def test_track_setting_rejects_negative_gain():
    import pytest
    from pydantic import ValidationError
    from cedartoy.config_model import normalize_config
    with pytest.raises(ValidationError):
        normalize_config({"shader": "shaders/foo.glsl",
                          "track_settings": {"drums.kick": {"gain": -1.0}}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_model.py::test_track_settings_defaults_and_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'TrackSetting'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/config_model.py`, add the model above the `CedarToyConfig` class (after the `Literal` aliases, ~line 13):

```python
class TrackSetting(BaseModel):
    gain: float = 1.0
    mute: bool = False
    threshold: float = 0.0
    smoothing: float = 0.0  # NOTE: filtering implemented in Phase 4 (calibration)

    @field_validator("gain")
    @classmethod
    def _gain_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("gain must be >= 0")
        return value

    @field_validator("threshold", "smoothing")
    @classmethod
    def _unit_range(cls, value: float, info) -> float:
        if value < 0 or value > 1:
            raise ValueError(f"{info.field_name} must be between 0 and 1")
        return value
```

Then add the field to `CedarToyConfig` (after `shader_parameters`, ~line 49):

```python
    track_settings: Dict[str, TrackSetting] = Field(default_factory=dict)
```

`to_runtime_dict()` already calls `self.model_dump(mode="python")`, which converts nested `TrackSetting`s to plain dicts — no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_model.py -v`
Expected: PASS (both new tests + existing tests still green).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/config_model.py tests/test_config_model.py
git commit -m "feat(config): add per-track TrackSetting model and track_settings"
```

---

## Task 2: Canonical track maps + `apply_setting` helper

**Files:**
- Modify: `cedartoy/musicue.py`
- Test: `tests/test_tracks.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_tracks.py`:

```python
from cedartoy.musicue import (
    ALL_TRACK_IDS, BAND_TRACKS, UNIFORM_TRACKS, apply_setting,
)


def test_track_id_inventory():
    assert BAND_TRACKS["drums.kick"] == "low"
    assert BAND_TRACKS["drums.snare"] == "low_mid"
    assert BAND_TRACKS["drums.tom"] == "low_mid"
    assert BAND_TRACKS["drums.hat"] == "mid_hi"
    assert BAND_TRACKS["drums.cymbal"] == "mid_hi"
    assert BAND_TRACKS["drums.other"] == "mid_hi"
    assert BAND_TRACKS["stem.vocals"] == "high"
    assert BAND_TRACKS["stem.other"] == "high"
    assert BAND_TRACKS["stem.bass"] == "high"
    assert UNIFORM_TRACKS == {"tempo", "sections", "energy"}
    # ALL = band + uniform, no duplicates
    assert set(ALL_TRACK_IDS) == set(BAND_TRACKS) | UNIFORM_TRACKS
    assert len(ALL_TRACK_IDS) == len(set(ALL_TRACK_IDS))


def test_apply_setting_threshold_gain_mute():
    assert apply_setting(0.8, None) == 0.8                       # no setting = pass-through
    assert apply_setting(0.8, {"mute": True}) == 0.0             # mute wins
    assert apply_setting(0.8, {"gain": 2.0}) == 1.6              # gain scales
    assert apply_setting(0.05, {"threshold": 0.1}) == 0.0        # below threshold floored
    # threshold subtracts, then gain: (0.8 - 0.1) * 2.0 = 1.4
    assert abs(apply_setting(0.8, {"threshold": 0.1, "gain": 2.0}) - 1.4) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -v`
Expected: FAIL — `ImportError: cannot import name 'ALL_TRACK_IDS'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, replace the bare `_BIN_RANGES` block (lines 253-258) with the canonical maps (keep `_BIN_RANGES` as-is, add the rest):

```python
_BIN_RANGES = {
    "low":     (0, 32),
    "low_mid": (32, 96),
    "mid_hi":  (96, 256),
    "high":    (256, 512),
}

# Canonical track inventory. Band tracks contribute to an iChannel0 band;
# uniform tracks drive scalar uniforms (handled in masked_builtin_uniforms).
BAND_TRACKS: Dict[str, str] = {
    "drums.kick":   "low",
    "drums.snare":  "low_mid",
    "drums.tom":    "low_mid",
    "drums.hat":    "mid_hi",
    "drums.cymbal": "mid_hi",
    "drums.other":  "mid_hi",
    "stem.vocals":  "high",
    "stem.other":   "high",
    "stem.bass":    "high",
}
UNIFORM_TRACKS = {"tempo", "sections", "energy"}
ALL_TRACK_IDS = list(BAND_TRACKS.keys()) + sorted(UNIFORM_TRACKS)

# Map a band track id to the EvalFrame field + key holding its raw value.
_BAND_TRACK_SOURCE = {
    "drums.kick":   ("drum_pulses", "kick"),
    "drums.snare":  ("drum_pulses", "snare"),
    "drums.tom":    ("drum_pulses", "tom"),
    "drums.hat":    ("drum_pulses", "hat"),
    "drums.cymbal": ("drum_pulses", "cymbal"),
    "drums.other":  ("drum_pulses", "other"),
    "stem.vocals":  ("midi_energy", "vocals"),
    "stem.other":   ("midi_energy", "other"),
    "stem.bass":    ("midi_energy", "bass"),
}


def apply_setting(value: float, setting: Optional[dict]) -> float:
    """Stateless threshold→gain→mute. Smoothing is applied in Phase 4."""
    if not setting:
        return value
    if setting.get("mute", False):
        return 0.0
    threshold = float(setting.get("threshold", 0.0))
    gain = float(setting.get("gain", 1.0))
    v = max(0.0, value - threshold)
    return v * gain
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tracks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(tracks): canonical track maps + apply_setting helper"
```

---

## Task 3: Settings-aware synth + per-track contributions (parity cornerstone)

**Files:**
- Modify: `cedartoy/musicue.py` (`MusicalSpectrumSynth`)
- Test: `tests/test_tracks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
import numpy as np
from cedartoy.musicue import MusicalSpectrumSynth, EvalFrame, BAND_TRACKS


def _frame():
    return EvalFrame(
        section_energy=0.4, global_energy=0.5, beat_phase=0.25,
        drum_pulses={"kick": 0.9, "snare": 0.3, "tom": 0.2,
                     "hat": 0.6, "cymbal": 0.1, "other": 0.05},
        midi_energy={"vocals": 0.7, "other": 0.2, "bass": 0.4},
    )


def test_band_contributions_sum_to_synth_output():
    """The select-and-sum model the JS client will use must equal the synth."""
    synth = MusicalSpectrumSynth()
    frame = _frame()

    full = synth.synthesize(frame, settings=None)              # canonical texture

    # Sum per-track contributions + the section_energy floor, same as synth.
    contrib = synth.track_band_contributions(frame, settings=None)
    summed = np.zeros((2, 512), dtype=np.float32)
    for row in contrib.values():
        summed[0] += row
    summed[0] += 0.1 * frame.section_energy
    np.clip(summed[0], 0.0, 1.0, out=summed[0])
    summed[1, :] = full[1, :]   # row 1 (heartbeat) is not per-track

    assert np.allclose(full, summed, atol=1e-6)


def test_muting_kick_removes_low_band():
    synth = MusicalSpectrumSynth()
    frame = _frame()
    muted = synth.synthesize(frame, settings={"drums.kick": {"mute": True}})
    # low band (bins 0:32) must be only the section_energy floor (0.04), no kick
    assert muted[0, 16] <= 0.1 + 1e-6
    full = synth.synthesize(frame, settings=None)
    assert full[0, 16] > muted[0, 16]   # kick contributed before muting


def test_gain_boosts_band():
    synth = MusicalSpectrumSynth()
    frame = _frame()
    base = synth.synthesize(frame, settings=None)
    boosted = synth.synthesize(frame, settings={"stem.vocals": {"gain": 1.5}})
    # high band (bins 256:512) grows with vocal gain (pre-clip headroom assumed)
    assert boosted[0, 300] >= base[0, 300]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k "band_contributions or muting_kick or gain_boosts" -v`
Expected: FAIL — `synthesize() got an unexpected keyword argument 'settings'` / `no attribute 'track_band_contributions'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, replace `MusicalSpectrumSynth` (lines 269-305) with:

```python
class MusicalSpectrumSynth:
    """Synthesize a 2x512 iChannel0 texture from an EvalFrame.

    Composes row 0 from per-track band contributions so the same select-and-sum
    model can run client-side (Phase 2) and match this output exactly.
    """

    def __init__(self) -> None:
        self._envelopes = {
            name: _hann_envelope(end - start)
            for name, (start, end) in _BIN_RANGES.items()
        }

    def _raw_value(self, frame: "EvalFrame", track_id: str) -> float:
        src_field, key = _BAND_TRACK_SOURCE[track_id]
        return float(getattr(frame, src_field).get(key, 0.0))

    def track_band_contributions(
        self, frame: "EvalFrame", settings: Optional[Dict[str, dict]] = None
    ) -> Dict[str, np.ndarray]:
        """Each band track's isolated 512-bin row (settings applied)."""
        settings = settings or {}
        out: Dict[str, np.ndarray] = {}
        for track_id, band in BAND_TRACKS.items():
            value = apply_setting(self._raw_value(frame, track_id),
                                  settings.get(track_id))
            s, e = _BIN_RANGES[band]
            row = np.zeros(512, dtype=np.float32)
            if value > 0:
                row[s:e] = self._envelopes[band] * value
            out[track_id] = row
        return out

    def synthesize(
        self, frame: "EvalFrame", settings: Optional[Dict[str, dict]] = None
    ) -> np.ndarray:
        tex = np.zeros((2, 512), dtype=np.float32)
        for row in self.track_band_contributions(frame, settings).values():
            tex[0] += row
        tex[0] += 0.1 * float(frame.section_energy)
        np.clip(tex[0], 0.0, 1.0, out=tex[0])

        wave = 0.5 + 0.5 * float(frame.global_energy) * math.sin(
            2.0 * math.pi * float(frame.beat_phase)
        )
        tex[1, :] = max(0.0, min(1.0, wave))
        return tex
```

Delete the now-unused `_add_range` method (it was part of the old class body). Note `section_energy`'s `0.1*` floor stays driven by the `sections` track's uniform path; muting `sections` zeroes its uniforms in Task 4 but the texture floor remains (documented behavior — the floor is ambient, not a per-band track).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracks.py -v`
Expected: PASS.

Also run the existing musicue suite to confirm no regressions in the default (no-settings) path:

Run: `python -m pytest tests/test_musicue_integration.py tests/test_musicue_loader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(synth): per-track band contributions + settings-aware synthesize"
```

---

## Task 4: Settings-aware built-in uniforms

**Files:**
- Modify: `cedartoy/musicue.py` (add `masked_builtin_uniforms`)
- Test: `tests/test_tracks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
from cedartoy.musicue import masked_builtin_uniforms


def test_masked_uniforms_passthrough_and_mute():
    frame = EvalFrame(bpm=128.0, beat_phase=0.5, bar=3,
                      section_energy=0.4, section_id=2, global_energy=0.5)

    u = masked_builtin_uniforms(frame, settings=None)
    assert u == {"iBpm": 128.0, "iBeat": 0.5, "iBar": 3,
                 "iSectionEnergy": 0.4, "iSectionId": 2, "iEnergy": 0.5}

    # muting tempo zeroes bpm/beat/bar (closes the step(1.0,iBpm) gate)
    u = masked_builtin_uniforms(frame, settings={"tempo": {"mute": True}})
    assert u["iBpm"] == 0.0 and u["iBeat"] == 0.0 and u["iBar"] == 0
    assert u["iEnergy"] == 0.5   # other tracks unaffected

    # muting energy zeroes iEnergy; muting sections zeroes section uniforms
    u = masked_builtin_uniforms(frame, settings={"energy": {"mute": True},
                                                 "sections": {"mute": True}})
    assert u["iEnergy"] == 0.0
    assert u["iSectionEnergy"] == 0.0 and u["iSectionId"] == 0


def test_masked_uniforms_none_frame():
    u = masked_builtin_uniforms(None, settings={"tempo": {"mute": True}})
    assert u == {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0,
                 "iSectionEnergy": 0.0, "iSectionId": 0, "iEnergy": 0.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k masked_uniforms -v`
Expected: FAIL — `ImportError: cannot import name 'masked_builtin_uniforms'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, add after `apply_setting` (Task 2 block):

```python
def masked_builtin_uniforms(
    frame: Optional["EvalFrame"], settings: Optional[Dict[str, dict]] = None
) -> Dict[str, Any]:
    """The six Phase-1 scalar uniforms with per-track mute applied.

    Uniform tracks: 'tempo' -> iBpm/iBeat/iBar, 'sections' -> iSectionEnergy/
    iSectionId, 'energy' -> iEnergy. Mute zeroes a track's uniforms; gain/
    threshold scale the energy-like uniforms (iSectionEnergy, iEnergy).
    Structural ints (iBpm/iBeat/iBar/iSectionId) honor mute only.
    """
    if frame is None:
        return {"iBpm": 0.0, "iBeat": 0.0, "iBar": 0,
                "iSectionEnergy": 0.0, "iSectionId": 0, "iEnergy": 0.0}
    settings = settings or {}

    def muted(track_id: str) -> bool:
        s = settings.get(track_id)
        return bool(s and s.get("mute", False))

    tempo_off = muted("tempo")
    sections_off = muted("sections")

    return {
        "iBpm": 0.0 if tempo_off else float(frame.bpm),
        "iBeat": 0.0 if tempo_off else float(frame.beat_phase),
        "iBar": 0 if tempo_off else int(frame.bar),
        "iSectionEnergy": 0.0 if sections_off
            else apply_setting(float(frame.section_energy), settings.get("sections")),
        "iSectionId": 0 if sections_off else int(frame.section_id),
        "iEnergy": apply_setting(float(frame.global_energy), settings.get("energy")),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracks.py -k masked_uniforms -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(uniforms): masked_builtin_uniforms honoring track mutes"
```

---

## Task 5: `build_track_timeline` + `bundle_health`

**Files:**
- Modify: `cedartoy/musicue.py`
- Test: `tests/test_tracks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tracks.py`:

```python
from cedartoy.musicue import (
    build_track_timeline, bundle_health, MusiCueBundle, TempoInfo,
    BeatEvent, SectionBundleEntry, DrumOnset, StemEnergyCurve,
)


def _bundle():
    return MusiCueBundle(
        schema_version="1.0", source_sha256="x", duration_sec=4.0, fps=24.0,
        tempo=TempoInfo(bpm_global=120.0, time_signature=[4, 4]),
        beats=[BeatEvent(t=0.0, beat_in_bar=0, bar=0, is_downbeat=True),
               BeatEvent(t=0.5, beat_in_bar=1, bar=0, is_downbeat=False)],
        sections=[SectionBundleEntry(start=0.0, end=2.0, label="verse",
                                     energy_rank=0.3),
                  SectionBundleEntry(start=2.0, end=4.0, label="chorus",
                                     energy_rank=0.9)],
        drums={"kick": [DrumOnset(t=0.0, strength=0.9),
                        DrumOnset(t=1.0, strength=0.7)],
               "hat": []},
        midi={}, midi_energy={"vocals": StemEnergyCurve(hop_sec=0.5,
                                                        values=[0.1, 0.2, 0.3])},
        stems_energy={},
        global_energy=StemEnergyCurve(hop_sec=0.5, values=[0.2, 0.4]),
        cuesheet={},
    )


def test_build_track_timeline_shape():
    tl = build_track_timeline(_bundle(), fps=24.0)
    assert tl["fps"] == 24.0 and tl["duration_sec"] == 4.0
    assert tl["bands"] == ["low", "low_mid", "mid_hi", "high"]
    assert tl["tracks"]["drums.kick"]["band"] == "low"
    assert len(tl["tracks"]["drums.kick"]["onsets"]) == 2
    assert tl["tracks"]["drums.kick"]["onsets"][0] == {"t": 0.0, "strength": 0.9}
    assert tl["tracks"]["stem.vocals"]["curve"]["values"] == [0.1, 0.2, 0.3]
    assert tl["tracks"]["sections"]["blocks"][1]["label"] == "chorus"
    assert tl["tracks"]["tempo"]["bpm"] == 120.0


def test_bundle_health_flags_empty_fields():
    h = bundle_health(_bundle())
    assert h["beats"] == {"present": True, "count": 2}
    assert h["sections"] == {"present": True, "count": 2}
    assert h["drums"]["kick"] == 2
    assert h["drums"]["hat"] == 0
    assert h["midi_energy"]["vocals"] is True
    assert h["midi_energy"].get("bass", False) is False
    assert h["stems_energy"]["present"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracks.py -k "track_timeline or bundle_health" -v`
Expected: FAIL — `ImportError: cannot import name 'build_track_timeline'`.

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/musicue.py`, add near the bottom (after `MusicalSpectrumSynth`):

```python
def bundle_health(bundle: "MusiCueBundle") -> Dict[str, Any]:
    """Report which bundle fields are populated (UI data-quality surface)."""
    return {
        "beats": {"present": bool(bundle.beats), "count": len(bundle.beats)},
        "sections": {"present": bool(bundle.sections),
                     "count": len(bundle.sections)},
        "drums": {cls: len(events) for cls, events in bundle.drums.items()},
        "midi_energy": {stem: bool(curve.values)
                        for stem, curve in bundle.midi_energy.items()},
        "stems_energy": {"present": any(
            bool(c.values) for c in bundle.stems_energy.values())},
    }


def build_track_timeline(bundle: "MusiCueBundle", fps: float) -> Dict[str, Any]:
    """Whole-song per-track data for the UI: lane-draw shapes + health.

    Ships RAW per-track data; consumers (preview/render) apply track_settings.
    """
    duration = float(bundle.duration_sec)
    tracks: Dict[str, Any] = {}

    for track_id, band in BAND_TRACKS.items():
        src_field, key = _BAND_TRACK_SOURCE[track_id]
        if src_field == "drum_pulses":
            events = bundle.drums.get(key, [])
            tracks[track_id] = {
                "band": band,
                "onsets": [{"t": o.t, "strength": o.strength} for o in events],
            }
        else:  # midi_energy curve
            curve = bundle.midi_energy.get(key)
            tracks[track_id] = {
                "band": band,
                "curve": {"hop_sec": curve.hop_sec, "values": list(curve.values)}
                if curve else {"hop_sec": 0.0, "values": []},
            }

    tracks["tempo"] = {
        "bpm": bundle.tempo.bpm_global,
        "beats": [{"t": b.t, "isDownbeat": b.is_downbeat, "bar": b.bar,
                   "beatInBar": b.beat_in_bar} for b in bundle.beats],
    }
    tracks["sections"] = {
        "blocks": [{"start": s.start, "end": s.end, "label": s.label,
                    "energyRank": s.energy_rank} for s in bundle.sections],
    }
    tracks["energy"] = {
        "curve": {"hop_sec": bundle.global_energy.hop_sec,
                  "values": list(bundle.global_energy.values)},
    }

    return {
        "fps": float(fps),
        "duration_sec": duration,
        "frames": int(round(duration * fps)),
        "bands": ["low", "low_mid", "mid_hi", "high"],
        "tracks": tracks,
        "health": bundle_health(bundle),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tracks.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add cedartoy/musicue.py tests/test_tracks.py
git commit -m "feat(timeline): build_track_timeline + bundle_health"
```

---

## Task 6: `GET /api/reactivity/track-timeline` endpoint

**Files:**
- Modify: `cedartoy/server/api/reactivity.py`
- Test: `tests/test_track_timeline_route.py` (create)

The endpoint resolves the bundle for an audio path (reusing `musicue.load_for_audio`), then returns `build_track_timeline`. It mirrors the project route's audio handling.

- [ ] **Step 1: Write the failing test**

Create `tests/test_track_timeline_route.py`:

```python
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cedartoy.server.api.reactivity import router


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api/reactivity")
    return TestClient(app)


def _write_bundle(audio: Path):
    bundle = {
        "schema_version": "1.0", "source_sha256": "x", "duration_sec": 4.0,
        "fps": 24.0, "tempo": {"bpm_global": 120.0, "time_signature": [4, 4]},
        "beats": [{"t": 0.0, "beat_in_bar": 0, "bar": 0, "is_downbeat": True}],
        "sections": [{"start": 0.0, "end": 4.0, "label": "verse",
                      "energy_rank": 0.5}],
        "drums": {"kick": [{"t": 0.0, "strength": 0.9}]},
        "midi": {}, "midi_energy": {}, "stems_energy": {},
        "global_energy": {"hop_sec": 0.5, "values": [0.2, 0.4]},
        "cuesheet": {},
    }
    audio.with_suffix("").with_suffix(".musicue.json").write_text(
        json.dumps(bundle), encoding="utf-8")


def test_track_timeline_returns_tracks_and_health(tmp_path):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF....fake")
    _write_bundle(audio)

    r = _client().get("/api/reactivity/track-timeline",
                      params={"audio": str(audio)})
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"]["drums.kick"]["onsets"][0]["strength"] == 0.9
    assert data["health"]["beats"]["count"] == 1
    assert data["bands"] == ["low", "low_mid", "mid_hi", "high"]


def test_track_timeline_404_when_no_bundle(tmp_path):
    audio = tmp_path / "nobundle.wav"
    audio.write_bytes(b"RIFF....fake")
    r = _client().get("/api/reactivity/track-timeline",
                      params={"audio": str(audio)})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_track_timeline_route.py -v`
Expected: FAIL — 404/route-not-found (endpoint doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `cedartoy/server/api/reactivity.py`, add the import and the route. Update the top import block:

```python
from cedartoy.musicue import build_track_timeline, load_for_audio
```

Add at the end of the file:

```python
@router.get("/track-timeline")
def track_timeline(audio: str, fps: float = 24.0) -> dict:
    """Per-track timeline (lane-draw data + health) for the given audio file."""
    audio_path = Path(audio)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio}")
    result = load_for_audio(audio_path)
    if result.bundle is None:
        raise HTTPException(status_code=404,
                            detail=f"no MusiCue bundle for {audio}")
    return build_track_timeline(result.bundle, fps=fps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_track_timeline_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/server/api/reactivity.py tests/test_track_timeline_route.py
git commit -m "feat(api): GET /api/reactivity/track-timeline"
```

---

## Task 7: Thread `track_settings` through RenderJob → render

**Files:**
- Modify: `cedartoy/types.py` (`RenderJob`)
- Modify: `cedartoy/cli.py:156-195` (`RenderJob(...)` construction)
- Modify: `cedartoy/render.py` (`Renderer.__init__`, `_render_pass`)
- Test: `tests/test_track_settings_render.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_track_settings_render.py` — a unit test that the render's per-frame composition honors `job.track_settings` without spinning up a GL context, by exercising the same helpers the render calls:

```python
import numpy as np

from cedartoy.musicue import (
    MusicalSpectrumSynth, EvalFrame, masked_builtin_uniforms,
)


def test_render_helpers_honor_track_settings():
    # This mirrors exactly what Renderer._render_pass does per frame.
    synth = MusicalSpectrumSynth()
    frame = EvalFrame(bpm=120.0, beat_phase=0.0, bar=1, section_energy=0.4,
                      section_id=1, global_energy=0.5,
                      drum_pulses={"kick": 0.9}, midi_energy={})
    settings = {"drums.kick": {"mute": True}, "tempo": {"mute": True}}

    tex = synth.synthesize(frame, settings)
    uni = masked_builtin_uniforms(frame, settings)

    assert tex[0, 16] <= 0.1 + 1e-6     # kick muted -> only section floor
    assert uni["iBpm"] == 0.0           # tempo muted -> gate closed
```

Also add a `RenderJob` field test in the same file:

```python
def test_render_job_has_track_settings_default():
    from cedartoy.types import RenderJob
    import inspect
    # default_factory dict — constructing without it must work.
    sig = inspect.signature(RenderJob)
    assert "track_settings" in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_track_settings_render.py -v`
Expected: `test_render_job_has_track_settings_default` FAILS (`track_settings` not a field). The helpers test should already PASS (Tasks 3-4 done).

- [ ] **Step 3: Write minimal implementation**

(a) `cedartoy/types.py` — add to `RenderJob` after `shader_parameters` (line 77):

```python
    # Per-track reactivity settings: {track_id: {gain, mute, threshold, smoothing}}
    track_settings: Dict[str, Any] = field(default_factory=dict)
```

(b) `cedartoy/cli.py` — add to the `RenderJob(...)` call (after `bundle_blend=...`, line 194):

```python
        track_settings=cfg.get("track_settings", {}),
```

(c) `cedartoy/render.py` — in `Renderer.__init__`, after `self.bundle_blend = ...` (line 244):

```python
        self.track_settings = getattr(job, "track_settings", {}) or {}
```

(d) `cedartoy/render.py` — update the import at the top of the bundle block (line 247) and the per-frame calls. Change line 247:

```python
                from .musicue import (BundleEvaluator, MusicalSpectrumSynth,
                                      load_for_audio)
```

Change the synthesize call (line 1061) from `self.spectrum_synth.synthesize(eval_frame)` to:

```python
                    cued_aud = self.spectrum_synth.synthesize(
                        eval_frame, self.track_settings)
```

Change the uniform update (line 1074) from `_builtin_uniforms_from_eval(eval_frame)` to the masked builder. Add the import near `_builtin_uniforms_from_eval` usage by importing at top-of-file scope; simplest is to import inline at line 1074:

```python
        from .musicue import masked_builtin_uniforms
        uni.update(masked_builtin_uniforms(eval_frame, self.track_settings))
```

(Leave `_builtin_uniforms_from_eval` in place — the thumbnail path and any callers still use it; it is now superseded for the main render but harmless.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_track_settings_render.py -v`
Expected: PASS (both tests).

Regression: the CLI bundle wiring test must still pass.

Run: `python -m pytest tests/test_cli_bundle_wiring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cedartoy/types.py cedartoy/cli.py cedartoy/render.py tests/test_track_settings_render.py
git commit -m "feat(render): thread track_settings into synth + uniforms"
```

---

## Task 8: Full Phase-1 regression sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (no regressions). If pre-existing unrelated failures exist, note them but do not let new tests fail.

- [ ] **Step 2: Manual endpoint smoke (optional, if a bundle exists)**

Run: `python -c "from cedartoy.musicue import load_for_audio, build_track_timeline; from pathlib import Path; r=load_for_audio(Path('audio_data/Neon Queens.wav')); print(list(build_track_timeline(r.bundle, 24.0)['tracks'])) if r.bundle else print('no bundle')"`
Expected: prints the 12 canonical track ids (or `no bundle` if the sample audio isn't present).

- [ ] **Step 3: Commit any doc note (if needed)**

No code change expected. If the sweep surfaced a fix, commit it with a clear message.

---

## Self-Review

**Spec coverage (Phase 1 scope of `2026-05-22-track-reactivity-validation-design.md`):**
- §3 track model + namespacing → Task 2 (`BAND_TRACKS`, `UNIFORM_TRACKS`, `stem.bass` wired to `high`).
- §3.1 `track_settings` model + config round-trip → Task 1; effective-contribution (threshold→gain→mute) → Task 2 (`apply_setting`); smoothing field present, filtering explicitly deferred to Phase 4 (documented in header + model comment).
- §4 canonical signal path / select-and-sum parity → Task 3 (`track_band_contributions` + parity test).
- §4.2 `PerTrackTimeline` shape (tracks + lane-draw + health) → Task 5; endpoint → Task 6.
- §5.4 bundle health → Task 5 (`bundle_health`).
- Render honors mask (§3.1 "mutes persist to render") → Task 7.
- Parity test cornerstone (§8) → Task 3.

**Placeholder scan:** No TBD/TODO; every code step shows full code; commands have expected output. The single intentional deferral (smoothing filtering → Phase 4) is documented, not a placeholder — the field validates and round-trips now, and no UI can set it nonzero until Phase 4.

**Type consistency:** `apply_setting(value, setting: Optional[dict])`, `synthesize(frame, settings)`, `track_band_contributions(frame, settings)`, `masked_builtin_uniforms(frame, settings)`, `build_track_timeline(bundle, fps)`, `bundle_health(bundle)` are used with identical signatures across Tasks 2-7. `RenderJob.track_settings` (Dict[str, Any]) is populated from `cfg["track_settings"]` (Dict[str, dict] after `model_dump`) and consumed by helpers expecting `Dict[str, dict]` — consistent.

Out-of-Phase-1 spec items (Validate mode UI, cue inspector, section loop, calibration UI, A/B grid, cache fix, explain-prompt) are intentionally NOT in this plan; they are Phases 2-6 and get their own plans.
