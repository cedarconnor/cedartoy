// Luminescence by Martijn Steinrucken aka BigWings - 2017
// Email:countfrolic@gmail.com Twitter:@The_ArtOfCode
// License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
// cookbook_version: 2
//
// Reactive variant: jellyfish body squash and tentacle sway driven by a
// HALF-NOTE tempo clock (every other beat), each with staccato attack
// and soft exponential decay. Per-jelly phase stagger so the school
// breathes organically rather than pulsing in unison. Body and tentacles
// fire on opposite half-notes so the deformation cadence is push / drift
// / push / drift rather than thud-thud-thud. Three jelly colour groups
// rotate per bar with the same half-note envelope; glow nodes blink on
// the half-note. Section id locks the global accent/bg palette. NO
// camera musicality. All bundle uniforms at zero ≈ original shader.

// Music by Klaus Lunde
// https://soundcloud.com/klauslunde/zebra-tribute

// NOTE: dropped the `@param audio_strength` / `@param pulse_speed`
// uniforms that the parent luminescenceAudio.glsl used — they were
// unbound in the live preview (no @param binding there), zeroing
// `iTime * pulse_speed` and FREEZING the entire body pump waveform.
// The constants are inlined to match the original luminescence.glsl
// so the bulb and tentacle deformation read the same with or without
// a bundle loaded. Beat-driven accents stack additively on top.

#define INVERTMOUSE -1.

#define MAX_STEPS 100.
#define VOLUME_STEPS 8.
//#define SINGLE
#define MIN_DISTANCE 0.1
#define MAX_DISTANCE 100.
#define HIT_DISTANCE .01

#define S(x,y,z) smoothstep(x,y,z)
#define B(x,y,z,w) S(x-z, x+z, w)*S(y+z, y-z, w)
#define sat(x) clamp(x,0.,1.)
#define SIN(x) sin(x)*.5+.5

const vec3 lf=vec3(1., 0., 0.);
const vec3 up=vec3(0., 1., 0.);
const vec3 fw=vec3(0., 0., 1.);

const float halfpi = 1.570796326794896619;
const float pi = 3.141592653589793238;
const float twopi = 6.283185307179586;


vec3 accentColor1 = vec3(1., .1, .5);
vec3 secondColor1 = vec3(.1, .5, 1.);

vec3 accentColor2 = vec3(1., .5, .1);
vec3 secondColor2 = vec3(.1, .5, .6);

vec3 bg;         // global background color
vec3 accent;    // color of the phosphorecence
float g_audio;  // global audio level

// MusiCue-driven uniforms — bound by CedarToy when a bundle is loaded.
uniform float iBpm;
uniform float iBeat;
uniform int   iBar;
uniform float iSectionEnergy;
uniform int   iSectionId;
uniform float iEnergy;

float N1( float x ) { return fract(sin(x)*5346.1764); }
float N2(float x, float y) { return N1(x + y*23414.324); }

float N3(vec3 p) {
    p  = fract( p*0.3183099+.1 );
    p *= 17.0;
    return fract( p.x*p.y*p.z*(p.x+p.y+p.z) );
}

struct ray {
    vec3 o;
    vec3 d;
};

struct camera {
    vec3 p;            // the position of the camera
    vec3 forward;    // the camera forward vector
    vec3 left;        // the camera left vector
    vec3 up;        // the camera up vector

    vec3 center;    // the center of the screen, in world coords
    vec3 i;            // where the current ray intersects the screen, in world coords
    ray ray;        // the current ray: from cam pos, through current uv projected on screen
    vec3 lookAt;    // the lookat point
    float zoom;        // the zoom factor
};

struct de {
    // data type used to pass the various bits of information used to shade a de object
    float d;    // final distance to field
    float m;     // material
    vec3 uv;
    float pump;

    vec3 id;
    vec3 pos;        // the world-space coordinate of the fragment
};

struct rc {
    // data type used to handle a repeated coordinate
    vec3 id;    // holds the floor'ed coordinate of each cell. Used to identify the cell.
    vec3 h;        // half of the size of the cell
    vec3 p;        // the repeated coordinate
    //vec3 c;        // the center of the cell, world coordinates
};

