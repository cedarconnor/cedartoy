# MusiCue Reactivity Cookbook — v3

`cookbook_version: 3`

A vocabulary of *kinds of mappings* between musical signals and visual
parameters. **This is not a menu to pick from.** Each entry sketches a
relationship that has read well in practice; copy one, adapt it to the
shader's own variables, combine several, or invent something better
when the shader's structure suggests it.

Available CedarToy bindings:

- `iChannel0` — 2×512 musical spectrum texture
  (row 0.25 = frequency, row 0.75 = tempo-locked heartbeat). Row-0 bands:
  low (x < 0.0625) = kick + bass, low-mid = snare + tom, mid-high = hats +
  cymbals, high (x > 0.5) = vocals + other.
- `iBpm` `iBeat` `iBar` `iSectionEnergy` `iSectionId` `iEnergy` — bundle uniforms
  (`iSectionId` is a stable int per section label — all verses share one id,
  all choruses another; use it when a change should happen on
  verse/chorus/bridge boundaries.)
- Musical-structure uniforms (all `float`, declare the ones you use):

  | Uniform | Range | Meaning |
  |---|---|---|
  | `iBeatClock` | continuous | Beat count from the real beat grid (index + phase). Monotonic, phase-locked to actual beats even when tempo drifts. `fract(iBeatClock)` = beat phase, `floor` = beat index. Negative before the first beat. |
  | `iBarPhase` | 0..1 | Position within the bar (from downbeats), continuous. |
  | `iPhrasePhase` | 0..1 | Position within the phrase (MusiCue phrases when present, else 4-bar groups). |
  | `iSectionProgress` | 0..1 | Position within the current section. |
  | `iTimeToNextSection` | seconds | Time until the next section starts (1000 when none). |
  | `iBuild` | 0..1 | Anticipation ramp into higher-energy sections; drops to 0 at the drop. |
  | `iKick` `iSnare` `iHat` | 0..1 | Drum envelopes: instant attack, decay to ~10% in half a beat (tempo-relative). |
  | `iBass` `iVocals` `iDrums` `iOther` | 0..1 | Per-stem loudness (0 when the bundle has no stems). |
  | `iBrightness` | 0..1 | Spectral brightness of the mix. |
  | `iEnergyFast` | 0..1 | Short-window loudness (falls back to `iEnergy`). |
  | `iMusicTime` | seconds | Drop-in `iTime` replacement that runs faster in loud passages and slower in quiet ones (mean rate 1, monotonic, smooth). Equals `iTime` without a bundle. |

  Signals the bundle lacks are 0 (see the song data summary appended
  to the prompt), so every mapping should still look right at 0.
- `iTime` `iResolution` — standard Shadertoy

Each snippet's first line is its lineage header — keep it (or adapt
the name) when copying so a future reader can see which idiom each
block came from.

---

## Inner-loop modulations (high impact)

Shaders that raymarch, iterate, or fold are most expressive when you
modulate parameters *inside* their inner loop. The pattern itself
changes, not just its colour.

### noise_scale_breathe

Modulate the inner noise scale by `iEnergy`. Features grow denser and
finer in louder passages; the field literally morphs with the song.

```glsl
// === noise_scale_breathe (cookbook_version 2) ===
// noise scale ← iEnergy — pattern density breathes with the song
float noiseScale = mix(9.0, 15.0, iEnergy);
// ...inside the loop, replace n(p*12.) with n(p*noiseScale)
```

Reads as: the visual texture changes shape, not just brightness.

### iteration_swell

Bump the loop iteration count when energy is high. Adds depth and glow
in choruses without changing the visual identity.

```glsl
// === iteration_swell (cookbook_version 2) ===
// iteration count ← iEnergy — depth swells in louder passages
int maxIter = 8 + int(iEnergy * 4.0);   // 8..12
for (int i = 0; i < maxIter; i++) { /* march */ }
```

Reads as: the image gains layers and glow on energetic passages.

### swirl_whip_on_kick

Add kick-band energy as an **additive** angle offset to a per-iteration
rotation. Each kick visibly twists the field.

**Critical:** do not multiply `iTime` by the kick (or by any volatile
audio signal). At large `iTime`, a small wobble in the multiplier
becomes many radians of angle change per frame and the field spins
chaotically — looks like jitter, not music.

```glsl
// === swirl_whip_on_kick (cookbook_version 2) ===
// rotation angle ← kick band — additive twist on each kick
float kick = texture(iChannel0, vec2(0.03, 0.25)).r;
float swirlOffset = kick * 0.6;   // radians — additive, NOT a rate
// ...inside the loop: r(sin(b.xy), iTime*1.5 + b.z*3.0 + swirlOffset)
```

Reads as: localised whip/twist motion synchronised to kicks.

### fold_strength_pulse

