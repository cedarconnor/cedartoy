// Shader by Frostbyte
// Licensed under CC BY-NC-SA 4.0
// cookbook_version: 1

// MusiCue-driven uniforms — bound by CedarToy when a bundle is loaded.
uniform float iBpm;
uniform float iBeat;
uniform int   iBar;
uniform float iSectionEnergy;
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

    for(o*=i;i<10.;i++){
        b=p;
        b.xy=r(sin(b.xy),t*1.5+b.z*3.);
        s=.001+abs(n(b*12.)/12.-n(b))*.4;
        s=max(s,2.-length(p.xy));
        s+=abs(p.y*.75+sin(p.z+t*.1+p.x*1.5))*.2;
        p+=d*s;
        l+=(1.+sin(i+length(p.xy*.1)+vec3(3,1.5,1)+palette))/s;
    }
    vec3 col=a(l*l/6e2);

    // === energy_brightness_lift (cookbook_version 1) ===
    col *= mix(0.9, 1.15, iEnergy);

    // === bar_anchored_strobe (cookbook_version 1) ===
    bool onBarStart = iBeat < 0.04 && (iBar % 4) == 0;
    if (onBarStart && iSectionEnergy > 0.6) {
        col += vec3(0.5);
    }

    // === hat_grain (cookbook_version 1) ===
    float hat = texture(iChannel0, vec2(0.35, 0.25)).r;
    float noise = fract(sin(dot(u, vec2(12.9898, 78.233))) * 43758.5453);
    col += (noise - 0.5) * hat * 0.04;

    o.rgb = col;
    o.a = 1.0;
}
