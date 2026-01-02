// Name: Audio Reactive Simple
// Description: Simple audio-reactive visualization using iChannel0

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;

    // Sample audio FFT (row 0 of iChannel0)
    float fftValue = texture(iChannel0, vec2(uv.x, 0.25)).r;

    // Sample audio waveform (row 1 of iChannel0)
    float waveValue = texture(iChannel0, vec2(uv.x, 0.75)).r;

    // Create bars based on FFT
    float bar = step(uv.y, fftValue * 0.5);

    // Color based on audio
    vec3 color = vec3(
        fftValue,
        0.5 + 0.5 * sin(iTime + fftValue * 10.0),
        waveValue
    );

    fragColor = vec4(color * bar, 1.0);
}
