// Aurora Borealis - Shadertoy compliant
// Method: 2D noise "difference clouds" extruded volumetrically with raymarching.
// Uniforms: iResolution, iTime (standard Shadertoy)

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

// Simple value noise
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);

    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));

    vec2 u = f * f * (3.0 - 2.0 * f);

    return mix(mix(a, b, u.x),
               mix(c, d, u.x), u.y);
}

// fbm for nicer, wispy noise
float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = m * p;
        a *= 0.5;
    }
    return v;
}

// "Difference clouds" style aurora mask
float auroraMask(vec2 p, float t) {
    // Scale + scroll speeds for the two noise fields
    float s1 = 0.7;
    float s2 = 1.3;
    float speed1 = 0.04;
    float speed2 = -0.03;

    float n1 = fbm(p * s1 + vec2(0.0, t * speed1));
    float n2 = fbm(p * s2 + vec2(0.0, t * speed2));

    float d = abs(n1 - n2);   // difference clouds
    float m = 1.0 - d;        // invert to get bright veins

    // Sharpen into streaks
    m = smoothstep(0.35, 0.9, m);
    return m;
}

// Aurora color gradient by height and intensity
vec3 auroraColor(float h, float m) {
    // Base green, mid cyan, top magenta-ish
    vec3 c1 = vec3(0.1, 0.8, 0.3);
    vec3 c2 = vec3(0.2, 0.6, 1.0);
    vec3 c3 = vec3(0.9, 0.2, 0.9);

    float t1 = clamp(h * 1.2, 0.0, 1.0);
    float t2 = clamp(h - 0.3, 0.0, 1.0);

    vec3 col = mix(c1, c2, t1);
    col = mix(col, c3, t2);

    // Boost a bit by local mask intensity
    return col * (0.35 + 0.65 * m);
}

// Simple night sky background with gradient + stars
float starNoise(vec2 p) {
    return hash(p);
}

vec3 skyColor(vec3 rd) {
    // Vertical gradient
    float t = clamp(rd.y * 0.7 + 0.5, 0.0, 1.0);
    vec3 horizon = vec3(0.01, 0.02, 0.05);
    vec3 zenith  = vec3(0.0,  0.08, 0.18);
    vec3 col = mix(horizon, zenith, t);

    // Faint airglow near zenith
    float glow = pow(max(rd.y, 0.0), 3.0);
    col += vec3(0.1, 0.15, 0.2) * glow;

    // Simple star field
    // Project rd on unit sphere -> use xy as seed
    float s = pow(max(starNoise(rd.xy * 500.0), 0.0), 30.0);
    col += vec3(s);

    return col;
}

mat2 rot(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

// Raymarch volumetric aurora
vec3 renderAurora(vec3 ro, vec3 rd, float time) {
    // Aurora volume region: y in [1, 6], max distance ~40
    float t = 0.0;
    float maxDist = 40.0;
    float density = 0.0;
    vec3 col = vec3(0.0);

    float dt = 0.15;

    for (int i = 0; i < 80; i++) {
        if (t > maxDist || density > 0.98) break;

        vec3 pos = ro + rd * t;

        if (pos.y < 1.0 || pos.y > 6.0) {
            t += dt;
            continue;
        }

        // XZ is our "ground plane" for sampling the 2D noise
        vec2 p = pos.xz * 0.18;

        float m = auroraMask(p, time * 0.7);

        // Vertical falloff: low at bottom, soft tail at top
        float h = (pos.y - 1.0) / 5.0;        // 0..1 across the aurora height
        h = clamp(h, 0.0, 1.0);

        float heightMask = smoothstep(0.05, 0.2, h) * (1.0 - smoothstep(0.8, 1.0, h));

        float intensity = m * heightMask;

        // Distance fade to keep things in check
        float dfade = exp(-0.02 * t * t);

        float alpha = intensity * dfade * 0.08; // per-step opacity

        if (alpha > 0.0001) {
            vec3 c = auroraColor(h, m);
            // Front-to-back compositing
            col += (1.0 - density) * c * alpha;
            density += alpha;
        }

        t += dt;
    }

    return col;
}

vec3 getRayDir(vec3 ro, vec3 target, vec2 uv, float fov) {
    vec3 fw = normalize(target - ro);
    vec3 rt = normalize(cross(vec3(0.0, 1.0, 0.0), fw));
    vec3 up = cross(fw, rt);

    float z = 1.0 / tan(fov * 0.5);
    vec3 rd = normalize(rt * uv.x + up * uv.y + fw * z);
    return rd;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    // Normalized screen coordinates (centered)
    vec2 uv = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;

    float time = iTime;

    // Camera setup: slowly orbit around the aurora
    vec3 ro = vec3(0.0, 1.8, -10.0);
    vec3 target = vec3(0.0, 2.8, 0.0);

    float orbit = time * 0.05;
    ro.xz     = rot(orbit) * ro.xz;
    target.xz = rot(orbit) * target.xz;

    vec3 rd = getRayDir(ro, target, uv, radians(60.0));

    vec3 col = skyColor(rd);
    col += renderAurora(ro, rd, time);

    // Tone map & gamma
    col = col / (1.0 + col);      // simple Reinhard
    col = pow(col, vec3(0.4545)); // gamma 2.2

    fragColor = vec4(col, 1.0);
}