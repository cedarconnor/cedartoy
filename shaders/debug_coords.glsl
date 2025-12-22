void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    vec2 uv = fragCoord.xy / iResolution.xy;
    
    vec3 col = vec3(0.0);
    
    // Grid
    vec2 grid = step(0.98, fract(uv * 10.0));
    col = vec3(max(grid.x, grid.y));
    
    // Axes
    if (uv.x > 0.49 && uv.x < 0.51) col.r = 1.0; // Y axis (Red)
    if (uv.y > 0.49 && uv.y < 0.51) col.g = 1.0; // X axis (Green)
    
    // Quadrants
    if (uv.x < 0.5 && uv.y < 0.5) col.b += 0.2; // BL - Blue tint
    if (uv.x > 0.5 && uv.y > 0.5) col.r += 0.2; // TR - Red tint
    
    // FragCoord Gradient (to check pixel mapping)
    col += vec3(uv.x, uv.y, 0.0) * 0.1;

    fragColor = vec4(col, 1.0);
}
