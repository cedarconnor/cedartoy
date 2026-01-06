
// Removed #version as per header

/*
	Bumped Sinusoidal Warp
*/

vec2 W(vec2 p){
    p = (p + 3.)*4.;
    float t = iTime/2.;
    for (int i=0; i<3; i++){
        p += cos(p.yx*3. + vec2(t, 1.57))/3.;
        p += sin(p.yx + t + vec2(1.57, 0))/2.;
        p *= 1.3;
    }
    p += fract(sin(p+vec2(13, 7))*5e5)*.03 - .015;
    return mod(p, 2.) - 1.; 
}

float bumpFunc(vec2 p){ 
	return length(W(p))*.7071; 
}

vec3 smoothFract(vec3 x){ x = fract(x); return min(x, x*(1.-x)*12.); }

// Manual Ray-Plane intersection for VR mode
vec3 intersectPlane(vec3 ro, vec3 rd, vec3 planeNormal, float planeDist) {
    // Plane: dot(p, n) = d
    // Ray: p = ro + t*rd
    // dot(ro + t*rd, n) = d
    // dot(ro, n) + t*dot(rd, n) = d
    // t = (d - dot(ro, n)) / dot(rd, n)
    float denom = dot(rd, planeNormal);
    if (abs(denom) < 1e-4) return vec3(0.); // Parallel
    float t = (planeDist - dot(ro, planeNormal)) / denom;
    if (t < 0.) return vec3(0.); // Behind
    return ro + t * rd;
}

void mainImage( out vec4 fragColor, in vec2 fragCoord ){

    // Screen coordinates.
	vec2 uv = (fragCoord - iResolution.xy*.5)/iResolution.y;
    
    // Default setup
    vec3 sp = vec3(uv, 0); 
    vec3 rd = normalize(vec3(uv, 1)); 
    vec3 lp = vec3(cos(iTime)*.5, sin(iTime)*.2, -1); 
	vec3 sn = vec3(0, 0, -1); 
 
    // VR Override
    if (iCameraMode > 0) {
        vec2 q = fragCoord.xy / iResolution.xy;
        // Basis: Standard (Right, Up, Forward=Z)
        // Original shader thinks screen is at Z=0?
        // rd = normalize(uv, 1). z=1. So forward is +Z.
        mat3 basis = mat3(
            vec3(1,0,0),
            vec3(0,1,0),
            vec3(0,0,1)
        );
        
        vec3 vrRd; 
        if (iCameraMode == 1) { // Equirect
             float lon = (q.x * 2.0 - 1.0) * PI;
             float lat = (q.y * 2.0 - 1.0) * (PI * 0.5);
             vec3 dir;
             dir.x = cos(lat) * sin(lon);
             dir.y = sin(lat);
             dir.z = cos(lat) * cos(lon);
             vrRd = normalize(basis * dir);
        } else if (iCameraMode == 2) { // LL180
            vrRd = cameraDirLL180(q, iCameraTiltDeg, basis);
        }
        
        // Ray intersect Plane at Z=0
        vec3 ro = vec3(0, 0, -1); // Assume camera is back a bit, or use shader's implicit camera
        // Original: sp = vec3(uv, 0). Camera is implicitly at (0,0,-1) looking at Z=0?
        // The shader says "From the origin to the screen plane".
        // If screen plane is at Z=0. Camera at origin? No, rd=normalize(uv, 1).
        // That implies camera at (0,0,0) and plane at Z=1.
        // But 'sp' is defined as (uv, 0).
        // Let's stick to the 2D logic: sp is key.
        // If we want to map this to 360, we assume the user is at (0,0,-1) looking at a wall at Z=0.
        // We intersect that wall.
        
        vec3 p = intersectPlane(ro, vrRd, vec3(0,0,-1), 0.0); // Plane normal -Z (facing viewer), dist 0.
        // Check intersection validity (if length is 0, we missed or parallel, but intersect returns 0 vec if t<0)
        // A better check is needed.
        float denom = dot(vrRd, vec3(0,0,-1));
        float t = (0.0 - dot(ro, vec3(0,0,-1))) / denom;
        
        if (t > 0.0) {
            sp = ro + t * vrRd;
            rd = vrRd;
            // sn = vec3(0,0,-1) is consistent.
            // But we need to update LIGHTING vectors?
            // "vec3 ld = lp - sp;" <- uses sp.
            // "rd" is used for specular.
            // So we just need valid sp and rd.
        } else {
            // Hit nothing (background)
            fragColor = vec4(0.1, 0.1, 0.1, 1.0);
            return;
        }
    }
 
    // ... BUMP MAPPING code ...
    // Note: bumpFunc uses sp.xy.
    
    vec2 eps = vec2(4./iResolution.y, 0);
    
    float f = bumpFunc(sp.xy); 
    float fx = bumpFunc(sp.xy - eps.xy); 
    float fy = bumpFunc(sp.xy - eps.yx); 
   
	const float bumpFactor = .05;
    
    fx = (fx - f)/eps.x; 
    fy = (fy - f)/eps.x; 
    sn = normalize(sn + vec3(fx, fy, 0)*bumpFactor);   
   
	vec3 ld = lp - sp;
	float lDist = max(length(ld), .0001);
	ld /= lDist;

    float atten = 1./(1. + lDist*lDist*.15);
    atten *= f*.9 + .1; 

	float diff = max(dot(sn, ld), 0.);  
    diff = pow(diff, 4.)*.66 + pow(diff, 8.)*.34; 
    float spec = pow(max(dot( reflect(-ld, sn), -rd), 0.), 12.); 
    
    vec3 texCol = texture(iChannel0, sp.xy + W(sp.xy)/8.).xyz; 
    texCol *= texCol; 
    texCol = smoothstep(.05, .75, pow(texCol, vec3(.75, .8, .85)));    
    
    vec3 col = (texCol*(diff*vec3(1, .97, .92)*2. + .5) + vec3(1, .6, .2)*spec*2.)*atten;
    
    float ref = max(dot(reflect(rd, sn), vec3(1)), 0.);
    col += col*pow(ref, 4.)*vec3(.25, .5, 1)*3.;

	fragColor = vec4(sqrt(clamp(col, 0., 1.)), 1);
}
