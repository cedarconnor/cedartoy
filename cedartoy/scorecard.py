"""Reactivity scorecard: does a rendered clip actually follow the music?

Pure numpy, no GL. Reads a directory of rendered frames, extracts three
visual features per frame and correlates them with the musical signals the
shader was driven by (the same post-mute/calibration bundle uniforms the
renderer binds). See docs/modulation-and-scorecard.md, section 2.

Visual features (per frame, on a <= 256 px wide box-filtered copy):
  L  mean luminance (Rec.709 luma)
  M  motion: mean |frame_t - frame_{t-1}|  (undefined for the first frame)
  H  hue shift: mean circular |hue_t - hue_{t-1}| in turns (0..0.5), over
     pixels saturated/bright enough in both frames to have a meaningful hue

Lag convention: ``lag = k`` means visual frame t best matches source frame
t + k, so a *negative* lag means the visuals lag the audio.
"""
from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# NOTE: mirrors the MOD_SOURCES list of the modulation matrix
# (docs/modulation-and-scorecard.md §1). Unify with modulation.MOD_SOURCES
# once cedartoy/modulation.py lands.
SCORE_SOURCES: Tuple[str, ...] = (
    "iEnergy", "iEnergyFast", "iSectionEnergy", "iBuild",
    "iKick", "iSnare", "iHat", "iBass", "iVocals", "iDrums", "iOther",
    "iBrightness", "iBarPhase", "iPhrasePhase", "iSectionProgress", "iBeat",
)
DERIVED_SOURCES: Tuple[str, ...] = ("beat_pulse", "downbeat_pulse")
# Sources scored both as values and via their positive derivative (onsets).
IMPULSIVE_SOURCES = frozenset({
    "iKick", "iSnare", "iHat", "iEnergyFast", "beat_pulse", "downbeat_pulse",
    "audio_rms",
})
# Proxy source used when no MusiCue bundle is available.
AUDIO_RMS_SOURCE = "audio_rms"

FEATURES: Tuple[str, ...] = ("L", "M", "H")
FEATURE_NAMES = {"L": "brightness", "M": "motion", "H": "hue"}
SOURCE_LABELS = {
    "iEnergy": "energy", "iEnergyFast": "fast energy",
    "iSectionEnergy": "section energy", "iBuild": "build", "iKick": "kick",
    "iSnare": "snare", "iHat": "hats", "iBass": "bass", "iVocals": "vocals",
    "iDrums": "drums", "iOther": "other stem", "iBrightness": "brightness curve",
    "iBarPhase": "bar phase", "iPhrasePhase": "phrase phase",
    "iSectionProgress": "section progress", "iBeat": "beat phase",
    "beat_pulse": "beat", "downbeat_pulse": "downbeat",
    AUDIO_RMS_SOURCE: "audio level",
}

MAX_LAG = 3
MAX_WIDTH = 256
FRAME_EXTENSIONS = {".png", ".tif", ".tiff", ".exr"}
EFFECT_R = 0.3       # |r| at or above: a visible effect
WEAK_R = 0.15        # |r| below: no visible effect
JITTER_HIGH = 0.3
JITTER_MODERATE = 0.15
QUIET_ENERGY = 0.1
LOUD_ENERGY = 0.5
EVENT_WINDOW = 2     # frames: a motion burst within this of an onset is "caused"
_EPS = 1e-9


class ScorecardError(ValueError):
    """Raised for inputs the scorecard can't score (clear, user-facing)."""


# ---------------------------------------------------------------- frames ----

_NUM_RE = re.compile(r"(\d+)")


def _natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in _NUM_RE.split(name)]


def _frame_number(path: Path) -> Optional[int]:
    nums = _NUM_RE.findall(path.stem)
    return int(nums[-1]) if nums else None


def list_frames(frames_dir: Path) -> Tuple[List[Path], List[int]]:
    """Frame files sorted by frame number (natural sort) + their frame numbers.

    Frame numbers come from the last digit group in each file name; when any
    file lacks one (or they collide) the files are numbered 0..n-1 instead.
    """
    frames_dir = Path(frames_dir)
    if not frames_dir.is_dir():
        raise ScorecardError(f"frames directory not found: {frames_dir}")
    files = [p for p in frames_dir.iterdir()
             if p.is_file() and p.suffix.lower() in FRAME_EXTENSIONS]
    nums = [_frame_number(p) for p in files]
    if files and all(n is not None for n in nums) and len(set(nums)) == len(nums):
        order = sorted(range(len(files)), key=lambda i: (nums[i], _natural_key(files[i].name)))
        return [files[i] for i in order], [int(nums[i]) for i in order]
    files.sort(key=lambda p: _natural_key(p.name))
    return files, list(range(len(files)))


