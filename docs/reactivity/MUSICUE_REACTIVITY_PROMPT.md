# Make this GLSL shader MusiCue-reactive

You are modifying an existing Shadertoy-style GLSL shader so it reacts to a
song analyzed by MusiCue. Your job is to find the shader's *expressive
knobs* and wire them to the music — not to apply a checklist.

## Process

1. **Read the target shader. Identify 4–8 expressive levers** — the
   parameters that, when changed, visibly alter the image. Examples vary
   per shader: noise scales, loop iteration counts, rotation rates,
   palette indices, step sizes, FOV, displacement amplitudes, glow
   thresholds, symmetry counts, fold counts. **Levers inside the inner
   loop are usually the most visually rich** — find them.

2. **Match levers to musical signals.** Which knob should breathe with
   global energy? Which should jolt on kicks? Which should slowly drift
   across sections? Pick mappings that fit *this shader's* feel. A
   raymarched noise field wants its noise scale modulated; a
   palette-driven plasma wants its palette index modulated; a
   kaleidoscope wants its symmetry count modulated; a fractal IFS wants
   its fold depth or fold strength modulated. Don't pick "brightness
   multiply" if the shader has more interesting knobs.

3. **Avoid bland modulations.** A ±15% brightness lift on a shader that
   already glows is invisible. Prefer modulations that change the
   *shape* or *motion* of the image, not just its brightness. Reserve
   global brightness/strobe effects for moments you genuinely want a
   blackout-and-flash — and even then, **a colour wash usually reads
   better than a pure white add.**

4. **Preserve visual identity.** When all bundle uniforms are zero the
   shader should look essentially like the original. Modulation is on
   top of, not a replacement for, the existing image.

5. **Don't add new top-level passes or buffers.** Stay within
   `mainImage`. No `Buffer A` / `Buffer B` simulations.

6. **Use the bundle uniforms and `iChannel0` frequency bands** listed
   below. Do not invent new uniforms.

## Inputs available

```glsl
uniform float     iTime;
uniform vec3      iResolution;
uniform sampler2D iChannel0;   // 2x512 musical spectrum texture
                               //   row 0.25 (frequency): bins 0–32 kick,
                               //                         32–96 snare+tom,
                               //                         96–256 hat+cymbal,
                               //                         256–512 melodic
                               //   row 0.75 (waveform):  tempo-locked heartbeat

uniform float iBpm;             // current BPM
uniform float iBeat;            // [0,1] phase within current beat
uniform int   iBar;             // 0-indexed bar number
uniform float iSectionEnergy;   // [0,1] rank of current section
uniform int   iSectionId;       // stable per-label id (verse=N, chorus=M, ...).
                                //   Use this — not iBar — when you want a
                                //   change to happen on verse/chorus/bridge
                                //   boundaries.
uniform float iEnergy;          // [0,1] global energy at this moment
```

## Cookbook (vocabulary, not a checklist)

Below is a library of *kinds of mappings* that have worked in practice.
Read them for ideas — copy one, adapt one, combine two, or invent
something better that fits this shader. If you use a cookbook idiom,
keep a `// === <name> ===` comment header so the lineage is traceable.

Add `// cookbook_version: 2` near the top of the modified shader.

<paste the full contents of REACTIVITY_COOKBOOK.md here verbatim>

## Output

Emit ONE fenced ```glsl block containing the modified shader. No prose,
no diff, no explanation outside the code.

Each new reactivity block should be preceded by a one-line comment
naming the knob and the musical signal driving it, e.g.

```glsl
// noise scale ← iEnergy — pattern breathes denser in louder passages
```

This is the most important habit: it lets a future fix-it pass see
*what is wired to what* at a glance.

## Target shader

<paste the contents of your target shader.glsl here verbatim>
