// Shader by Frostbyte
// Licensed under CC BY-NC-SA 4.0
// cookbook_version: 1

// MusiCue-driven uniforms — bound by CedarToy when a bundle is loaded.
uniform float iBpm;
uniform float iBeat;
uniform int   iBar;
uniform float iSectionEnergy;
uniform int   iSectionId;       // stable per-label id (verse=N, chorus=M, ...)
uniform float iEnergy;

//2d rotation matrix
vec2 r(vec2 v,float t){float s=sin(t),c=cos(t);return mat2(c,-s,s,c)*v;}

// ACES tonemap: https://www.shadertoy.com/view/Xc3yzM
vec3 a(vec3 c)
{
mat3 m1=mat3(0.59719,0.07600,0.02840,0.35458,0.90834,0.13383,0.04823,0.01566,0.83777);
mat3 m2=mat3(1.60475,-0.10208,-0.00327,-0.53108,1.10813,-0.07276,-0.07367,-0.00605,1.07602);
vec3 v=m1*c,a=v*(v+0.0245786)-0.000090537,b=v*(0.983729*v+0.4329510)+0.238081;
return m2*(a/b);
}

//Xor's Dot Noise: https://www.shadertoy.com/view/wfsyRX
float n(vec3 p)
{
    const float PHI = 1.618033988;
    const mat3 GOLD = mat3(
    -0.571464913, +0.814921382, +0.096597072,
    -0.278044873, -0.303026659, +0.911518454,
    +0.772087367, +0.494042493, +0.399753815);
    return dot(cos(GOLD * p), sin(PHI * p * GOLD));
}

void mainImage(out vec4 o,in vec2 u){
    float i,s,t=iTime;
    vec3 p,l,b,d;p.z=t;

    // === beat_pump_zoom (cookbook_version 1) ===
    float beatWave = 0.5 + 0.5 * sin(6.2831853 * iBeat - 1.5707963);
    float zoomMul = 1.0 + beatWave * 0.04;
    vec2 uPump = (u - iResolution.xy * 0.5) * zoomMul + iResolution.xy * 0.5;
    d=normalize(vec3(2.*uPump-iResolution.xy,iResolution.y));

    // === camera_rock_subtle (custom) ===
    // Gentle roll of the ray direction on a continuous tempo clock. Do not
    // use float(iBar) + iBeat here: iBeat resets every beat while iBar changes
    // once per bar, which creates visible camera stutter.
    float tempoBeat = iTime * max(iBpm, 0.0) / 60.0;
    float rockEnabled = step(1.0, iBpm);
    float rockAngle = rockEnabled * (
        sin(tempoBeat * 0.3927) * 0.030       // slow ~16-beat sway
      + sin(tempoBeat * 1.5708) * 0.008       // 1/4-bar nudge
    );
    d.xy = mat2(cos(rockAngle), -sin(rockAngle),
                sin(rockAngle),  cos(rockAngle)) * d.xy;

    // === kick_pulse_camera (cookbook_version 1) ===
    float kickEnergy = texture(iChannel0, vec2(0.03, 0.25)).r;
    p.z += kickEnergy * 0.08;

    // CedarToy VR Logic
    if (iCameraMode > 0) {
        mat3 basis = mat3(vec3(1,0,0), vec3(0,1,0), vec3(0,0,1));
        vec2 q = u / iResolution.xy;
        if (iCameraMode == 1) { // Equirect
             float lon = (q.x * 2.0 - 1.0) * PI;
             float lat = (q.y * 2.0 - 1.0) * (PI * 0.5);
             vec3 dir;
             dir.x = cos(lat) * sin(lon);
             dir.y = sin(lat);
             dir.z = cos(lat) * cos(lon);
             d = normalize(basis * dir);
        } else if (iCameraMode == 2) { // LL180
            d = cameraDirLL180(q, iCameraTiltDeg, basis);
        }
    }

    // === section_palette_shift (cookbook_version 1) ===
    float palette = float(iBar / 8) + iSectionEnergy * 0.5;

    // === noise_scale_breathe (custom) ===
    // Modulate the inner noise feature scale by global energy. The pattern
    // itself morphs — denser features during high-energy moments, looser
    // structure in quiet passages.
    float noiseScale = mix(9.0, 15.0, iEnergy);

    // === swirl_whip_on_kick (custom) ===
    // Add kick-band energy as a small ADDITIVE rotation offset. Do NOT
    // multiply iTime by the kick — at large t a volatile rate produces
    // many radians of jitter per frame and the field spins chaotically.
    float kick = texture(iChannel0, vec2(0.03, 0.25)).r;
    float swirlOffset = kick * 0.6;

    for(o*=i;i<10.;i++){
        b=p;
        b.xy=r(sin(b.xy),t*1.5+b.z*3.+swirlOffset);
        s=.001+abs(n(b*noiseScale)/12.-n(b))*.4;
        s=max(s,2.-length(p.xy));
        s+=abs(p.y*.75+sin(p.z+t*.1+p.x*1.5))*.2;
        p+=d*s;
        l+=(1.+sin(i+length(p.xy*.1)+vec3(3,1.5,1)+palette))/s;
    }
    vec3 col=a(l*l/6e2);

    // === energy_brightness_lift (cookbook_version 1) ===
    col *= mix(0.9, 1.15, iEnergy);

    // === section_color_wash (custom, replaces bar_anchored_strobe) ===
    // Tint the image toward a section-type-derived accent colour. iSectionId
    // is stable per label (all verses share one id, all choruses another),
    // so the colour changes ONLY on verse/chorus/bridge boundaries — not
    // every 8 bars. Strength is gentle; the image never blanks.
    float sid = float(iSectionId);
    vec3 accent = 0.5 + 0.5 * sin(sid * 1.7 + vec3(0.0, 2.094, 4.189));
    col = mix(col, col * accent * 1.2, iSectionEnergy * 0.35);

    // === hat_shimmer (custom, replaces hat_grain) ===
    // Hi-hat energy adds a low-amplitude radial shimmer instead of film
    // grain — reads as motion locked to the hat instead of texture noise.
    float hat = texture(iChannel0, vec2(0.35, 0.25)).r;
    vec2 cuv = (u - iResolution.xy * 0.5) / iResolution.y;
    float shimmer = sin(length(cuv) * 40.0 - t * 6.0) * hat * 0.06;
    col += col * shimmer;

    o.rgb = col;
    o.a = 1.0;
}
