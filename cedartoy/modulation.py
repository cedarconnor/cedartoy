"""Modulation matrix: route musical signals into a shader's ``@param`` knobs.

A shader only exposes knobs (``// @param name float default min max "Label"``);
routes map a musical source (``MOD_SOURCES``) onto a float param with
tempo-aware shaping:

    source (0..1, post track-mute/calibration)
      -> asymmetric one-pole envelope follower (attack/release in BEATS of the
         local beat period; run offline on a dense grid)
      -> curve (linear | ease_in | ease_out | smoothstep | pow2 | sqrt)
      -> x depth

``add`` routes sum onto the base value (the UI slider / ``shader_parameters``)
and the result is clamped to the @param min/max. ``integrate`` routes add
``depth * integral(shaped dt)`` (seconds) on top and are NOT clamped: they are
meant for phases/offsets (rotation angle, scroll offset) whose *speed* should
follow the music without jitter.

Default routes can live in the shader source next to the params::

    // @mod warp_amount <- iKick depth=0.5 release=0.5 curve=ease_out
    // @mod swirl_phase <- iEnergy depth=1.5 mode=integrate

A render config's ``modulation_routes`` replaces these defaults whenever it is
present (even as an empty list); a missing / ``None`` value means "use the
shader's @mod defaults".

``ModulationEvaluator`` is the single canonical evaluator: the renderer calls
``evaluate_at(t)`` at every temporal sample and the preview binds per-frame
values produced by ``series`` (served by ``/api/modulation/series``).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field, field_validator

from .musicue import (
    BundleEvaluator, MusiCueBundle, bundle_uniforms, envelope_tau, envelope_value,
)
from .shader import parse_params

# Scalar bundle uniforms usable as modulation sources, plus derived pulses.
MOD_SOURCES: Tuple[str, ...] = (
    "iEnergy", "iEnergyFast", "iSectionEnergy", "iBuild",
    "iKick", "iSnare", "iHat",
    "iBass", "iVocals", "iDrums", "iOther",
    "iBrightness", "iBarPhase", "iPhrasePhase", "iSectionProgress", "iBeat",
    "beat_pulse", "downbeat_pulse",
)
CURVES: Tuple[str, ...] = ("linear", "ease_in", "ease_out", "smoothstep", "pow2", "sqrt")
MODES: Tuple[str, ...] = ("add", "integrate")

# Dense evaluation grid: at least this many Hz, and at least 4x the fps.
MIN_GRID_HZ = 200.0
GRID_FPS_FACTOR = 4.0

CurveName = Literal["linear", "ease_in", "ease_out", "smoothstep", "pow2", "sqrt"]
ModeName = Literal["add", "integrate"]


class Route(BaseModel):
    id: str = ""
    target: str
    source: str
    depth: float = 1.0
    curve: CurveName = "linear"
    attack_beats: float = 0.0
    release_beats: float = 0.0
    mode: ModeName = "add"
    enabled: bool = True

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in MOD_SOURCES:
            raise ValueError(f"unknown modulation source {value!r}")
        return value

    @field_validator("attack_beats", "release_beats")
    @classmethod
    def _non_negative(cls, value: float, info) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{info.field_name} must be >= 0")
        return value

    @field_validator("depth")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("depth must be finite")
        return value


# ---- @mod parsing ----

_MOD_LINE_RE = re.compile(r"^[ \t]*//[ \t]*@mod\b(.*)$", re.MULTILINE)
_MOD_BODY_RE = re.compile(r"^\s+(\w+)\s*<-\s*(\w+)((?:\s+[A-Za-z_]+=\S+)*)\s*$")
_MOD_KEYS = {
    "depth": "depth", "curve": "curve", "mode": "mode", "enabled": "enabled",
    "attack": "attack_beats", "attack_beats": "attack_beats",
    "release": "release_beats", "release_beats": "release_beats",
}
_BOOL = {"true": True, "1": True, "yes": True, "on": True,
         "false": False, "0": False, "no": False, "off": False}


def parse_mod_comments(src: str) -> List[Route]:
    """Default routes from ``// @mod target <- source key=value ...`` lines.

    Malformed lines (no ``<-``, unknown source/curve/mode/key, bad numbers)
    are ignored. Ids are ``mod1``, ``mod2``, ... in source order.
    """
    routes: List[Route] = []
    for m in _MOD_LINE_RE.finditer(src or ""):
        body = _MOD_BODY_RE.match(m.group(1))
        if not body:
            continue
        target, source, rest = body.groups()
        fields: Dict[str, Any] = {"target": target, "source": source}
        ok = True
        for token in rest.split():
            key, _, value = token.partition("=")
            field = _MOD_KEYS.get(key.lower())
            if field is None or field in fields:
                ok = False
                break
            if field == "enabled":
                if value.lower() not in _BOOL:
                    ok = False
                    break
                fields[field] = _BOOL[value.lower()]
            else:
                fields[field] = value
        if not ok:
            continue
        try:
            route = Route(id=f"mod{len(routes) + 1}", **fields)
        except (ValueError, TypeError):
            continue
        routes.append(route)
    return routes


def coerce_routes(routes: Optional[Iterable[Any]]) -> Optional[List[Route]]:
    """Route models from dicts/models; None stays None (= use @mod defaults)."""
    if routes is None:
        return None
    return [r if isinstance(r, Route) else Route.model_validate(r) for r in routes]


def resolve_routes(config_routes: Optional[Iterable[Any]], shader_src: str) -> List[Route]:
    """Config routes replace @mod defaults whenever present (even if empty)."""
    coerced = coerce_routes(config_routes)
    if coerced is not None:
        return coerced
    return parse_mod_comments(shader_src)


# ---- shaping ----

def apply_curve(x: np.ndarray, curve: str) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    if curve == "linear":
        return x
    if curve == "ease_in":
        return 1.0 - np.cos(0.5 * math.pi * x)
    if curve == "ease_out":
        return np.sin(0.5 * math.pi * x)
    if curve == "smoothstep":
        return x * x * (3.0 - 2.0 * x)
    if curve == "pow2":
        return x * x
    if curve == "sqrt":
        return np.sqrt(x)
    raise ValueError(f"unknown curve {curve!r}")


def envelope_follow(x: np.ndarray, dt: float, beat_period: np.ndarray,
                    attack_beats: float, release_beats: float) -> np.ndarray:
    """Asymmetric one-pole follower on a uniform grid of step ``dt``.

    The time constant is ``attack_beats * beat_period`` while rising and
    ``release_beats * beat_period`` while falling; 0 beats = instant.
    Starts at x[0].
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n == 0 or (attack_beats <= 0 and release_beats <= 0):
        return x.copy()
    period = np.maximum(np.asarray(beat_period, dtype=np.float64), 1e-6)

    def coef(beats: float) -> np.ndarray:
        if beats <= 0:
            return np.ones(n)
        return 1.0 - np.exp(-dt / (beats * period))

    a_up, a_dn = coef(attack_beats), coef(release_beats)
    out = np.empty(n)
    y = float(x[0])
    xs = x.tolist()
    up = a_up.tolist()
    dn = a_dn.tolist()
    for i in range(n):
        xi = xs[i]
        y += (xi - y) * (up[i] if xi > y else dn[i])
        out[i] = y
    return out


