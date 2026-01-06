#version 430 core

// --- Standard Shadertoy Inputs ---
uniform vec3      iResolution;           // viewport resolution (in pixels)
uniform float     iTime;                 // shader playback time (in seconds)
uniform float     iTimeDelta;            // render time (in seconds)
uniform float     iFrameRate;            // shader frame rate
uniform int       iFrame;                // shader playback frame
uniform float     iChannelTime[4];       // channel playback time (in seconds)
uniform vec3      iChannelResolution[4]; // channel resolution (in pixels)
uniform vec4      iMouse;                // mouse pixel coords. xy: current (if MLB down), zw: click
uniform sampler2D iChannel0;             // input channel. XX = 2D/Cube
uniform sampler2D iChannel1;             // input channel. XX = 2D/Cube
uniform sampler2D iChannel2;             // input channel. XX = 2D/Cube
uniform sampler2D iChannel3;             // input channel. XX = 2D/Cube
uniform vec4      iDate;                 // (year, month, day, time in seconds)
uniform float     iSampleRate;           // sound sample rate (i.e., 44100)

// --- CedarToy Extensions ---
uniform float     iDuration;             // total duration of the animation
uniform int       iPassIndex;            // index of the current pass
uniform vec2      iTileOffset;           // offset for tiled rendering
uniform vec2      iJitter;               // subpixel jitter for AA (Halton sequence)
uniform int       iSampleIndex;          // current temporal/AA sample index

// Camera / VR
uniform int       iCameraMode;           // 0=2D, 1=Equirect, 2=LL180
uniform int       iCameraStereo;         // 0=None, 1=SBS, 2=TB
uniform vec3      iCameraPos;
uniform vec3      iCameraDir;
uniform vec3      iCameraUp;
uniform float     iCameraFov;
uniform float     iCameraTiltDeg;
uniform float     iCameraIPD;

// Audio History
uniform sampler2D iAudioHistoryTex;
uniform vec3      iAudioHistoryResolution; // x=frames, y=total_rows, z=unused

// LL180 Helper Functions (as per design)
const float PI = 3.141592653589793238;

mat3 buildCameraBasis(vec3 camDir, vec3 camUp) {
    vec3 f = normalize(camDir);
    vec3 r = normalize(cross(camUp, f));
    vec3 u = cross(f, r);
    return mat3(r, u, f);
}

vec3 cameraDirLL180(vec2 uv, float tiltDeg, mat3 camBasis) {
    float lon = (uv.x * 2.0 - 1.0) * (0.5 * PI);  // -pi/2 .. pi/2
    float lat = (uv.y * 2.0 - 1.0) * (0.5 * PI);  // -pi/2 .. pi/2

    vec3 dirLocal;
    dirLocal.x = cos(lat) * sin(lon);
    dirLocal.y = sin(lat);
    dirLocal.z = cos(lat) * cos(lon);

    float tiltRad = radians(-tiltDeg);
    float c = cos(tiltRad);
    float s = sin(tiltRad);
    mat3 tiltX = mat3(
        1.0, 0.0, 0.0,
        0.0,  c, -s,
        0.0,  s,  c
    );

    dirLocal = tiltX * dirLocal;
    return normalize(camBasis * dirLocal);
}

// Audio History Helper
vec2 sampleAudioHistoryLR(float tNorm, float freqNorm) {
    float frames = iAudioHistoryResolution.x;
    float bins2  = iAudioHistoryResolution.y;
    float bins   = bins2 * 0.5;

    float x = clamp(tNorm, 0.0, 1.0);
    // Map 0..1 to 0..frames-1 pixel coords
    // actually texture coordinates are 0..1, so we just use x directly if linear interpolation is desired?
    // Design says: "x axis: time (0..1 -> earliest..latest)"
    // The design snippet:
    float frameIndex = x * (frames - 1.0);
    x = frameIndex / max(frames - 1.0, 1.0);

    float yL = clamp(freqNorm, 0.0, 1.0) * (bins / bins2);
    float yR = 0.5 + clamp(freqNorm, 0.0, 1.0) * (bins / bins2);

    float L = texture(iAudioHistoryTex, vec2(x, yL)).r;
    float R = texture(iAudioHistoryTex, vec2(x, yR)).r;
    return vec2(L, R);
}
