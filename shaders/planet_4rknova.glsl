
// by Nikos Papadopoulos, 4rknova / 2015
// Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.

#define EPS		.001
//#define PI		3.14159265359 // defined in header.glsl
#define RADIAN	180. / PI
#define SPEED	25.

float hash(in float n) { return fract(sin(n)*43758.5453123); }

float hash(vec2 p)
{
    return fract(sin(dot(p,vec2(127.1,311.7))) * 43758.5453123);
}

// Rename noise to avoid conflict if header has one, though header.glsl doesn't seem to have 'noise'.
float noise(vec2 p)
{
    vec2 i = floor(p), f = fract(p); 
	f *= f*(3.-2.*f);
    
    vec2 c = vec2(0,1);
    
    return mix(mix(hash(i + c.xx), 
                   hash(i + c.yx), f.x),
               mix(hash(i + c.xy), 
                   hash(i + c.yy), f.x), f.y);
}

float fbm(in vec2 p)
{
	return	.5000 * noise(p)
		   +.2500 * noise(p * 2.)
		   +.1250 * noise(p * 4.)
		   +.0625 * noise(p * 8.);
}

float dst(vec3 p)
{
	return dot(vec3(p.x, p.y
                    + 0.45 * fbm(p.zx) 
                    + 2.55 * noise(.1 * p.xz) 
                    + 0.83 * noise(.4 * p.xz)
                    + 3.33 * noise(.001 * p.xz)
                    + 3.59 * noise(.0005 * (p.xz + 132.453)) 
                    , p.z),  vec3(0.,1.,0.));	
}

vec3 nrm(vec3 p, float d)
{
	return normalize(
			vec3(dst(vec3(p.x + EPS, p.y, p.z)),
    			 dst(vec3(p.x, p.y + EPS, p.z)),
    			 dst(vec3(p.x, p.y, p.z + EPS))) - d);
}

bool rmarch(vec3 ro, vec3 rd, out vec3 p, out vec3 n)
{
	p = ro;
	vec3 pos = p;
	float d = 1.;

	for (int i = 0; i < 64; i++) {
		d = dst(pos);

		if (d < EPS) {
			p = pos;
			break;
		}
		pos += d * rd;
	}
	
	n = nrm(p, d);
	return d < EPS;
}

vec4 render(vec2 uv)
{
    float t = iTime;
    
    // UVN is aspect corrected UV
    vec2 uvn = (uv) * vec2(iResolution.x / iResolution.y, 1.);
	
    float vel = SPEED * t;
    
	vec3 cu = vec3(2. * noise(vec2(.3 * t)) - 1.,1., 1. * fbm(vec2(.8 * t)));
	vec3 cp = vec3(0, 3.1 + noise(vec2(t)) * 3.1, vel);
	vec3 ct = vec3(1.5 * sin(t), 
				   -2. + cos(t) + fbm(cp.xz) * .4, 13. + vel);
		
	vec3 ro = cp,
		 rd = normalize(vec3(uvn, 1. / tan(60. * RADIAN)));
	
	vec3 cd = ct - cp,
		 rz = normalize(cd),
		 rx = normalize(cross(rz, cu)),
		 ry = normalize(cross(rx, rz));

    mat3 basis = mat3(rx, ry, rz);
	rd = normalize(basis * rd);
    
    // CedarToy VR/360 Override
    if (iCameraMode == 1) { // Equirectangular
        vec2 q = uv * 0.5 + 0.5; // uv is -1..1 from mainImage
        float lon = (q.x * 2.0 - 1.0) * PI;
        float lat = (q.y * 2.0 - 1.0) * (PI * 0.5);
        vec3 dir;
        dir.x = cos(lat) * sin(lon);
        dir.y = sin(lat);
        dir.z = cos(lat) * cos(lon);
        // Transform by camera basis (rz is forward, rx right, ry up)
        // Need to check basis orientation.
        // rz matches cd (lookdir).
        // rx matches right.
        // ry matches up.
        // My manual construction: dir.z is forward (cos(0)*cos(0)=1).
        // rx,ry,rz are columns.
        // M * v = x*vx + y*vy + z*vz
        // So rx*dir.x + ry*dir.y + rz*dir.z
        // Standard equirect: x is right (sin lon), y is up (sin lat), z is forward (cos cos).
        // Matches.
        rd = normalize(basis * dir);
    } else if (iCameraMode == 2) { // LL180
         vec2 q = uv * 0.5 + 0.5;
         rd = cameraDirLL180(q, iCameraTiltDeg, basis);
    }

	vec3 sp, sn;
	vec3 col = (rmarch(ro, rd, sp, sn) ?
		  vec3(.6) * dot(sn, normalize(vec3(cp.x, cp.y + .5, cp.z) - sp))
		: vec3(0.));
	
	return vec4(col, length(ro-sp));
}

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    vec2 uv = fragCoord.xy / iResolution.xy * 2. - 1.;
        

	
    vec4 res = render(uv);
    
    vec3 col = res.xyz;
    
    col *= 1.75 * smoothstep(length(uv) * .35, .75, .4);
    float n = hash((hash(uv.x) + uv.y) * iTime) * .15; // renamed 'noise' var to 'n'
	col += n;
	// col *= smoothstep(EPS, 3.5, iTime);

    fragColor = vec4(col, 1);
}
