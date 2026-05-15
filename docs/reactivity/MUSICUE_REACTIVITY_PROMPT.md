# Make this GLSL shader MusiCue-reactive

You are modifying an existing Shadertoy-style GLSL shader so it reacts to a
song analyzed by MusiCue. Use ONLY the inputs documented below. Do not
invent uniforms. Prefer cookbook patterns when they fit.

## Inputs available

```glsl
// Standard Shadertoy uniforms — already present in any Shadertoy shader.
uniform float     iTime;
uniform vec3      iResolution;
uniform sampler2D iChannel0;   // 2x512 musical spectrum texture
                               //   row 0.25 (frequency): bins 0–32 kick,
                               //                         32–96 snare+tom,
                               //                         96–256 hat+cymbal,
                               //                         256–512 melodic
                               //   row 0.75 (waveform):  tempo-locked heartbeat
                               //                         0.5 + 0.5·iEnergy·sin(2π·iBeat)

// MusiCue-driven uniforms — bound by CedarToy when a bundle is loaded.
// Declaring any of these in your shader opts in to bundle-aware reactivity.
uniform float iBpm;             // current BPM
uniform float iBeat;            // [0,1] phase within current beat
uniform int   iBar;             // 0-indexed bar number
uniform float iSectionEnergy;   // [0,1] rank of current section
uniform float iEnergy;          // [0,1] global energy at this moment
```

## Rules

1. **Preserve visual identity.** Reactivity is a modulation layer on top
   of the existing shader. Do NOT change the core look.
2. **Modulate parameters the shader already exposes** — FOV, speed,
   palette weights, distortion strength, brightness, glow. Avoid
   introducing new top-level passes or new buffers.
3. **Cap modulation amplitudes** to ±20% of base value by default. The
   shader must still look recognisable when the song is silent (all
   bundle uniforms = 0). Each cookbook entry has a recommended cap —
   honor it.
4. **Use cookbook patterns where they fit.** They have been chosen for
   musical legibility. Mix-and-match is fine; rewriting them is fine if
   the shader's variable names differ — but keep the comment header so a
   reader can see which idiom each block came from.
5. **Carry the cookbook version.** Add a `// cookbook_version: 1` line
   near the top of the shader so future tooling can suggest upgrades.
6. **Emit only the modified shader, in a single fenced ```glsl block.
   No prose, no diff, no explanation.

## Cookbook (attached)

<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>

## Target shader

<paste the contents of your target shader.glsl here verbatim>