def box_downsample(img: np.ndarray, max_width: int = MAX_WIDTH) -> np.ndarray:
    """Integer box-filter downsample so the width is <= max_width."""
    h, w = img.shape[:2]
    k = max(1, math.ceil(w / max_width))
    if k == 1:
        return img
    hh, ww = (h // k) * k, (w // k) * k
    if hh == 0:  # very short, very wide: filter horizontally only
        return img[:, :ww].reshape(h, ww // k, k, *img.shape[2:]).mean(axis=2)
    img = img[:hh, :ww]
    return img.reshape(hh // k, k, ww // k, k, *img.shape[2:]).mean(axis=(1, 3))


def to_rgb_float(img: np.ndarray) -> np.ndarray:
    """Loaded image -> float32 HxWx3 (integers normalised by dtype max)."""
    img = np.asarray(img)
    if img.dtype.kind in ("u", "i"):
        out = img.astype(np.float32) / float(np.iinfo(img.dtype).max)
    else:
        out = img.astype(np.float32)
    if out.ndim == 2:
        out = np.repeat(out[:, :, None], 3, axis=2)
    elif out.shape[2] == 1:
        out = np.repeat(out, 3, axis=2)
    elif out.shape[2] == 2:  # luminance + alpha
        out = np.repeat(out[:, :, :1], 3, axis=2)
    else:
        out = out[:, :, :3]
    return np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)


def load_frame(path: Path, max_width: int = MAX_WIDTH) -> np.ndarray:
    """Read one frame (PNG/TIFF/EXR via imageio, as render.py writes them)."""
    import imageio.v3 as iio
    return box_downsample(to_rgb_float(iio.imread(str(path))), max_width)


# ------------------------------------------------------------- features ----

def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _hue_sat(rgb: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hue in turns (0..1), HSV saturation, value."""
    rgb = np.clip(rgb, 0.0, None)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(axis=-1)
    mn = rgb.min(axis=-1)
    d = mx - mn
    safe = np.where(d > _EPS, d, 1.0)
    h = np.where(mx == r, ((g - b) / safe) % 6.0,
                 np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0))
    h = np.where(d > _EPS, h / 6.0, 0.0)
    s = np.where(mx > _EPS, d / np.where(mx > _EPS, mx, 1.0), 0.0)
    return h, s, mx


def frame_features(frames: Iterable[np.ndarray],
                   sat_min: float = 0.2, val_min: float = 0.05) -> Dict[str, np.ndarray]:
    """L/M/H per frame. M[0] and H[0] are NaN (no previous frame)."""
    L: List[float] = []
    M: List[float] = [math.nan]
    H: List[float] = [math.nan]
    prev = None
    prev_hsv = None
    for rgb in frames:
        L.append(float(_luma(rgb).mean()))
        hsv = _hue_sat(rgb)
        if prev is not None:
            if prev.shape != rgb.shape:
                raise ScorecardError("frames have different sizes")
            M.append(float(np.abs(rgb - prev).mean()))
            h0, s0, v0 = prev_hsv
            h1, s1, v1 = hsv
            ok = (s0 > sat_min) & (s1 > sat_min) & (v0 > val_min) & (v1 > val_min)
            if ok.any():
                dh = (h1 - h0 + 0.5) % 1.0 - 0.5
                H.append(float(np.abs(dh[ok]).mean()))
            else:
                H.append(0.0)
        prev, prev_hsv = rgb, hsv
    n = len(L)
    return {"L": np.asarray(L, dtype=np.float64),
            "M": np.asarray(M[:n], dtype=np.float64),
            "H": np.asarray(H[:n], dtype=np.float64)}


def load_features(files: Sequence[Path]) -> Tuple[Dict[str, np.ndarray], Tuple[int, int]]:
    """Stream frames from disk into features (one frame in memory at a time).
    Returns the features and the analysis (width, height)."""
    shape = [0, 0]

    def gen():
        for p in files:
            f = load_frame(p)
            shape[0], shape[1] = f.shape[1], f.shape[0]
            yield f

    feats = frame_features(gen())
    return feats, (shape[0], shape[1])


# ---------------------------------------------------------- correlation ----

def pearson(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Pearson r over pairs where both are finite; None if undefined."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return None
    x, y = x[ok], y[ok]
    x = x - x.mean()
    y = y - y.mean()
    sx, sy = math.sqrt(float((x * x).sum())), math.sqrt(float((y * y).sum()))
    if sx < 1e-9 * max(1.0, len(x)) or sy < 1e-9 * max(1.0, len(y)):
        return None
    return float(np.clip((x * y).sum() / (sx * sy), -1.0, 1.0))


def lagged_correlation(source: np.ndarray, feature: np.ndarray,
                       max_lag: int = MAX_LAG) -> Tuple[Optional[float], Optional[int]]:
    """Best (max |r|) correlation of feature[t] vs source[t + lag], |lag| <= max_lag.

    Ties go to the smaller |lag| (lag 0 first).
    """
    n = min(len(source), len(feature))
    best_r: Optional[float] = None
    best_lag: Optional[int] = None
    lags = [0]
    for k in range(1, max_lag + 1):
        lags += [-k, k]
    for lag in lags:
        lo, hi = max(0, -lag), min(n, n - lag)
        if hi - lo < 3:
            continue
        r = pearson(source[lo + lag:hi + lag], feature[lo:hi])
        if r is None:
            continue
        if best_r is None or abs(r) > abs(best_r) + 1e-6:
            best_r, best_lag = r, lag
    return best_r, best_lag


def positive_derivative(x: np.ndarray) -> np.ndarray:
    d = np.full(len(x), np.nan)
    if len(x) > 1:
        d[1:] = np.maximum(0.0, np.diff(np.asarray(x, dtype=np.float64)))
    return d


def score_sources(sources: Dict[str, np.ndarray], feats: Dict[str, np.ndarray],
                  max_lag: int = MAX_LAG) -> Dict[str, Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, series in sources.items():
        series = np.asarray(series, dtype=np.float64)
        variants = [("value", series)]
        if name in IMPULSIVE_SOURCES:
            variants.append(("onset", positive_derivative(series)))
        per: Dict[str, Dict[str, Any]] = {}
        for fk in FEATURES:
            best = {"r": None, "lag": None, "via": None}
            for via, s in variants:
                r, lag = lagged_correlation(s, feats[fk], max_lag)
                if r is not None and (best["r"] is None or abs(r) > abs(best["r"]) + 1e-6):
                    best = {"r": round(r, 4), "lag": lag, "via": via}
            per[fk] = best
        out[name] = per
    return out


# ----------------------------------------------------------- jitter etc ----

def motion_spikes(M: np.ndarray) -> np.ndarray:
    """Boolean mask of frames whose motion is > median + 3·MAD."""
    M = np.asarray(M, dtype=np.float64)
    ok = np.isfinite(M)
    mask = np.zeros(len(M), dtype=bool)
    if ok.sum() < 3:
        return mask
    v = M[ok]
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    thresh = med + 3.0 * mad
    floor = max(1e-4, 1e-3 * float(v.max()))  # numerical noise is not motion
    mask[ok] = (v > thresh) & (v - med > floor)
    return mask


def jitter_score(M: np.ndarray, event_frames: Sequence[int],
                 window: int = EVENT_WINDOW) -> Dict[str, Any]:
    """Fraction of motion energy in bursts with no musical cause.

    Contiguous spike frames form a burst; a burst is caused when an onset or
    beat lands within ±window frames of its first frame (the tail of a decay
    after a hit is part of that hit's burst). jitter = motion in uncaused
    bursts / total motion.
    """
    M = np.asarray(M, dtype=np.float64)
    total = float(np.nansum(M))
    spikes = motion_spikes(M)
    events = np.asarray(sorted(set(int(e) for e in event_frames)), dtype=np.int64)
    bursts = caused = 0
    uncaused_energy = 0.0
    i, n = 0, len(M)
    while i < n:
        if not spikes[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and spikes[j + 1]:
            j += 1
        bursts += 1
        hit = events.size > 0 and bool(np.any(np.abs(events - i) <= window))
        if hit:
            caused += 1
        else:
            uncaused_energy += float(np.nansum(M[i:j + 1]))
        i = j + 1
    value = uncaused_energy / total if total > _EPS else 0.0
    return {"value": round(value, 4), "bursts": bursts, "uncaused_bursts": bursts - caused}


def dynamic_range(energy: Optional[np.ndarray], feats: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """Brightness/motion in quiet (energy < 0.1) vs loud (energy >= 0.5) frames."""
    out: Dict[str, Any] = {"quiet_frames": 0, "loud_frames": 0,
                           "L_quiet": None, "L_loud": None,
                           "M_quiet": None, "M_loud": None,
                           "motion_ratio": None, "brightness_delta": None,
                           "verdict": "n/a"}
    if energy is None:
        return out
    e = np.asarray(energy, dtype=np.float64)
    quiet, loud = e < QUIET_ENERGY, e >= LOUD_ENERGY
    out["quiet_frames"], out["loud_frames"] = int(quiet.sum()), int(loud.sum())
    if not quiet.any() or not loud.any():
        return out

    def m(x, mask):
        v = x[mask & np.isfinite(x)]
        return float(v.mean()) if v.size else None

    Lq, Ll = m(feats["L"], quiet), m(feats["L"], loud)
    Mq, Ml = m(feats["M"], quiet), m(feats["M"], loud)
    out.update(L_quiet=_r4(Lq), L_loud=_r4(Ll), M_quiet=_r4(Mq), M_loud=_r4(Ml))
    if Lq is not None and Ll is not None:
        out["brightness_delta"] = round(Ll - Lq, 4)
    Mq, Ml = Mq or 0.0, Ml or 0.0
    ratio = round(Ml / Mq, 3) if Mq > 1e-6 else None   # None: quiet is still
    out["motion_ratio"] = ratio
    delta = out["brightness_delta"] or 0.0
    moves_more = Ml > 1e-6 and (ratio is None or ratio >= 1.5)
    if moves_more or delta >= 0.05:
        out["verdict"] = "ok"
    elif (ratio is not None and ratio < 0.67) or delta <= -0.05:
        out["verdict"] = "inverted"
    else:
        out["verdict"] = "flat"
    return out


def _r4(v):
    return None if v is None else round(v, 4)


# --------------------------------------------------------------- sources ----

@dataclass
class SourceSet:
    series: Dict[str, np.ndarray]
    event_frames: List[int]
    energy: Optional[np.ndarray]
    mode: str                      # "bundle" | "audio_rms"


def pulse_series(times: Sequence[float], event_times: Sequence[float],
                 tau_fn: Callable[[float], float]) -> np.ndarray:
    """1 at each event, exponential release with time constant tau_fn(t_event)."""
    ev = np.sort(np.asarray(event_times, dtype=np.float64))
    out = np.zeros(len(times))
    if ev.size == 0:
        return out
    for i, t in enumerate(times):
        k = int(np.searchsorted(ev, t, side="right")) - 1
        if k >= 0:
            te = float(ev[k])
            out[i] = math.exp(-(t - te) / max(1e-4, tau_fn(te)))
    return out


def bundle_sources(bundle, times: Sequence[float], fps: float,
                   av_offset_ms: float = 0.0,
                   track_settings: Optional[Dict[str, dict]] = None) -> SourceSet:
    """Evaluate SCORE_SOURCES + beat/downbeat pulses at each frame time, with
    the renderer's masking (mutes/calibration) and av offset."""
    from .musicue import BundleEvaluator, bundle_uniforms, envelope_tau

    settings = track_settings or {}
    ev = BundleEvaluator(bundle, fps=fps, av_offset_ms=av_offset_ms)
    series = {name: np.zeros(len(times)) for name in SCORE_SOURCES}
    energy = np.zeros(len(times))
    for i, t in enumerate(times):
        fr = ev.evaluate_at(t)
        u = bundle_uniforms(fr, settings, t)
        for name in SCORE_SOURCES:
            series[name][i] = float(u[name])
        energy[i] = float(fr.global_energy)

    off = ev.av_offset_sec
    audio_times = [t - off for t in times]
    beats = sorted(bundle.beats, key=lambda b: b.t)
    tau = lambda te: envelope_tau(ev.local_beat_period(te))
    tempo_muted = bool((settings.get("tempo") or {}).get("mute", False))
    for name, evs in (("beat_pulse", [b.t for b in beats]),
                      ("downbeat_pulse", [b.t for b in beats if b.is_downbeat])):
        series[name] = (np.zeros(len(times)) if tempo_muted
                        else pulse_series(audio_times, evs, tau))

    onset_times = [b.t for b in beats]
    for events in bundle.drums.values():
        onset_times += [o.t for o in events]
    event_frames = [int(round((te + off) * fps)) for te in onset_times]
    return SourceSet(series=series, event_frames=event_frames, energy=energy, mode="bundle")


def audio_rms_series(audio_path: Path, times: Sequence[float], fps: float) -> np.ndarray:
    """Per-frame RMS (1/fps window centred on each frame time), normalised 0..1."""
    from .audio import AudioProcessor

    proc = AudioProcessor(Path(audio_path), fps)
    samples = np.asarray(proc.data.samples, dtype=np.float64)
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    sr = proc.data.sample_rate
    half = max(1, int(sr / fps / 2))
    out = np.zeros(len(times))
    for i, t in enumerate(times):
        c = int(round(t * sr))
        chunk = mono[max(0, c - half):max(0, c + half)]
        out[i] = math.sqrt(float((chunk * chunk).mean())) if chunk.size else 0.0
    peak = float(out.max()) if out.size else 0.0
    return out / peak if peak > _EPS else out


def rms_sources(audio_path: Path, times: Sequence[float], fps: float) -> SourceSet:
    rms = audio_rms_series(audio_path, times, fps)
    # Onset proxy: sharp rises of the level.
    d = positive_derivative(rms)
    events = [int(round(times[i] * fps)) for i in np.nonzero(motion_spikes(d))[0]]
    return SourceSet(series={AUDIO_RMS_SOURCE: rms}, event_frames=events,
                     energy=rms, mode="audio_rms")


# --------------------------------------------------------------- summary ----

def _label(name: str) -> str:
    return SOURCE_LABELS.get(name, name)


def _best_feature(per: Dict[str, Dict[str, Any]]):
    best = None
    for fk in FEATURES:
        r = per[fk]["r"]
        if r is not None and (best is None or abs(r) > abs(per[best]["r"])):
            best = fk
    return best


def summary_lines(result: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    ranked = []
    silent = []
    for name, per in result["sources"].items():
        if not result.get("source_active", {}).get(name, True):
            continue
        fk = _best_feature(per)
        if fk is None:
            silent.append(name)
            continue
        ranked.append((abs(per[fk]["r"]), name, fk))
    ranked.sort(reverse=True)
    for strength, name, fk in ranked:
        e = result["sources"][name][fk]
        via = " on onsets" if e["via"] == "onset" else ""
        if strength >= EFFECT_R:
            lines.append(f"{_label(name)} → {FEATURE_NAMES[fk]} r={e['r']:.2f} "
                         f"(lag {e['lag']}){via}")
        elif strength >= WEAK_R:
            lines.append(f"{_label(name)}: weak effect on {FEATURE_NAMES[fk]} "
                         f"r={e['r']:.2f} (lag {e['lag']})")
        else:
            silent.append(name)
    for name in silent:
        lines.append(f"{_label(name)}: no visible effect")
    if not ranked:
        lines.insert(0, "no visible reaction to any musical source")

    j = result["jitter"]["value"]
    level = "high" if j >= JITTER_HIGH else "moderate" if j >= JITTER_MODERATE else "low"
    lines.append(f"jitter {j:.2f}: {level}")

    dr = result["dynamic_range"]
    v = dr["verdict"]
    if v == "n/a":
        lines.append("loud vs quiet: not enough quiet and loud passages to compare")
    else:
        ratio = dr["motion_ratio"]
        if ratio is not None:
            rtxt = f"motion ×{ratio:.1f}"
        elif (dr["M_loud"] or 0.0) > 1e-6:
            rtxt = "motion only when loud"
        else:
            rtxt = "no motion"
        dtxt = f"brightness {dr['brightness_delta']:+.2f}"
        verdict = {"ok": "loud passages hit harder",
                   "flat": "quiet passages look like loud ones",
                   "inverted": "quiet passages are busier than loud ones"}[v]
        lines.append(f"loud vs quiet: {rtxt}, {dtxt} — {verdict}")
    return lines


# ------------------------------------------------------------ top level ----

def score_features(feats: Dict[str, np.ndarray], srcs: SourceSet) -> Dict[str, Any]:
    n = len(feats["L"])
    if n < 3:
        raise ScorecardError(f"need at least 3 frames to score, got {n}")
    sources = {k: np.asarray(v, dtype=np.float64)[:n] for k, v in srcs.series.items()}
    active = {k: bool(np.nanstd(v) > 1e-9) if v.size else False for k, v in sources.items()}
    energy = None if srcs.energy is None else np.asarray(srcs.energy)[:n]
    result: Dict[str, Any] = {
        "mode": srcs.mode,
        "sources": score_sources(sources, feats),
        "source_active": active,
        "jitter": jitter_score(feats["M"], srcs.event_frames),
        "dynamic_range": dynamic_range(energy, feats),
    }
    result["summary"] = summary_lines(result)
    return result


def score_frames(frames_dir: Path, fps: float,
                 audio_path: Optional[Path] = None,
                 bundle_path: Optional[Path] = None,
                 av_offset_ms: float = 0.0,
                 track_settings: Optional[Dict[str, dict]] = None,
                 bundle_mode: str = "auto") -> Dict[str, Any]:
    """Score a rendered frames directory against the music.

    Bundle: ``bundle_path`` if given, else the audio's sibling
    ``<stem>.musicue.json``. Without a bundle (or with bundle_mode 'raw') the
    only source is an audio RMS proxy; with neither bundle nor audio this
    raises ScorecardError.
    """
    if fps is None or fps <= 0:
        raise ScorecardError("fps must be positive")
    files, numbers = list_frames(frames_dir)
    if len(files) < 3:
        raise ScorecardError(f"need at least 3 frames to score, found {len(files)} in {frames_dir}")
    feats, (w, h) = load_features(files)
    times = [n / fps for n in numbers]
    first = numbers[0]

    bundle = None
    used_bundle = None
    audio_path = Path(audio_path) if audio_path else None
    if audio_path is not None and not audio_path.exists():
        raise ScorecardError(f"audio not found: {audio_path}")
    if bundle_mode != "raw":
        from .musicue import load_bundle, load_for_audio
        if bundle_path is not None:
            bundle_path = Path(bundle_path)
            if not bundle_path.exists():
                raise ScorecardError(f"bundle not found: {bundle_path}")
            if audio_path is not None:
                res = load_for_audio(audio_path, override_path=bundle_path)
                bundle, used_bundle = res.bundle, res.path
            else:
                bundle, used_bundle = load_bundle(bundle_path), bundle_path
        elif audio_path is not None:
            res = load_for_audio(audio_path)
            bundle, used_bundle = res.bundle, res.path

    if bundle is not None:
        srcs = bundle_sources(bundle, times, fps, av_offset_ms, track_settings)
    elif audio_path is not None:
        srcs = rms_sources(audio_path, times, fps)
    else:
        raise ScorecardError(
            "no MusiCue bundle and no audio: nothing to score against "
            "(pass --audio song.wav, and/or --bundle song.musicue.json)")
    # Events are in absolute frame numbers; features are indexed from 0.
    srcs.event_frames = [e - first for e in srcs.event_frames]

    result = score_features(feats, srcs)
    result["meta"] = {
        "frames": len(files), "first_frame": first, "fps": fps,
        "analysis_size": [w, h], "frames_dir": str(frames_dir),
        "audio": str(audio_path) if audio_path else None,
        "bundle": str(used_bundle) if used_bundle else None,
        "av_offset_ms": float(av_offset_ms or 0.0),
    }
    return result


def to_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2, allow_nan=False)


# ---------------------------------------------------------- proxy render ----

PROXY_WIDTH = 512
PROXY_HEIGHT = 256


def proxy_render_config(cfg: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
    """Pure: a fast low-res copy of a runtime render config for scoring.

    512×256, 1 temporal sample, no supersampling, 1×1 tiles, 8-bit PNG,
    mono camera, written as frame_NNNNN.png into ``output_dir``. Everything
    that drives the shader (audio, bundle, track settings, av offset,
    params, frame range) is kept.
    """
    out = dict(cfg)
    out.update(
        width=PROXY_WIDTH, height=PROXY_HEIGHT,
        temporal_samples=1, ss_scale=1.0, tiles_x=1, tiles_y=1,
        default_output_format="png", default_bit_depth="8",
        output_dir=str(output_dir), output_pattern="frame_{frame:05d}.{ext}",
        camera_stereo="none", disk_streaming=False,
    )
    mp = cfg.get("multipass")
    if isinstance(mp, dict):
        mp = json.loads(json.dumps(mp, default=str))
        bufs = mp.get("buffers") if isinstance(mp.get("buffers"), dict) else mp
        for b in bufs.values():
            if isinstance(b, dict):
                b.pop("output_format", None)
                b.pop("bit_depth", None)
        out["multipass"] = mp
    return out


def score_render_config(cfg: Dict[str, Any], frames_dir: Path) -> Dict[str, Any]:
    """Score frames rendered from ``cfg`` using the config's own music settings."""
    return score_frames(
        frames_dir, fps=float(cfg.get("fps") or 0),
        audio_path=cfg.get("audio_path") or None,
        bundle_path=cfg.get("bundle_path") or None,
        av_offset_ms=float(cfg.get("av_offset_ms") or 0.0),
        track_settings=cfg.get("track_settings") or {},
        bundle_mode=cfg.get("bundle_mode") or "auto",
    )


def render_and_score(cfg: Dict[str, Any], render: Callable[[Dict[str, Any]], None],
                     work_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Render a proxy of ``cfg`` with ``render(proxy_cfg)`` into a temp dir,
    score it, and clean up the frames."""
    with tempfile.TemporaryDirectory(prefix="cedartoy_scorecard_", dir=work_dir) as tmp:
        proxy = proxy_render_config(cfg, Path(tmp))
        render(proxy)
        return score_render_config(proxy, Path(tmp))


# ------------------------------------------------------------------ CLI ----

def add_scorecard_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "scorecard", help="Score how well rendered frames follow the music")
    p.add_argument("frames_dir", help="Directory of rendered frames (PNG/TIFF/EXR)")
    p.add_argument("--audio", help="Song audio (its sibling .musicue.json bundle is used)")
    p.add_argument("--bundle", help="MusiCue bundle JSON (overrides the audio's sibling)")
    p.add_argument("--fps", type=float, default=24.0, help="Frame rate of the frames (default 24)")
    p.add_argument("--av-offset-ms", type=float, default=0.0,
                   help="A/V offset the frames were rendered with")
    p.add_argument("--track-settings", help="JSON file of per-track settings (mutes/calibration)")
    p.add_argument("--json", dest="json_out", help="Also write the full result to this JSON file")


def print_summary(result: Dict[str, Any], out=None) -> None:
    import sys
    out = out or sys.stdout
    meta = result.get("meta", {})
    print(f"Reactivity scorecard ({meta.get('frames', '?')} frames, "
          f"{result['mode']} signals)", file=out)
    for line in result["summary"]:
        print(f"  {line}", file=out)


def _write_json(result: Dict[str, Any], path: Optional[str]) -> None:
    if path:
        Path(path).write_text(to_json(result), encoding="utf-8")


def run_scorecard_cli(args) -> int:
    import sys
    try:
        settings = {}
        if args.track_settings:
            settings = json.loads(Path(args.track_settings).read_text(encoding="utf-8"))
        result = score_frames(Path(args.frames_dir), args.fps,
                              audio_path=Path(args.audio) if args.audio else None,
                              bundle_path=Path(args.bundle) if args.bundle else None,
                              av_offset_ms=args.av_offset_ms, track_settings=settings)
    except (ScorecardError, OSError, ValueError) as exc:
        print(f"scorecard: error: {exc}", file=sys.stderr)
        return 2
    print_summary(result)
    _write_json(result, args.json_out)
    return 0


def run_render_scorecard(cfg: Dict[str, Any], render: Callable[[Dict[str, Any]], None],
                         json_out: Optional[str] = None) -> int:
    """`render ... --scorecard`: proxy render, score, print."""
    import sys
    try:
        result = render_and_score(cfg, render)
    except (ScorecardError, OSError, ValueError) as exc:
        print(f"scorecard: error: {exc}", file=sys.stderr)
        return 2
    print_summary(result)
    _write_json(result, json_out)
    return 0
