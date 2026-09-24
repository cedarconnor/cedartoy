// Musical Demo — CedarToy showcase for the MusiCue musical-structure uniforms.
//
// A neon flythrough tunnel. Every visual lever is wired to one signal:
//   - flight speed      <- iMusicTime   (surges in loud passages, never jitters)
//   - camera roll       <- iBeatClock + iBarPhase (smooth, beat-locked)
//   - wall chaser light <- iBarPhase    (one lap around the tunnel per bar)
//   - kick shock ring   <- iKick        (a ring that rides out from the camera)
//   - tunnel radius     <- iBass        (low end swells the world)
//   - vanishing glow    <- iVocals      (the voice lights the far end)
//   - tension           <- iBuild       (colour drains + grid tightens into drops)
//   - palette/segments  <- iSectionId   (each section type has its own look)
// With no bundle loaded it falls back to iTime-driven motion, so it still
// looks alive in free-run preview.
//
// Supports CedarToy camera modes (2D / equirect / LL180) like the other
// shaders: the scene is defined purely by ray direction.
//
// cookbook_version: 3

// MusiCue bundle uniforms — declared so the headless render compiles.
// (The web preview auto-declares these and strips these lines.)
uniform float iBpm;
uniform int   iSectionId;
uniform float iMusicTime;
uniform float iBeatClock;
uniform float iBarPhase;
uniform float iKick;
uniform float iBass;
uniform float iVocals;
uniform float iBuild;

const float TAU = 6.283185307179586;

vec3 palette(float x) {
    return 0.5 + 0.5 * cos(TAU * (x + vec3(0.0, 0.33, 0.67)));
}

mat2 rot(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

// Distance from x to the nearest integer, anti-aliased line of width w.
float gridLine(float x, float w) {
    float d = abs(fract(x) - 0.5);            // 0.5 on the line, 0 mid-cell
    float fw = max(fwidth(x), 1e-4);
    return smoothstep(0.5 - w - fw, 0.5 - w + fw, d);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 q = fragCoord.xy / iResolution.xy;
    vec2 p = (fragCoord.xy - 0.5 * iResolution.xy) / iResolution.y;

    // ---- signals (fall back to plain time when no bundle is loaded) ----
    float hasBundle = step(1.0, iBpm);
    float flowT   = iMusicTime;                              // == iTime w/o bundle
    float beatClk = mix(iTime * 2.0, iBeatClock, hasBundle);
    float barPh   = mix(fract(iTime * 0.5), iBarPhase, hasBundle);
    float tension = iBuild * iBuild;                         // ease-in
    float sid     = float(iSectionId);

    // ---- camera ----
    vec3 rd = normalize(vec3(p, 1.1));
    if (iCameraMode > 0) {
        mat3 vrBasis = mat3(vec3(1, 0, 0), vec3(0, 1, 0), vec3(0, 0, 1));
        if (iCameraMode == 1) { // Equirect
            float lon = (q.x * 2.0 - 1.0) * PI;
            float lat = (q.y * 2.0 - 1.0) * (PI * 0.5);
            rd = normalize(vec3(cos(lat) * sin(lon), sin(lat), cos(lat) * cos(lon)));
        } else if (iCameraMode == 2) { // LL180
            rd = cameraDirLL180(q, iCameraTiltDeg, vrBasis);
        }
    }

    // === bar_phase_camera === roll <- iBeatClock (slow turn) + iBarPhase (swing)
    float roll = TAU * beatClk / 64.0 + 0.12 * sin(TAU * barPh);
    rd.xy = rot(roll) * rd.xy;

    // ---- tunnel intersection ----
    // === stem_layers === radius <- iBass
    float radius = 1.0 + 0.35 * iBass;
    float r = max(length(rd.xy), 1e-4);
    float t = radius / r;                                    // distance to wall
    // === music_time_flow === travel <- iMusicTime
    float travel = flowT * 2.2;
    float dz = t * rd.z;                                     // along-axis offset
    float z = travel + dz;
    float ang = atan(rd.y, rd.x);                            // -pi..pi

    // ---- wall pattern ----
    float segs = 6.0 + 2.0 * mod(sid, 4.0);                  // per-section symmetry
    float ringsPerUnit = mix(0.5, 1.5, tension);             // grid tightens in builds
    float u = ang / TAU * segs;
    float v = z * ringsPerUnit;
    float lines = max(gridLine(u, 0.03), gridLine(v, 0.04));

    float fog = exp(-0.06 * t);
    vec3 base = palette(sid * 0.21 + z * 0.015);
    vec3 col = base * (0.10 + 0.9 * lines) * fog;

    // Chaser: a light that laps the tunnel once per bar (loop-closed at wrap).
    float chaseAng = TAU * barPh - PI;
    float dAng = abs(mod(ang - chaseAng + PI, TAU) - PI);
    col += palette(sid * 0.21 + 0.5) * exp(-6.0 * dAng) * 0.6 * fog * (0.4 + lines);

    // Kick shock ring: rides away from the camera as the envelope decays.
    float ringPos = (1.0 - iKick) * 14.0;
    float ring = exp(-2.5 * abs(abs(dz) - ringPos)) * iKick;
    col += vec3(1.0, 0.85, 0.7) * ring * 1.4;

    // === stem_layers === vanishing-point glow <- iVocals
    float fwd = max(rd.z, 0.0);
    float halo = pow(fwd, 60.0) * 2.0 + pow(fwd, 8.0) * 0.25;
    col += palette(sid * 0.21 + 0.15) * halo * (0.15 + 1.6 * iVocals);

    // === build_tension === colour drains and contrast climbs into the drop
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(lum), 0.6 * tension);
    col *= 1.0 + 0.8 * tension * lines;

    // Tone map + gamma.
    col = 1.0 - exp(-col * 1.4);
    col = pow(col, vec3(0.4545));
    fragColor = vec4(col, 1.0);
}
