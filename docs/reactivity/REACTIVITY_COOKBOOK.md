# MusiCue Reactivity Cookbook — v1

`cookbook_version: 1`

Reusable GLSL idioms that turn MusiCue bundle data into visual modulation.
Each entry is self-contained: it lists the inputs it reads, the parameter
it modulates, default amplitude, a recommended cap, and where to insert
it in a typical Shadertoy-style shader.

These snippets assume CedarToy has bound:

- `iChannel0` — 2×512 musical spectrum texture (row 0.25 = spectrum, row 0.75 = heartbeat)
- `iBpm` `iBeat` `iBar` `iSectionEnergy` `iEnergy` — built-in uniforms when a bundle is loaded
- `iTime` `iResolution` — standard Shadertoy uniforms

---

## kick_pulse_camera (v1)

**Does:** Forward camera nudge on kick onsets.
**Inputs:** `iChannel0` row 0 bins 0–32.
**Modulates:** ray origin or eye position.
**Default amplitude:** 0.08 · **Cap:** 0.20.
**Where:** inside your camera-position calculation, before final ray origin.

```glsl
// === kick_pulse_camera (cookbook_version 1) ===
float kickEnergy = texture(iChannel0, vec2(0.03, 0.25)).r;
vec3 cameraPushOffset = cameraForward * kickEnergy * 0.08;
// add cameraPushOffset to your ray origin / eye position
```

---

## beat_pump_zoom (v1)

**Does:** FOV / scale wobble locked to the beat phase.
**Inputs:** `iBeat`.
**Modulates:** field-of-view or uniform scale.
**Default amplitude:** 0.04 · **Cap:** 0.10.
**Where:** near your `mainImage` UV scale or FOV calculation.

```glsl
// === beat_pump_zoom (cookbook_version 1) ===
float beatWave = 0.5 + 0.5 * sin(6.2831853 * iBeat - 1.5707963);
float zoomMul = 1.0 + beatWave * 0.04;
vec2 uv = (fragCoord / iResolution.xy - 0.5) * zoomMul + 0.5;
```

---

## section_palette_shift (v1)

**Does:** Advance the palette index by 1 step per section, eased.
**Inputs:** `iBar`, `iSectionEnergy`.
**Modulates:** palette lookup / hue rotation.
**Default amplitude:** 1.0 (one palette step per section).
**Where:** wherever you compute hue or palette index.

```glsl
// === section_palette_shift (cookbook_version 1) ===
float palette = float(iBar / 8) + iSectionEnergy * 0.5;
// Use palette as input to your existing palette function or hue rotation.
// Example: vec3 col = palette3(palette);
```

---

## energy_brightness_lift (v1)

**Does:** Multiplies final color by an energy-driven scalar.
**Inputs:** `iEnergy`.
**Modulates:** final fragColor.
**Default amplitude:** brightness range [0.9, 1.15] · **Cap:** [0.8, 1.30].
**Where:** at the end of `mainImage`, just before `fragColor = …`.

```glsl
// === energy_brightness_lift (cookbook_version 1) ===
col *= mix(0.9, 1.15, iEnergy);
```

---

## bar_anchored_strobe (v1)

**Does:** Single bright frame on every Nth downbeat, gated by section energy.
**Inputs:** `iBar`, `iBeat`, `iSectionEnergy`.
**Modulates:** additive white flash.
**Default amplitude:** 0.5 (white add) · **Cap:** 1.0.
**Where:** at the end of `mainImage`.

```glsl
// === bar_anchored_strobe (cookbook_version 1) ===
bool onBarStart = iBeat < 0.04 && (iBar % 4) == 0;
if (onBarStart && iSectionEnergy > 0.6) {
    col += vec3(0.5);
}
```

---

## melodic_glow_tint (v1)

**Does:** High-bin melodic energy modulates emissive tint on bright pixels.
**Inputs:** `iChannel0` row 0 bins 256–512.
**Modulates:** color tint where luminance > 0.6.
**Default amplitude:** 0.2 tint mix · **Cap:** 0.45.
**Where:** after primary shading, before final write.

```glsl
// === melodic_glow_tint (cookbook_version 1) ===
float mid = texture(iChannel0, vec2(0.75, 0.25)).r;
vec3 tint = vec3(1.0, 0.6, 0.8);
float lum = dot(col, vec3(0.299, 0.587, 0.114));
if (lum > 0.6) {
    col = mix(col, col * tint, clamp(mid, 0.0, 1.0) * 0.2);
}
```

---

## hat_grain (v1)

**Does:** Hi-hat energy adds film-grain density to the final image.
**Inputs:** `iChannel0` row 0 bins 96–256.
**Modulates:** additive noise.
**Default amplitude:** 0.04 · **Cap:** 0.10.
**Where:** at the end of `mainImage`.

```glsl
// === hat_grain (cookbook_version 1) ===
float hat = texture(iChannel0, vec2(0.35, 0.25)).r;
float n = fract(sin(dot(fragCoord, vec2(12.9898, 78.233))) * 43758.5453);
col += (n - 0.5) * hat * 0.04;
```