rc Repeat(vec3 pos, vec3 size) {
    rc o;
    o.h = size*.5;
    o.id = floor(pos/size);
    o.p = mod(pos, size)-o.h;

    return o;
}

camera cam;


void CameraSetup(vec2 uv, vec3 position, vec3 lookAt, float zoom) {

    cam.p = position;
    cam.lookAt = lookAt;
    cam.forward = normalize(cam.lookAt-cam.p);
    cam.left = cross(up, cam.forward);
    cam.up = cross(cam.forward, cam.left);
    cam.zoom = zoom;

    cam.center = cam.p+cam.forward*cam.zoom;
    cam.i = cam.center+cam.left*uv.x+cam.up*uv.y;

    cam.ray.o = cam.p;
    cam.ray.d = normalize(cam.i-cam.p);
}


// ============== Functions I borrowed ;)

vec3 N31(float p) {
   vec3 p3 = fract(vec3(p) * vec3(.1031,.11369,.13787));
   p3 += dot(p3, p3.yzx + 19.19);
   return fract(vec3((p3.x + p3.y)*p3.z, (p3.x+p3.z)*p3.y, (p3.y+p3.z)*p3.x));
}

float smin( float a, float b, float k )
{
    float h = clamp( 0.5+0.5*(b-a)/k, 0.0, 1.0 );
    return mix( b, a, h ) - k*h*(1.0-h);
}

float smax( float a, float b, float k )
{
    float h = clamp( 0.5 + 0.5*(b-a)/k, 0.0, 1.0 );
    return mix( a, b, h ) + k*h*(1.0-h);
}

float sdSphere( vec3 p, vec3 pos, float s ) { return (length(p-pos)-s); }

vec2 pModPolar(inout vec2 p, float repetitions, float fix) {
    float angle = twopi/repetitions;
    float a = atan(p.y, p.x) + angle/2.;
    float r = length(p);
    float c = floor(a/angle);
    a = mod(a,angle) - (angle/2.)*fix;
    p = vec2(cos(a), sin(a))*r;

    return p;
}

// -------------------------


float Dist( vec2 P,  vec2 P0, vec2 P1 ) {
    vec2 v = P1 - P0;
    vec2 w = P - P0;

    float c1 = dot(w, v);
    float c2 = dot(v, v);

    if (c1 <= 0. )
        return length(P-P0);

    float b = c1 / c2;
    vec2 Pb = P0 + b*v;
    return length(P-Pb);
}

vec3 ClosestPoint(vec3 ro, vec3 rd, vec3 p) {
    return ro + max(0., dot(p-ro, rd))*rd;
}

vec2 RayRayTs(vec3 ro1, vec3 rd1, vec3 ro2, vec3 rd2) {
    vec3 dO = ro2-ro1;
    vec3 cD = cross(rd1, rd2);
    float v = dot(cD, cD);

    float t1 = dot(cross(dO, rd2), cD)/v;
    float t2 = dot(cross(dO, rd1), cD)/v;
    return vec2(t1, t2);
}

float DistRaySegment(vec3 ro, vec3 rd, vec3 p1, vec3 p2) {
    vec3 rd2 = p2-p1;
    vec2 t = RayRayTs(ro, rd, p1, rd2);

    t.x = max(t.x, 0.);
    t.y = clamp(t.y, 0., length(rd2));

    vec3 rp = ro+rd*t.x;
    vec3 sp = p1+rd2*t.y;

    return length(rp-sp);
}

vec2 sph(vec3 ro, vec3 rd, vec3 pos, float radius) {
    vec3 oc = pos - ro;
    float l = dot(rd, oc);
    float det = l*l - dot(oc, oc) + radius*radius;
    if (det < 0.0) return vec2(MAX_DISTANCE);

    float d = sqrt(det);
    float a = l - d;
    float b = l + d;

    return vec2(a, b);
}


vec3 background(vec3 r) {

    float x = atan(r.x, r.z);
    float y = pi*0.5-acos(r.y);

    vec3 col = bg*(1.+y);

    float t = iTime;

    float a = sin(r.x);

    float beam = sat(sin(10.*x+a*y*5.+t));
    beam *= sat(sin(7.*x+a*y*3.5-t));

    float beam2 = sat(sin(42.*x+a*y*21.-t));
    beam2 *= sat(sin(34.*x+a*y*17.+t));

    beam += beam2;
    col *= 1.+beam*.05;

    return col;
}




