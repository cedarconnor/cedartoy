// Name: Preview Test
// Description: Simple animated gradient for testing WebGL preview

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    // Normalize coordinates to 0-1
    vec2 uv = fragCoord / iResolution.xy;

    // Animated colors
    vec3 color = vec3(
        0.5 + 0.5 * sin(iTime + uv.x * 3.0),
        0.5 + 0.5 * cos(iTime + uv.y * 3.0),
        0.5 + 0.5 * sin(iTime + uv.x * 2.0 + uv.y * 2.0)
    );

    fragColor = vec4(color, 1.0);
}
