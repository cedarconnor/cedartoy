void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    vec2 uv = fragCoord/iResolution.xy;

    // 1. Shadertoy iChannel0 (512x2)
    // Row 0: Freq (FFT)
    // Row 1: Wave (PCM)
    float fft  = texture(iChannel0, vec2(uv.x, 0.25)).r; 
    float wave = texture(iChannel0, vec2(uv.x, 0.75)).r;
    
    // Visualize
    vec3 col = vec3(0.0);
    
    // Green line for FFT
    if (abs(uv.y - 0.25 - fft * 0.5) < 0.01) col.g = 1.0;
    
    // Blue line for Waveform
    if (abs(uv.y - 0.75 - (wave - 0.5)) < 0.01) col.b = 1.0;
    
    // 2. Audio History (if available)
    // Map bottom of screen to history
    // uv.y 0..1 -> history time? No, history texture is (Time, Freq).
    // Let's visualize history texture directly on the background.
    
    // We need to know if iAudioHistoryTex is bound.
    // In our renderer, it's uniform sampler2D iAudioHistoryTex;
    // But we need to define it in the "User Shader" part? 
    // No, header defines it. We just use it.
    
    // Sample history: x=time, y=freq
    // We'll map screen X to Frequency, Screen Y to Time (scrolling up)
    // Actually, usually waterfall is X=Freq, Y=Time.
    // The texture layout: X=Time (frames), Y=Freq (bins*channels).
    
    // Let's map UV to texture coords directly to see it.
    // Texture: X [0..1] is Time (Earliest -> Latest)
    // Texture: Y [0..1] is Frequency (Left then Right)
    
    vec3 history = texture(iAudioHistoryTex, uv).rrr;
    
    // Blend: History background, overlay lines
    col = mix(history * 0.3, col, step(0.1, length(col)));

    fragColor = vec4(col, 1.0);
}