float remap(float a, float b, float c, float d, float t) {
    return ((t-a)/(b-a))*(d-c)+c;
}



de map( vec3 p, vec3 id ) {

    // Hardcoded swim speed matches the original luminescence.glsl. Do NOT
    // route through a uniform parameter — preview path doesn't bind
    // @param uniforms and zero here freezes the entire body waveform.
    float t = iTime * 2.0;

    float N = N3(id);

    de o;
    o.m = 0.;

    float x = (p.y+N*twopi)*1.+t;
    float r = 1.;

    // Original organic pump waveform — provides the continuous bulb and
    // tentacle breathing. g_audio multiplier is inlined (was the @param
    // audio_strength default of 2.0).
    float pump = cos(x+cos(x))+sin(2.*x)*.2+sin(4.*x)*.02 + g_audio * 2.0;

    // === jelly_pump_halfnote (custom) ===
    // body pump accent ← half-note tempo clock + kick band, per-jelly
    // phase staggered. Staccato attack (~30 ms at 120 BPM), soft
    // exponential decay across the half-note. Rate is every OTHER beat
    // so the school breathes rather than pulses. Stagger by N keeps the
    // school from clapping in unison.
    float pumpBpsActive = step(1.0, iBpm);
    float pumpHalfPhase = fract(iTime * iBpm / 60.0 * 0.5 + N * 0.31);
    float pumpAttack    = smoothstep(0.0, 0.03, pumpHalfPhase);
    float pumpDecay     = exp(-pumpHalfPhase * 2.2);
    float pumpEnv       = pumpAttack * pumpDecay * pumpBpsActive;
    float pumpKickBand  = texture(iChannel0, vec2(0.03, 0.25)).r;
    pump += pumpEnv * (0.14 + pumpKickBand * 0.30) * (0.5 + iSectionEnergy * 0.5);

    x = t + N*twopi;
    p.y -= (cos(x+cos(x))+sin(2.*x)*.2)*.6;
    p.xz *= 1. + pump*.2;

    float d1 = sdSphere(p, vec3(0., 0., 0.), r);
    float d2 = sdSphere(p, vec3(0., -.5, 0.), r);

    o.d = smax(d1, -d2, .1);
    o.m = 1.;

    if(p.y<.5) {
        float sway = sin(t+p.y+N*twopi)*S(.5, -3., p.y)*N*.3;

        // === tentacle_sway_halfnote_offset (custom) ===
        // sway amplitude ← half-note tempo clock (offset by 0.5 so
        // tentacles wiggle on the half-note OPPOSITE to the body pump)
        // + snare band. Staccato attack, soft decay. Per-jelly stagger
        // via 0.47*N decorrelates from the pump stagger.
        float swayBpsActive = step(1.0, iBpm);
        float swayHalfPhase = fract(iTime * iBpm / 60.0 * 0.5 + 0.5 + N * 0.47);
        float swayAttack    = smoothstep(0.0, 0.03, swayHalfPhase);
        float swayDecay     = exp(-swayHalfPhase * 1.9);
        float swayEnv       = swayAttack * swayDecay * swayBpsActive;
        float snareBand     = texture(iChannel0, vec2(0.13, 0.25)).r;
        sway *= 1.0 + swayEnv * snareBand * 1.6;

        p.x += sway*N;
        p.z += sway*(1.-N);

        vec3 mp = p;
        mp.xz = pModPolar(mp.xz, 6., 0.);

        float d3 = length(mp.xz-vec2(.2, .1))-remap(.5, -3.5, .1, .01, mp.y);
        if(d3<o.d) o.m=2.;
        d3 += (sin(mp.y*10.)+sin(mp.y*23.))*.03;

        float d32 = length(mp.xz-vec2(.2, .1))-remap(.5, -3.5, .1, .04, mp.y)*.5;
        d3 = min(d3, d32);
        o.d = smin(o.d, d3, .5);

        if( p.y<.2) {
             vec3 op = p;
            op.xz = pModPolar(op.xz, 13., 1.);

            float d4 = length(op.xz-vec2(.85, .0))-remap(.5, -3., .04, .0, op.y);
            if(d4<o.d) o.m=3.;
            o.d = smin(o.d, d4, .15);
        }
    }
    o.pump = pump;
    o.uv = p;

    o.d *= .8;
    return o;
}

