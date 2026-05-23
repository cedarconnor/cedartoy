// Auroras by nimitz 2017 (twitter: @stormoid)
// License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License
// Contact the author for other licensing options
//
// MusiCue-reactive modifications:
//   - Half-note radial wave from directly overhead the camera drives an
//     additive twist offset inside the noise inner loop (sharp attack,
//     soft exponential decay). The wave's leading edge sweeps outward
//     so different regions of the aurora respond at different moments,
//     not as a global pulse.
//   - Section id shifts the aurora's per-channel colour phase so verse,
//     chorus, and bridge each have a distinct palette identity.
//   - Section energy gently extends how high the upper aurora layers reach.
//   - Kick band slightly amplifies the wave so big drops feel weightier
//     without changing the rhythm.
//   - Melodic band tints the brightest pixels (highlight wash, not a strobe).
//   - All modulations gate on iBpm so the shader looks identical to the
//     original when no song is playing.
//
// cookbook_version: 2

#define time iTime

// MusiCue bundle uniforms — declared per the cookbook convention so the
// headless render compiles. (The web preview auto-declares these too.)
uniform float iBpm;
uniform float iBeat;
uniform float iSectionEnergy;
uniform int   iSectionId;
uniform float iEnergy;

mat2 mm2(in float a){float c = cos(a), s = sin(a);return mat2(c,s,-s,c);}
mat2 m2 = mat2(0.95534, 0.29552, -0.29552, 0.95534);
float tri(in float x){return clamp(abs(fract(x)-.5),0.01,0.49);}
vec2 tri2(in vec2 p){return vec2(tri(p.x)+tri(p.y),tri(p.y+tri(p.x)));}

// triNoise2d gains an additive `twist` angle offset on the per-octave
// rotation. twist is added, never multiplied with time, so audio
// modulation can never become a rate that spirals out at large iTime.
float triNoise2d(in vec2 p, float spd, float twist)
{
    float z=1.8;
    float z2=2.5;
    float rz = 0.;
    p *= mm2(p.x*0.06);
    vec2 bp = p;
    for (float i=0.; i<5.; i++ )
    {
        vec2 dg = tri2(bp*1.85)*.75;
        dg *= mm2(time*spd + twist);   // additive twist offset
        p -= dg/z2;

        bp *= 1.3;
        z2 *= .45;
        z *= .42;
        p *= 1.21 + (rz-1.0)*.02;

        rz += tri(p.x+tri(p.y))*z;
        p*= -m2;
    }
    return clamp(1./pow(rz*29., 1.3),0.,.55);
}

float hash21(in vec2 n){ return fract(sin(dot(n, vec2(12.9898, 4.1414))) * 43758.5453); }

vec4 aurora(vec3 ro, vec3 rd)
{
    vec4 col = vec4(0);
    vec4 avgCol = vec4(0);

    // Gate: zero when no bundle/BPM, one when a song is active.
    float bpsActive = step(1.0, iBpm);

    // === wave_from_center_halfnote (cookbook_version 2) ===
    // noise twist ← spatial wave radiating outward on half-notes
    // Continuous tempo clock (NOT iBeat, which would snap every beat).
    // Phase wraps once per half-note; pixels further from the centre
    // receive the wavefront later, producing a visible sweep across
    // the aurora rather than a uniform pulse.
    float halfNoteIdx   = iTime * iBpm / 60.0 * 0.5;
    float halfNotePhase = fract(halfNoteIdx);
    vec2  waveCenter    = vec2(0.0, -6.7);   // xz of point directly above the camera

    // === section_palette_drift (cookbook_version 2) ===
    // aurora sin-phase ← iSectionId — verse / chorus / bridge each shift colour
    vec3 sectionShift = sin(float(iSectionId) * 1.7 + vec3(0.0, 2.094, 4.189)) * 0.45 * bpsActive;

    // === section_reach_swell (cookbook_version 2) ===
    // upper layer altitude ← iSectionEnergy — choruses extend a touch higher
    float reachBoost = 1.0 + iSectionEnergy * 0.18 * bpsActive;

    // === kick_amp_modulation (cookbook_version 2) ===
    // wave amplitude ← kick band — big low end deepens the sweep without
    // adding a separate strobe
    float kickBand = texture(iChannel0, vec2(0.03, 0.25)).r;

    for(float i=0.;i<50.;i++)
    {
        float of = 0.006*hash21(gl_FragCoord.xy)*smoothstep(0.,15., i);
        float pt = ((.8 + pow(i,1.4)*.002 * reachBoost) - ro.y) / (rd.y*2.+0.4);
        pt -= of;
        vec3 bpos = ro + pt*rd;
        vec2 p = bpos.zx;

        // Spatial wave envelope at this sample.
        // Sharp attack (smoothstep 0..0.06), gentle exp decay (~2.4/sec at BPM 120).
        float r          = length(bpos.xz - waveCenter);
        float waveT      = halfNotePhase - r * 0.026;
        float waveAttack = smoothstep(0.0, 0.06, waveT);
        float waveDecay  = exp(-max(waveT, 0.0) * 2.4);
        float wave       = waveAttack * waveDecay * step(0.0, waveT) * bpsActive;

        // Additive angular twist — bounded, never multiplied with iTime
        float twist = wave * (0.32 + kickBand * 0.18) * (0.65 + 0.35 * iSectionEnergy);

        float rzt = triNoise2d(p, 0.06, twist);
        vec4 col2 = vec4(0,0,0, rzt);
        col2.rgb = (sin(1. - vec3(2.15,-.5, 1.2) + sectionShift + i*0.043)*0.5+0.5)*rzt;
        avgCol =  mix(avgCol, col2, .5);
        col += avgCol*exp2(-i*0.065 - 2.5)*smoothstep(0.,5., i);
    }

    col *= (clamp(rd.y*15.+.4,0.,1.));

    return col*1.8;
}


