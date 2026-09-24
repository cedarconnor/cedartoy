# Expose this GLSL shader's knobs for the CedarToy modulation matrix

Expose this shader's 4–8 most expressive constants as `@param`s with safe
ranges, keep the look identical at defaults, and suggest `@mod` routes from
this song's available data. Don't write audio-reactive code.

CedarToy's modulation matrix does the music side: it routes musical signals
into the shader's `@param` uniforms with tempo-aware smoothing (attack/release
in beats), response curves and depth. Your only job is to turn the right
hard-coded numbers into knobs, so the user can route music into them without
touching the code again.

## Process

1. **Read the target shader. Pick 4–8 expressive constants** — numbers that,
   when changed, visibly alter the *shape*, *motion* or *colour* of the image:
   noise scales, fold/warp strengths, rotation offsets, glow gains, fog
   density, palette offsets, step sizes, symmetry amounts. Prefer constants
   inside the inner loop / main pattern over a final brightness multiply.

2. **Expose each one as a float `@param` + matching uniform.** Replace the
   literal with the uniform; the `@param` default must be the exact original
   value so the image is identical at defaults:

   ```glsl
   // @param warp_amount float 0.2 0.0 1.0 "Warp"
   uniform float warp_amount;
   ```

   Format: `// @param <name> float <default> <min> <max> "<Label>"`. Names are
   GLSL identifiers (snake_case, no `i` prefix). Choose a min/max range that
   stays good-looking across the whole range (no NaNs, no black frames, no
   blown-out white) — the matrix clamps modulated values to it.

3. **Phases and offsets get their own knob.** For motion (rotation angle,
   scroll offset, drift) do NOT expose a speed that multiplies `iTime` —
   changing it mid-song makes the image jump. Instead expose an additive
   offset that defaults to 0 (e.g. `angle = iTime * 0.3 + swirl_phase`); the
   matrix's `integrate` mode then makes its speed follow the music smoothly.

4. **Suggest default routes with `@mod` lines** next to the params, using
   only sources this song actually has (see the data summary below):

   ```glsl
   // @mod warp_amount <- iKick depth=0.5 release=0.5 curve=ease_out
   // @mod swirl_phase <- iEnergy depth=1.5 mode=integrate
   ```

   Syntax: `// @mod <param> <- <source> [depth=<float>] [curve=<curve>]
   [attack=<beats>] [release=<beats>] [mode=add|integrate] [enabled=true|false]`.
   - `depth` is in param units (may be negative). `add` mode:
     `param = base + Σ depth·shaped`, clamped to the @param range.
     `integrate` mode adds `depth · ∫ shaped dt` (seconds) and is not
     clamped — only use it on phase/offset params.
   - `attack` / `release` are in **beats** of the local tempo (0 = instant).
     Impulsive sources (`iKick`, `iSnare`, `iHat`, `beat_pulse`) usually want
     attack 0 and release 0.25–1; slow ones (`iSectionEnergy`, `iBuild`) want
     attack/release of 2–8 beats.
   - Curves: <curves>.
   - Sources: <sources>.
   Values are 0..1. 2–5 routes is plenty; leave the rest for the user.

5. **Don't write audio-reactive code.** Do not declare or read any bundle
   uniform (`iEnergy`, `iKick`, `iBeatClock`, `iChannel0` bands, ...) and do
   not add new passes or buffers. Keep the original structure and comments.

## Output

Emit ONE fenced ```glsl block containing the modified shader. No prose, no
diff, no explanation outside the code. Put the `@param` and `@mod` lines
together near the top of the file.

## Target shader

<paste the contents of your target shader.glsl here verbatim>