vec3 calcNormal( de o ) {
    vec3 eps = vec3( 0.01, 0.0, 0.0 );
    vec3 nor = vec3(
        map(o.pos+eps.xyy, o.id).d - map(o.pos-eps.xyy, o.id).d,
        map(o.pos+eps.yxy, o.id).d - map(o.pos-eps.yxy, o.id).d,
        map(o.pos+eps.yyx, o.id).d - map(o.pos-eps.yyx, o.id).d );
    return normalize(nor);
}

de CastRay(ray r) {
    float d = 0.;
    float dS = MAX_DISTANCE;

    vec3 pos = vec3(0., 0., 0.);
    vec3 n = vec3(0.);
    de o, s;

    float dC = MAX_DISTANCE;
    vec3 p;
    rc q;
    float t = iTime;
    vec3 grid = vec3(6., 30., 6.);

    for(float i=0.; i<MAX_STEPS; i++) {
        p = r.o + r.d*d;

        #ifdef SINGLE
        s = map(p, vec3(0.));
        #else
        p.y -= t;
        p.x += t;

        q = Repeat(p, grid);

        vec3 rC = ((2.*step(0., r.d)-1.)*q.h-q.p)/r.d;
        dC = min(min(rC.x, rC.y), rC.z)+.01;

        float N = N3(q.id);
        q.p += (N31(N)-.5)*grid*vec3(.5, .7, .5);

        if(Dist(q.p.xz, r.d.xz, vec2(0.))<1.1)
            s = map(q.p, q.id);
        else
            s.d = dC;


        #endif

        if(s.d<HIT_DISTANCE || d>MAX_DISTANCE) break;
        d+=min(s.d, dC);
    }

    if(s.d<HIT_DISTANCE) {
        o.m = s.m;
        o.d = d;
        o.id = q.id;
        o.uv = s.uv;
        o.pump = s.pump;

        #ifdef SINGLE
        o.pos = p;
        #else
        o.pos = q.p;
        #endif
    }

    return o;
}

float VolTex(vec3 uv, vec3 p, float scale, float pump) {
    p.y *= scale;

    float s2 = 5.*p.x/twopi;
    float id = floor(s2);
    s2 = fract(s2);
    vec2 ep = vec2(s2-.5, p.y-.6);
    float ed = length(ep);
    float e = B(.35, .45, .05, ed);

       float s = SIN(s2*twopi*15. );
    s = s*s; s = s*s;
    s *= S(1.4, -.3, uv.y-cos(s2*twopi)*.2+.3)*S(-.6, -.3, uv.y);

    float t = iTime*5.;
    float mask = SIN(p.x*twopi*2. + t);
    s *= mask*mask*2.;

    return s+e*pump*2.;
}

vec4 JellyTex(vec3 p) {
    vec3 s = vec3(atan(p.x, p.z), length(p.xz), p.y);

    float b = .75+sin(s.x*6.)*.25;
    b = mix(1., b, s.y*s.y);

    p.x += sin(s.z*10.)*.1;
    float b2 = cos(s.x*26.) - s.z-.7;

    b2 = S(.1, .6, b2);
    return vec4(b+b2);
}