# ---- source table ----

class SourceTable:
    """Every MOD_SOURCE sampled on a dense uniform grid in VIDEO time.

    Independent of routes, so the API can cache it across route edits.
    Track settings (mute/gain/threshold) are applied, values clipped to 0..1.
    """

    def __init__(self, bundle: MusiCueBundle, fps: float,
                 track_settings: Optional[Dict[str, Any]] = None,
                 av_offset_ms: float = 0.0, duration_sec: Optional[float] = None):
        if fps <= 0:
            raise ValueError("fps must be positive")
        settings = _settings_dicts(track_settings)
        ev = BundleEvaluator(bundle, fps=fps, av_offset_ms=av_offset_ms)
        self.evaluator = ev
        rate = max(MIN_GRID_HZ, GRID_FPS_FACTOR * float(fps))
        end = float(duration_sec) if duration_sec and duration_sec > 0 else (
            float(bundle.duration_sec) + abs(ev.av_offset_sec))
        end = max(end, 1.0 / rate) + 1.0 / fps
        n = int(math.ceil(end * rate)) + 1
        self.dt = 1.0 / rate
        self.times = np.arange(n, dtype=np.float64) * self.dt
        cols: Dict[str, List[float]] = {s: [] for s in MOD_SOURCES}
        period: List[float] = []
        tempo = settings.get("tempo") or {}
        tempo_muted = bool(tempo.get("mute", False))
        beats_per_bar = ev._beats_per_bar
        uniform_sources = [s for s in MOD_SOURCES if s.startswith("i")]
        for t in self.times.tolist():
            u = bundle_uniforms(ev.evaluate_at(t), settings, t)
            for s in uniform_sources:
                cols[s].append(u[s])
            tm = t - ev.av_offset_sec
            bp = ev.local_beat_period(tm)
            period.append(bp)
            if tempo_muted:
                cols["beat_pulse"].append(0.0)
                cols["downbeat_pulse"].append(0.0)
                continue
            beat_since = _fract(ev._beat_grid.count(tm)) * bp
            cols["beat_pulse"].append(envelope_value(beat_since, envelope_tau(bp), 1.0))
            if ev._downbeat_times:
                bar_period = ev._bar_grid.period_at(tm)
            else:
                bar_period = bp * beats_per_bar
            bar_since = _fract(ev._bar_clock(tm)) * bar_period
            cols["downbeat_pulse"].append(envelope_value(bar_since, envelope_tau(bp), 1.0))
        self.values: Dict[str, np.ndarray] = {
            s: np.clip(np.nan_to_num(np.asarray(v, dtype=np.float64)), 0.0, 1.0)
            for s, v in cols.items()
        }
        self.beat_period = np.asarray(period, dtype=np.float64)