//-------------------Background and Stars--------------------

vec3 nmzHash33(vec3 q)
{
    uvec3 p = uvec3(ivec3(q));
    p = p*uvec3(374761393U, 1103515245U, 668265263U) + p.zxy + p.yzx;
    p = p.yzx*(p.zxy^(p >> 3U));
    return vec3(p^(p >> 16U))*(1.0/vec3(0xffffffffU));
}

vec3 stars(in vec3 p)
{
    vec3 c = vec3(0.);
    float res = iResolution.x*1.;

    for (float i=0.;i<4.;i++)
    {
        vec3 q = fract(p*(.15*res))-0.5;
        vec3 id = floor(p*(.15*res));
        vec2 rn = nmzHash33(id).xy;
        float c2 = 1.-smoothstep(0.,.6,length(q));
        c2 *= step(rn.x,.0005+i*i*0.001);
        c += c2*(mix(vec3(1.0,0.49,0.1),vec3(0.75,0.9,1.),rn.y)*0.1+0.9);
        p *= 1.3;
    }
    return c*c*.8;
}

vec3 bg(in vec3 rd)
{
    float sd = dot(normalize(vec3(-0.5, -0.6, 0.9)), rd)*0.5+0.5;
    sd = pow(sd, 5.);
    vec3 col = mix(vec3(0.05,0.1,0.2), vec3(0.1,0.05,0.2), sd);
    return col*.63;
}
//-----------------------------------------------------------


void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    vec2 q = fragCoord.xy / iResolution.xy;
    vec2 p = q - 0.5;
    p.x*=iResolution.x/iResolution.y;

    vec3 ro = vec3(0,0,-6.7);
    vec3 rd = normalize(vec3(p,1.3));

    // vec2 mo = iMouse.xy / iResolution.xy-.5;
    vec2 mo = vec2(0.); // Default mouse
    mo = (mo==vec2(-.5))?mo=vec2(-0.1,0.1):mo;
    mo.x *= iResolution.x/iResolution.y;
    rd.yz *= mm2(mo.y);
    rd.xz *= mm2(mo.x + sin(time*0.05)*0.2);

    // CedarToy VR Logic
    if (iCameraMode > 0) {
        mat3 vrBasis = mat3(vec3(1,0,0), vec3(0,1,0), vec3(0,0,1));

        if (iCameraMode == 1) { // Equirect
             float lon = (q.x * 2.0 - 1.0) * PI;
             float lat = (q.y * 2.0 - 1.0) * (PI * 0.5);
             vec3 dir;
             dir.x = cos(lat) * sin(lon);
             dir.y = sin(lat);
             dir.z = cos(lat) * cos(lon);
             rd = normalize(dir);
        } else if (iCameraMode == 2) { // LL180
            rd = cameraDirLL180(q, iCameraTiltDeg, vrBasis);
        }
    }

    vec3 col = vec3(0.);
    vec3 brd = rd;
    float fade = smoothstep(0.,0.01,abs(brd.y))*0.1+0.9;

    col = bg(rd)*fade;

    if (rd.y > 0.){
        vec4 aur = smoothstep(0.,1.5,aurora(ro,rd))*fade;
        col += stars(rd);
        col = col*(1.-aur.a) + aur.rgb;
    }
    else //Reflections
    {
        rd.y = abs(rd.y);
        col = bg(rd)*fade*0.6;
        vec4 aur = smoothstep(0.0,2.5,aurora(ro,rd));
        col += stars(rd)*0.1;
        col = col*(1.-aur.a) + aur.rgb;
        vec3 pos = ro + ((0.5-ro.y)/rd.y)*rd;
        // water reflection stays calm (twist=0) so it reads as a baseline
        // against which the aurora dances
        float nz2 = triNoise2d(pos.xz*vec2(.5,.7), 0., 0.);
        col += mix(vec3(0.2,0.25,0.5)*0.08,vec3(0.3,0.3,0.5)*0.7, nz2*0.4);
    }

    // === melodic_glow_tint (cookbook_version 2) ===
    // brightest pixels ← melodic band — highlights pick up the melodic line
    float bpsActive = step(1.0, iBpm);
    float mid = texture(iChannel0, vec2(0.75, 0.25)).r * bpsActive;
    vec3 mtint = vec3(1.0, 0.65, 1.15);
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    if (lum > 0.35) {
        col = mix(col, col * mtint, clamp(mid, 0.0, 1.0) * 0.22);
    }

    // === energy_brightness_lift (cookbook_version 2) ===
    // overall lift ← iEnergy — gentle dynamic swell across sections
    col *= mix(1.0, 1.08, iEnergy);

    fragColor = vec4(col, 1.);
}