vec3 render( vec2 uv, ray camRay, float depth ) {

    bg = background(cam.ray.d);

    vec3 col = bg;
    de o = CastRay(camRay);

    float t = iTime;
    vec3 L = up;


    if(o.m>0.) {
        // === per_jelly_color_groups_halfnote (custom) ===
        // accent ← jelly-hash group + 3-bar feature cycle, half-note
        // pulse. Three colour groups (magenta / cyan / amber). Each
        // group gets a featured bar where its colour pulses on the
        // half-note (every other beat), staccato attack + soft decay.
        // Per-jelly phase stagger keeps groupmates from firing together.
        // iSectionId tints the whole palette per section.
        // Falls back to the original shared accent when no song loaded.
        float colorBpsActive = step(1.0, iBpm);
        float jellyN = N3(o.id);
        int jellyGroup = int(mod(jellyN * 7.0, 3.0));

        vec3 groupAccent;
        if (jellyGroup == 0)      groupAccent = vec3(1.00, 0.30, 0.65);  // magenta
        else if (jellyGroup == 1) groupAccent = vec3(0.30, 0.70, 1.00);  // cyan
        else                       groupAccent = vec3(1.00, 0.80, 0.30); // amber

        vec3 sectionTint = 0.7 + 0.3 * sin(float(iSectionId) * 1.7
                                          + vec3(0.0, 2.094, 4.189));
        groupAccent *= sectionTint;

        int activeGroup = int(mod(float(iBar), 3.0));
        float barEmphasis = (jellyGroup == activeGroup) ? 1.0 : 0.0;

        float colorHalfPhase = fract(iTime * iBpm / 60.0 * 0.5 + jellyN * 0.19);
        float colorAttack    = smoothstep(0.0, 0.04, colorHalfPhase);
        float colorDecay     = exp(-colorHalfPhase * 1.7);
        float beatEnv        = colorAttack * colorDecay;

        float kickBand2 = texture(iChannel0, vec2(0.03, 0.25)).r;
        float groupPulse = barEmphasis * beatEnv * (0.45 + kickBand2 * 1.30);

        // Ambient stagger so non-featured groups still breathe a little.
        float ambientPhase   = fract(colorHalfPhase + float(jellyGroup) / 3.0);
        float ambientAttack  = smoothstep(0.0, 0.04, ambientPhase);
        float ambientDecay   = exp(-ambientPhase * 2.4);
        groupPulse += ambientAttack * ambientDecay * 0.18;

        groupPulse *= colorBpsActive;

        vec3 perJellyAccent = groupAccent * (1.0 + groupPulse * (0.6 + iSectionEnergy));
        accent = mix(accent, perJellyAccent, colorBpsActive);

        vec3 n = calcNormal(o);
        float lambert = sat(dot(n, L));
        vec3 R = reflect(camRay.d, n);
        float fresnel = sat(1.+dot(camRay.d, n));
        float trans = (1.-fresnel)*.5;
        vec3 ref = background(R);
        float fade = 0.;

        if(o.m==1.) {    // hood color
            float density = 0.;
            for(float i=0.; i<VOLUME_STEPS; i++) {
                float sd = sph(o.uv, camRay.d, vec3(0.), .8+i*.015).x;
                if(sd!=MAX_DISTANCE) {
                    vec2 intersect = o.uv.xz+camRay.d.xz*sd;

                    vec3 uv = vec3(atan(intersect.x, intersect.y), length(intersect.xy), o.uv.z);
                    density += VolTex(o.uv, uv, 1.4+i*.03, o.pump);
                }
            }
            vec4 volTex = vec4(accent, density/VOLUME_STEPS);


            vec3 dif = JellyTex(o.uv).rgb;
            dif *= max(.2, lambert);

            col = mix(col, volTex.rgb, volTex.a);
            col = mix(col, vec3(dif), .25);

            col += fresnel*ref*sat(dot(up, n));

            fade = max(fade, S(.0, 1., fresnel));
        } else if(o.m==2.) {                        // inside tentacles
            vec3 dif = accent;
            col = mix(bg, dif, fresnel);

            col *= mix(.6, 1., S(0., -1.5, o.uv.y));

            float prop = o.pump+.25;
            prop *= prop*prop;
            col += pow(1.-fresnel, 20.)*dif*prop;


            fade = fresnel;
        } else if(o.m==3.) {                        // outside tentacles / glow nodes
            // === tentacle_glow_halfnote (custom) ===
            // node brightness ← hi-hat band + half-note blink — the
            // little lights along the tentacles flicker harder on
            // hi-hat patterns and snap on each half-note (every other
            // beat) with a fast attack and tight exponential decay.
            // Tighter decay than the body deformations because these
            // are hot points, not breathing mass.
            float glowBpsActive = step(1.0, iBpm);
            float glowHalfPhase = fract(iTime * iBpm / 60.0 * 0.5);
            float glowAttack    = smoothstep(0.0, 0.02, glowHalfPhase);
            float glowDecay     = exp(-glowHalfPhase * 3.8);
            float dotFlick      = glowAttack * glowDecay * glowBpsActive;
            float hatBand       = texture(iChannel0, vec2(0.35, 0.25)).r;
            vec3 dif = accent * (1.0 + hatBand * 1.6 + dotFlick * 0.8);
            float d = S(100., 13., o.d);
            col = mix(bg, dif, pow(1.-fresnel, 5.)*d);
        }

        fade = max(fade, S(0., 100., o.d));
        col = mix(col, bg, fade);

        if(o.m==4.)
            col = vec3(1., 0., 0.);
    }
     else
        col = bg;

    return col;
}

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    float t = iTime*.04;

    vec2 uv = (fragCoord.xy / iResolution.xy);
    uv -= .5;
    uv.y *= iResolution.y/iResolution.x;

    vec2 m = iMouse.xy/iResolution.xy;

    if(m.x<0.05 || m.x>.95) {
        m = vec2(t*.25, SIN(t*pi)*.5+.5);
    }

    // === section_locked_palette_globals (custom) ===
    // accent / bg ← iSectionId — lock global palette cycle to song
    // structure (verse/chorus/bridge each have their own colours).
    // Falls back to the original time-varying mix when no bundle is
    // loaded so the visual identity is preserved.
    float palBpsActive = step(1.0, iBpm);
    float sidPhase = float(iSectionId);
    vec3 origAccent = mix(accentColor1, accentColor2, SIN(t*pi));
    vec3 origBg     = mix(secondColor1, secondColor2, SIN(t*pi));
    vec3 sectAccent = mix(accentColor1, accentColor2, SIN(sidPhase * 1.7));
    vec3 sectBg     = mix(secondColor1, secondColor2, SIN(sidPhase * 2.3));
    accent = mix(origAccent, sectAccent, palBpsActive);
    bg     = mix(origBg,     sectBg,     palBpsActive);

    float turn = (.1-m.x)*twopi;
    float s = sin(turn);
    float c = cos(turn);
    mat3 rotX = mat3(c,  0., s, 0., 1., 0., s,  0., -c);

    // Sample Audio (Low Frequency) — original per-jelly pump term.
    g_audio = texture(iChannel0, vec2(0.05, 0.25)).x;
    g_audio = pow(g_audio, 3.0) * 2.0;

    #ifdef SINGLE
    float camDist = -10.;
    #else
    float camDist = -.1;
    #endif

    vec3 lookAt = vec3(0., -1., 0.);

    vec3 camPos = vec3(0., INVERTMOUSE*camDist*cos((m.y)*pi), camDist)*rotX;

    CameraSetup(uv, camPos+lookAt, lookAt, 1.);

    // CedarToy Panoramic Override
    if (iCameraMode == 1) { // Equirectangular
        vec2 q = fragCoord.xy / iResolution.xy;
        float lon = (q.x * 2.0 - 1.0) * pi;
        float lat = (q.y * 2.0 - 1.0) * halfpi;

        vec3 sphereDir;
        sphereDir.x = cos(lat) * sin(lon);
        sphereDir.y = sin(lat);
        sphereDir.z = cos(lat) * cos(lon);

        cam.ray.d = normalize(sphereDir.x * cam.left + sphereDir.y * cam.up + sphereDir.z * cam.forward);
    } else if (iCameraMode == 2) { // LL180 (Dome)
        vec2 q = fragCoord.xy / iResolution.xy;

        vec3 domeForward = vec3(0., 0., 1.);
        vec3 domeUp = vec3(0., 1., 0.);
        vec3 domeRight = vec3(1., 0., 0.);

        mat3 camBasis = mat3(domeRight, domeUp, domeForward);

        cam.ray.d = cameraDirLL180(q, iCameraTiltDeg, camBasis);
    }

    // Camera musicality intentionally omitted — no beat-driven roll,
    // zoom, or push. All audio reactivity lives in deformations
    // (body pump, tentacle sway) and colour (group accents, glow nodes,
    // section palette).

    vec3 col = render(uv, cam.ray, 0.);

    col = max(vec3(0.), col); // Safety clamp to prevent NaN in pow
    col = pow(col, vec3(mix(1.5, 2.6, SIN(t+pi))));        // post-processing
    float d = 1.-dot(uv, uv);        // vignette
    col *= (d*d*d)+.1;

    fragColor = vec4(col, 1.);
}