For IFS / mirror-fold shaders: modulate the fold offset or fold
strength by beat phase. The kaleidoscopic structure breathes.

```glsl
// === fold_strength_pulse (cookbook_version 2) ===
// fold strength ← iBeat — symmetry breathes on the beat
float foldPulse = 1.0 + 0.15 * (0.5 + 0.5 * sin(6.2832 * iBeat - 1.5708));
// ...replace p = abs(p) - 1.0 with p = abs(p) - foldPulse
```

Reads as: the symmetry pattern subtly inflates and deflates with each
beat.

---

## Camera & UV modulations

Camera, UV, and speed controls are sensitive to discontinuities. Treat
`iBeat` as a **modulo phase** that jumps from almost 1.0 back to 0.0 at
every beat. That is fine for colour pulses and loop-closed functions
where `f(0) == f(1)`, but it creates visible stutter when it directly
drives camera angle, object position, scroll speed, or accumulated time.
For smooth tempo-locked motion use `iBeatClock` (continuous, phase-locked
to the real beat grid) or `iBarPhase`, then optionally add small beat
accents on top. `iTime * iBpm / 60.0` is continuous too, but it drifts off
the real beats whenever the tempo wanders.

### kick_pulse_camera

Forward camera nudge on kick onsets. Most useful in tunnel/forward-fly
shaders where the displacement reads as a punch in the gut.

```glsl
// === kick_pulse_camera (cookbook_version 2) ===
// camera position ← kick band — punch on kick
float kickEnergy = texture(iChannel0, vec2(0.03, 0.25)).r;
vec3 cameraPushOffset = cameraForward * kickEnergy * 0.12;
// add cameraPushOffset to ray origin / eye position
```

Tip: the iChannel0 low band carries kick *and* bass; use `iKick` instead
of the texture read when you want the kick alone.

Reads as: the camera lurches forward and back with the kick. Make sure
the push is large enough to be perceived — small camera moves disappear
in noisy / busy shaders.

### beat_pump_zoom

FOV or scale wobble locked to beat phase. Better on minimalist shaders
where the wobble has space to breathe.

```glsl
// === beat_pump_zoom (cookbook_version 2) ===
// uv scale ← iBeat — global pulse on the beat
float beatWave = 0.5 + 0.5 * sin(6.2832 * iBeat - 1.5708);
float zoomMul = 1.0 + beatWave * 0.06;
vec2 uv = (fragCoord / iResolution.xy - 0.5) * zoomMul + 0.5;
```

Use 0.04–0.10. Below 0.04 it's invisible; above 0.10 it's seasick.

### camera_rock_subtle

A tiny roll of the camera (or ray direction) locked to a slow tempo
phase. Two superimposed sines at incommensurate rates so it never
sits still and never resolves to a single visible spin. Amplitudes are
deliberately small (~2°) so it reads as the *world* breathing, not as
"the camera is rotating."

**Critical:** do not use `float(iBar) + iBeat` as a continuous beat
clock. `iBeat` resets every beat, but `iBar` changes only once per bar,
so the camera angle snaps at beat boundaries inside the bar. Use a
continuous tempo clock for camera / speed / position motion.

```glsl
// === camera_rock_subtle (cookbook_version 3) ===
// ray roll ← iBeatClock — smooth sway without beat-boundary snaps
float tempoBeat = iBeatClock;                           // continuous, beat-locked
float rockEnabled = step(1.0, iBpm);                    // zero when no bundle/BPM
float rockAngle = rockEnabled * (
    sin(tempoBeat * 0.3927) * 0.030       // ~16-beat sway
  + sin(tempoBeat * 1.5708) * 0.008       // 1/4-bar nudge
);
d.xy = mat2(cos(rockAngle), -sin(rockAngle),
            sin(rockAngle),  cos(rockAngle)) * d.xy;
```

Reads as: the scene seems to gently rock with the music. Easy to miss
consciously, hard to do without once it's there. Keep total amplitude
under ~0.06 rad (~3.5°) or it starts feeling drunk.

### bar_phase_camera

Smooth, bar-locked camera drift. `iBarPhase` sweeps 0→1 across each bar
and `iBeatClock` never jumps, so the camera lands on the downbeat every
bar without a single snap. Use a loop-closed function of `iBarPhase`
(`f(0) == f(1)`) so the wrap at the downbeat is invisible.

```glsl
// === bar_phase_camera (cookbook_version 3) ===
// camera orbit ← iBarPhase + iBeatClock — smooth, lands on every downbeat
float barSwing = sin(6.2832 * iBarPhase);                // loop-closed per bar
float drift = iBeatClock / 64.0;                         // one slow turn every 64 beats
float camYaw = 6.2832 * drift + 0.08 * barSwing;
d.xz = mat2(cos(camYaw), -sin(camYaw), sin(camYaw), cos(camYaw)) * d.xz;
```