def _fract(x: float) -> float:
    f = x - math.floor(x)
    return 0.0 if f >= 1.0 else f


def _settings_dicts(track_settings: Optional[Dict[str, Any]]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for k, v in (track_settings or {}).items():
        if hasattr(v, "model_dump"):
            v = v.model_dump()
        out[k] = dict(v or {})
    return out


def float_params(params: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {p["name"]: p for p in params if p.get("type") == "float"}


class ModulationEvaluator:
    """Routes + bundle -> modulated @param values at any video time.

    ``params`` is the parsed @param list (``cedartoy.shader.parse_params``);
    only float params are modulated. ``shader_parameters`` provides the base
    values (falling back to each param's default). Routes targeting unknown
    or non-float params, and disabled routes, are ignored.
    """

    def __init__(self, bundle: MusiCueBundle, fps: float,
                 routes: Iterable[Any], params: Sequence[Dict[str, Any]],
                 track_settings: Optional[Dict[str, Any]] = None,
                 av_offset_ms: float = 0.0,
                 shader_parameters: Optional[Dict[str, Any]] = None,
                 duration_sec: Optional[float] = None,
                 source_table: Optional[SourceTable] = None):
        self.fps = float(fps)
        self.params = float_params(params)
        self.routes = [r for r in (coerce_routes(routes) or [])
                       if r.enabled and r.target in self.params]
        self.table = source_table or SourceTable(
            bundle, fps, track_settings, av_offset_ms, duration_sec)
        base_values = shader_parameters or {}
        self.base: Dict[str, float] = {}
        self.lo: Dict[str, float] = {}
        self.hi: Dict[str, float] = {}
        for name, p in self.params.items():
            try:
                self.base[name] = float(base_values.get(name, p["default"]))
            except (TypeError, ValueError):
                self.base[name] = float(p["default"])
            lo, hi = float(p["min"]), float(p["max"])
            self.lo[name], self.hi[name] = min(lo, hi), max(lo, hi)

        tab = self.table
        n = len(tab.times)
        self._add: Dict[str, np.ndarray] = {}
        self._int: Dict[str, np.ndarray] = {}
        for r in self.routes:
            shaped = apply_curve(envelope_follow(
                tab.values[r.source], tab.dt, tab.beat_period,
                r.attack_beats, r.release_beats), r.curve)
            if r.mode == "add":
                acc = self._add.setdefault(r.target, np.zeros(n))
                acc += r.depth * shaped
            else:
                cum = np.concatenate([[0.0], np.cumsum(
                    0.5 * (shaped[1:] + shaped[:-1]) * tab.dt)])
                acc = self._int.setdefault(r.target, np.zeros(n))
                acc += r.depth * cum
        # Integrate tables extrapolate past the grid with the last slope.
        self._int_slope = {
            k: (v[-1] - v[-2]) / tab.dt if n > 1 else 0.0 for k, v in self._int.items()
        }
        self.targets: List[str] = [name for name in self.params
                                   if name in self._add or name in self._int]

    def _values(self, t: np.ndarray) -> Dict[str, np.ndarray]:
        grid = self.table.times
        out: Dict[str, np.ndarray] = {}
        for name in self.targets:
            v = np.full(t.shape, self.base[name])
            if name in self._add:
                v = v + np.interp(t, grid, self._add[name])
            v = np.clip(v, self.lo[name], self.hi[name])
            if name in self._int:
                cum = self._int[name]
                iv = np.interp(t, grid, cum)
                over = t > grid[-1]
                if np.any(over):
                    iv = np.where(over, cum[-1] + self._int_slope[name] * (t - grid[-1]), iv)
                v = v + iv
            out[name] = v
        return out

    def evaluate_at(self, t: float) -> Dict[str, float]:
        """Modulated values for every routed float param at video time t."""
        vals = self._values(np.asarray([float(t)], dtype=np.float64))
        return {k: float(v[0]) for k, v in vals.items()}

    def series(self, fps: float, n_frames: int) -> Dict[str, List[float]]:
        """Per-frame values (frame f at t = f / fps) for the preview."""
        t = np.arange(max(0, int(n_frames)), dtype=np.float64) / float(fps)
        return {k: v.tolist() for k, v in self._values(t).items()}


# ---- job helpers ----

def job_shader_sources(job: Any) -> List[str]:
    """Source text of every pass shader in a RenderJob (main first)."""
    paths: List[Path] = [Path(job.shader_main)]
    graph = getattr(job, "multipass_graph", None)
    if graph is not None:
        for buf in graph.buffers.values():
            if Path(buf.shader) not in paths:
                paths.append(Path(buf.shader))
    out = []
    for p in paths:
        try:
            out.append(p.read_text(encoding="utf-8"))
        except OSError:
            continue
    return out


def job_params(job: Any) -> List[Dict[str, Any]]:
    """@param declarations across all of a job's pass shaders (first wins)."""
    seen: Dict[str, Dict[str, Any]] = {}
    for src in job_shader_sources(job):
        for p in parse_params(src):
            seen.setdefault(p["name"], p)
    return list(seen.values())


def build_job_modulation(job: Any, bundle: MusiCueBundle,
                         duration_sec: Optional[float] = None
                         ) -> Optional[ModulationEvaluator]:
    """Evaluator for a RenderJob, or None when no route applies."""
    params = job_params(job)
    if not float_params(params):
        return None
    srcs = job_shader_sources(job)
    routes = resolve_routes(getattr(job, "modulation_routes", None), "\n".join(srcs))
    if not routes:
        return None
    ev = ModulationEvaluator(
        bundle, job.fps, routes, params,
        track_settings=getattr(job, "track_settings", None),
        av_offset_ms=getattr(job, "av_offset_ms", 0.0) or 0.0,
        shader_parameters=getattr(job, "shader_parameters", None),
        duration_sec=duration_sec,
    )
    return ev if ev.targets else None
