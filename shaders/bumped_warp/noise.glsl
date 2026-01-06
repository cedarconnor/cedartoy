
// uniform vec2 iResolution; // In header
// uniform float iTime; // In header

// Simple procedural noise to serve as texture input
float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
    vec2 uv = fragCoord.xy / iResolution.xy;
    vec3 col = vec3(hash(uv * 100.0 + iTime * 0.1));
    fragColor = vec4(col, 1.0);
}