Reads as: the camera glides in time with the bar structure; the
downbeat is where each swing turns around.

### hat_shimmer

Hi-hat energy adds a radial standing-wave shimmer. More musical than
film-grain; reads as the screen vibrating with the hats.

```glsl
// === hat_shimmer (cookbook_version 2) ===
// uv displacement ← hat band — radial shimmer locked to hi-hats
float hat = texture(iChannel0, vec2(0.35, 0.25)).r;
vec2 cuv = (fragCoord - iResolution.xy * 0.5) / iResolution.y;
float shimmer = sin(length(cuv) * 40.0 - iTime * 6.0) * hat * 0.06;
col += col * shimmer;
```

Reads as: a faint chromatic vibration that intensifies on hi-hat
patterns.

---

## Speed, structure & stems

### music_time_flow

Use `iMusicTime` wherever the shader uses `iTime` for *flow speed*
(scrolling, advection, fly-through distance, noise evolution). It runs
faster in loud passages and slower in quiet ones, but it is monotonic
and smooth, so this is the **safe way to modulate speed** — never
multiply `iTime` by an audio signal (see "Patterns that almost never
read"). Without a bundle `iMusicTime == iTime`.

```glsl
// === music_time_flow (cookbook_version 3) ===
// flow clock ← iMusicTime — faster in loud passages, never jitters
float flowT = iMusicTime;              // was: iTime
vec2 flowUv = fragCoord / iResolution.y + vec2(flowT * 0.1, 0.0);
// ...use flowT everywhere the shader advected by iTime
```

Reads as: the piece surges forward in the chorus and drifts in the
breakdown, with no stutter.

### build_tension

`iBuild` ramps 0→1 over the bars before a lift into a higher-energy
section and snaps to 0 on the drop. Ramp a tension parameter (warp,
contrast, desaturation, zoom) with it so the drop releases it.

```glsl
// === build_tension (cookbook_version 3) ===
// tension ← iBuild — winds up into the drop, releases on it
float tension = iBuild * iBuild;                   // ease-in
float warpAmt = mix(0.1, 0.6, tension);
vec3 grey = vec3(dot(col, vec3(0.299, 0.587, 0.114)));
col = mix(col, grey, 0.5 * tension);               // drain colour into the drop
col *= 1.0 + 0.3 * tension;
// ...feed warpAmt into the shader's domain warp strength
```

Reads as: anticipation you can see; the drop lands as a release.

### stem_layers

Give each stem its own visual layer: bass drives large-scale warp or
scale, vocals drive glow. Both are loudness curves (smooth), so they
can go straight into shape parameters. They read 0 when the bundle has
no stems, so keep the zero case a good default.

```glsl
// === stem_layers (cookbook_version 3) ===
// scale/warp ← iBass, glow ← iVocals — each stem owns one layer
float bassScale = 1.0 + 0.25 * iBass;              // bass swells the geometry
vec2 suv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y / bassScale;
float glow = 0.4 * iVocals;
col += glow * vec3(1.0, 0.75, 0.55) * smoothstep(0.4, 1.0, length(col));
```

Reads as: low end moves the world, the voice lights it.

---

## Colour & palette modulations

### section_palette_shift

Advance a palette index per section. Pair with an actual palette
function — a bare `+ palette` term added to a sin argument has
surprisingly strong perceptual effect on rainbow-style shaders.

```glsl
// === section_palette_shift (cookbook_version 2) ===
// palette index ← section — colour mood changes per section
float palette = float(iBar / 8) + iSectionEnergy * 0.5;
// ...feed palette into hue rotation, palette3(), or sin argument
```

Reads as: each section has its own colour identity.

### section_color_wash

Tint the final image toward a per-section-type accent colour. Uses
`iSectionId` so all verses share one colour, all choruses another, all
bridges another — the wash changes only on verse/chorus/bridge
boundaries, never mid-section. Smooth; never blanks the image.

```glsl
// === section_color_wash (cookbook_version 2) ===
// final tint ← iSectionId — verse / chorus / bridge each have a colour
float sid = float(iSectionId);
vec3 accent = 0.5 + 0.5 * sin(sid * 1.7 + vec3(0.0, 2.094, 4.189));
col = mix(col, col * accent * 1.2, iSectionEnergy * 0.35);
```

Reads as: choruses pick up one colour mood, verses another, bridges
another — the shader has a section-specific identity.

### beat_phase_color_dance

Phase-rotate the per-channel sin offsets by beat phase. Each beat the
RGB phases shift, producing actively dancing colour, not just a hue
slide.

```glsl
// === beat_phase_color_dance (cookbook_version 2) ===
// per-channel phase ← iBeat — RGB phases dance on the beat
vec3 phase = vec3(3.0, 1.5, 1.0) + iBeat * vec3(0.6, 0.4, 0.8);
// ...l += (1.0 + sin(i + length(p.xy*0.1) + phase + palette)) / s
```

Reads as: subtle colour rolling on every beat, especially visible on
sin-palette shaders.

### melodic_glow_tint

High-bin melodic energy tints emissive areas. Selective: only acts
where luminance is already high.

```glsl
// === melodic_glow_tint (cookbook_version 2) ===
// emissive tint ← melodic band — bright pixels pick up melodic colour
float mid = texture(iChannel0, vec2(0.75, 0.25)).r;
vec3 tint = vec3(1.0, 0.6, 0.8);
float lum = dot(col, vec3(0.299, 0.587, 0.114));
if (lum > 0.6) {
    col = mix(col, col * tint, clamp(mid, 0.0, 1.0) * 0.25);
}
```

Reads as: the bright parts pick up the melodic line.

---

## Time-anchored events

### bar_anchored_strobe

Single bright frame on every Nth downbeat. **Use sparingly** — this is
the brightest possible cookbook idiom. Almost always prefer
`section_color_wash` instead unless you genuinely want a club strobe.

```glsl
// === bar_anchored_strobe (cookbook_version 2) ===
// additive flash ← bar % N + iSectionEnergy gate
bool onBarStart = iBeat < 0.04 && (iBar % 8) == 0;
if (onBarStart && iSectionEnergy > 0.6) {
    col += vec3(0.5);
}
```

Reads as: a hard flash on big drops. Annoying outside of drops.

### kick_displace

Instead of pushing the camera, jolt the screen-space UV on kick. Reads
as a percussive jolt rather than a camera move; works on 2D shaders
where there is no camera.

```glsl
// === kick_displace (cookbook_version 2) ===
// uv offset ← kick band — percussive jolt
float kick = texture(iChannel0, vec2(0.03, 0.25)).r;
vec2 jolt = vec2(sin(iTime*47.0), cos(iTime*53.0)) * kick * 0.02;
vec2 uv = fragCoord / iResolution.xy + jolt;
```

Reads as: the image flinches on each kick.

---

## Patterns that almost never read

These came up in early experiments. Avoid unless you have a specific
reason.

- **Brightness-only modulation on already-glowing shaders.** A ±15%
  multiply on a bloomed plasma is invisible. Modulate inner-loop
  parameters instead.
- **Pure-white additive strobes on every bar.** Reads as a broken
  monitor, not music. Gate harder, use colour, or skip the strobe.
- **Tiny camera nudges (<0.05 of scene depth) on busy shaders.** Lost
  in the noise. Either go bigger or pick a different lever.
- **Film grain as the only "audio reaction."** Static-looking noise
  doesn't read as music. Pair it with something else or use shimmer
  instead.
- **Multiplying `iTime` by a volatile audio signal.** `iTime *
  (1.5 + kick * 4.0)` looks like a clever way to speed up rotation on
  kicks but at `iTime=60s` even a 0.1 swing in the multiplier is six
  whole radians of angle change per frame. Reads as catastrophic
  jitter. **Always add audio signals to angles/positions; never use
  them as rate multipliers on accumulated time.** If you want speed to
  follow the music, swap `iTime` for `iMusicTime` (see
  `music_time_flow`) — it is integrated offline, so it stays smooth.
- **Using `iBeat` as a continuous clock for camera / speed / position.**
  `iBeat` is a phase inside the current beat; it wraps from ~1.0 back to
  0.0 every beat. `float(iBar) + iBeat` is also discontinuous because
  `iBar` increments once per bar, not once per beat. This makes camera
  roll, object position, fly-through speed, and scroll offsets visibly
  stutter on the beat. Use `iBeatClock` (or `iBarPhase` / `iPhrasePhase`)
  for smooth tempo motion, and reserve `iBeat` for loop-closed pulses
  where the value returns to the same state at phase 0 and phase 1.
- **Animating random hashes or `fract` seams with time-moving coordinates.**
  Expressions like `fract(sin(p) * 1e5)` are discontinuous. If `p`
  already moves with `iTime`, pixels cross random seams and pop between
  frames, especially at 29.97 fps. Do not feed `iTime` into a hash for
  texture animation, and do not add hash jitter after a time-moving warp.
  Use a static noise texture, filtered value noise, or a continuous
  sinusoidal micro-warp instead.
- **Assuming the Web UI preview exposes shutter / sample jitter artifacts.**
  Preview runs as a single current-time sample. Disk renders with
  `temporal_samples == 1` should also sample the center of each frame; only
  use shutter offsets and subpixel jitter when `temporal_samples >= 2`.
  If a preview is smooth but disk output stutters, inspect render-time
  sampling first before changing musical mappings.
