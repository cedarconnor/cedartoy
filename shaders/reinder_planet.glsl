
// Planet Shadertoy. Created by Reinder Nijhoff 2015
// Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License.

#define HIGH_QUALITY
//#define MED_QUALITY
//#define LOW_QUALITY
//#define VERY_LOW_QUALITY

// Removed const float PI as it is in header (check if it conflicts)
// const float PI = 3.14159265359; 
// Header has PI.
const float DEG_TO_RAD = (PI / 180.0);
const float MAX = 10000.0;

const float EARTH_RADIUS = 1000.;
const float EARTH_ATMOSPHERE = 5.;
const float EARTH_CLOUDS = 1.;

const float RING_INNER_RADIUS = 1500.;
const float RING_OUTER_RADIUS = 2300.;
const float RING_HEIGHT = 2.;

#ifdef HIGH_QUALITY
    const int   SEA_NUM_STEPS = 7;
    const int	TERRAIN_NUM_STEPS = 140;
    const int   ASTEROID_NUM_STEPS = 11;
	const int	ASTEROID_NUM_BOOL_SUB = 7;
    const int   RING_VOXEL_STEPS = 25;
    const float ASTEROID_MAX_DISTANCE = 1.1; 
	const int   FBM_STEPS = 4;
    const int   ATMOSPHERE_NUM_OUT_SCATTER = 5;
    const int   ATMOSPHERE_NUM_IN_SCATTER = 7;

    #define DISPLAY_LLAMEL
    #define DISPLAY_CLOUDS
    #define DISPLAY_CLOUDS_DETAIL
    #define DISPLAY_TERRAIN_DETAIL
#endif

#ifdef MED_QUALITY
    const int   SEA_NUM_STEPS = 6;
    const int	TERRAIN_NUM_STEPS = 100;
    const int   ASTEROID_NUM_STEPS = 10;
	const int	ASTEROID_NUM_BOOL_SUB = 6;
    const int   RING_VOXEL_STEPS = 24;
    const float ASTEROID_MAX_DISTANCE = 1.; 
	const int   FBM_STEPS = 4;
    const int   ATMOSPHERE_NUM_OUT_SCATTER = 4;
    const int   ATMOSPHERE_NUM_IN_SCATTER = 6;
    #define DISPLAY_CLOUDS
    #define DISPLAY_TERRAIN_DETAIL
    #define DISPLAY_CLOUDS_DETAIL
#endif

#ifdef LOW_QUALITY
    const int   SEA_NUM_STEPS = 5;
    const int	TERRAIN_NUM_STEPS = 75;
    const int   ASTEROID_NUM_STEPS = 9;
    const int	ASTEROID_NUM_BOOL_SUB = 5;
    const int   RING_VOXEL_STEPS = 20;
    const float ASTEROID_MAX_DISTANCE = .85; 
	const int   FBM_STEPS = 3;
    const int   ATMOSPHERE_NUM_OUT_SCATTER = 3;
    const int   ATMOSPHERE_NUM_IN_SCATTER = 5;
#endif

#ifdef VERY_LOW_QUALITY
    const int   SEA_NUM_STEPS = 4;
    const int	TERRAIN_NUM_STEPS = 60;
    const int   ASTEROID_NUM_STEPS = 7;
	const int	ASTEROID_NUM_BOOL_SUB = 4;
    const int   RING_VOXEL_STEPS = 16;
    const float ASTEROID_MAX_DISTANCE = .67; 
	const int   FBM_STEPS = 3;
    const int   ATMOSPHERE_NUM_OUT_SCATTER = 2;
    const int   ATMOSPHERE_NUM_IN_SCATTER = 4;
	#define HIDE_TERRAIN
#endif

const vec3  SUN_DIRECTION = vec3( .940721,  .28221626, .18814417 );
const vec3  SUN_COLOR = vec3(.3, .21, .165);

float time;

//-----------------------------------------------------
// Noise functions
//-----------------------------------------------------

float hash( const in float n ) {
    return fract(sin(n)*43758.5453123);
}
float hash( const in vec2 p ) {
	float h = dot(p,vec2(127.1,311.7));	
    return fract(sin(h)*43758.5453123);
}
float hash( const in vec3 p ) {
	float h = dot(p,vec3(127.1,311.7,758.5453123));	
    return fract(sin(h)*43758.5453123);
}
vec3 hash31( const in float p) {
	vec3 h = vec3(1275.231,4461.7,7182.423) * p;	
    return fract(sin(h)*43758.543123);
}
vec3 hash33( const in vec3 p) {
    return vec3( hash(p), hash(p.zyx), hash(p.yxz) );
}

float noise( const in  float p ) {    
    float i = floor( p );
    float f = fract( p );	
	float u = f*f*(3.0-2.0*f);
    return -1.0+2.0* mix( hash( i + 0. ), hash( i + 1. ), u);
}

float noise( const in  vec2 p ) {    
    vec2 i = floor( p );
    vec2 f = fract( p );	
	vec2 u = f*f*(3.0-2.0*f);
    return -1.0+2.0*mix( mix( hash( i + vec2(0.0,0.0) ), 
                     hash( i + vec2(1.0,0.0) ), u.x),
                mix( hash( i + vec2(0.0,1.0) ), 
                     hash( i + vec2(1.0,1.0) ), u.x), u.y);
}
float noise( const in  vec3 x ) {
    vec3 p = floor(x);
    vec3 f = fract(x);
    f = f*f*(3.0-2.0*f);
    float n = p.x + p.y*157.0 + 113.0*p.z;
    return mix(mix(mix( hash(n+  0.0), hash(n+  1.0),f.x),
                   mix( hash(n+157.0), hash(n+158.0),f.x),f.y),
               mix(mix( hash(n+113.0), hash(n+114.0),f.x),
                   mix( hash(n+270.0), hash(n+271.0),f.x),f.y),f.z);
}

float tri( const in vec2 p ) {
    return 0.5*(cos(6.2831*p.x) + cos(6.2831*p.y));
   
}

const mat2 m2 = mat2( 0.80, -0.60, 0.60, 0.80 );

float fbm( in vec2 p ) {
    float f = 0.0;
    f += 0.5000*noise( p ); p = m2*p*2.02;
    f += 0.2500*noise( p ); p = m2*p*2.03;
    f += 0.1250*noise( p ); 
    
#ifndef LOW_QUALITY
#ifndef VERY_LOW_QUALITY
    p = m2*p*2.01;
    f += 0.0625*noise( p );
#endif
#endif
    return f/0.9375;
}

float fbm( const in vec3 p, const in float a, const in float f) {
    float ret = 0.0;    
    float amp = 1.0;
    float frq = 1.0;
    for(int i = 0; i < FBM_STEPS; i++) {
        float n = pow(noise(p * frq),2.0);
        ret += n * amp;
        frq *= f;
        amp *= a * (pow(n,0.2));
    }
    return ret;
}

float fbm( const in vec3 p ) {
    return fbm( p, 0.5, 2.0 );
}

//-----------------------------------------------------
// Lightning functions
//-----------------------------------------------------

float diffuse( const in vec3 n, const in vec3 l) { 
    return clamp(dot(n,l),0.,1.);
}

float specular( const in vec3 n, const in vec3 l, const in vec3 e, const in float s) {    
    float nrm = (s + 8.0) / (3.1415 * 8.0);
    return pow(max(dot(reflect(e,n),l),0.0),s) * nrm;
}

float fresnel( const in vec3 n, const in vec3 e, float s ) {
    return pow(clamp(1.-dot(n,e), 0., 1.),s);
}

//-----------------------------------------------------
// Math functions
//-----------------------------------------------------

vec2 rotate(float angle, vec2 v) {
    return vec2(cos(angle) * v.x + sin(angle) * v.y, cos(angle) * v.y - sin(angle) * v.x);
}

float boolSub(float a,float b) { 
    return max(a,-b); 
}
float sphere(vec3 p,float r) {
	return length(p)-r;
}

//-----------------------------------------------------
// Intersection functions (by iq)
//-----------------------------------------------------

vec3 nSphere( in vec3 pos, in vec4 sph ) {
    return (pos-sph.xyz)/sph.w;
}

float iSphere( in vec3 ro, in vec3 rd, in vec4 sph ) {
	vec3 oc = ro - sph.xyz;
	float b = dot( oc, rd );
	float c = dot( oc, oc ) - sph.w*sph.w;
	float h = b*b - c;
	if( h<0.0 ) return -1.0;
	return -b - sqrt( h );
}

float iCSphereF( vec3 p, vec3 dir, float r ) {
	float b = dot( p, dir );
	float c = dot( p, p ) - r * r;
	float d = b * b - c;
	if ( d < 0.0 ) return -MAX;
	return -b + sqrt( d );
}

vec2 iCSphere2( vec3 p, vec3 dir, float r ) {
	float b = dot( p, dir );
	float c = dot( p, p ) - r * r;
	float d = b * b - c;
	if ( d < 0.0 ) return vec2( MAX, -MAX );
	d = sqrt( d );
	return vec2( -b - d, -b + d );
}

vec3 nPlane( in vec3 ro, in vec4 obj ) {
    return obj.xyz;
}

float iPlane( in vec3 ro, in vec3 rd, in vec4 pla ) {
    return (-pla.w - dot(pla.xyz,ro)) / dot( pla.xyz, rd );
}

//-----------------------------------------------------
// Wet stone by TDM
// 
// https://www.shadertoy.com/view/ldSSzV
//-----------------------------------------------------

const float ASTEROID_TRESHOLD 	= 0.001;
const float ASTEROID_EPSILON 	= 1e-6;
const float ASTEROID_DISPLACEMENT = 0.1;
const float ASTEROID_RADIUS = 0.13;

const vec3  RING_COLOR_1 = vec3(0.42,0.3,0.2);
const vec3  RING_COLOR_2 = vec3(0.41,0.51,0.52);

float asteroidRock( const in vec3 p, const in vec3 id ) {  
    float d = sphere(p,ASTEROID_RADIUS);    
    for(int i = 0; i < ASTEROID_NUM_BOOL_SUB; i++) {
        float ii = float(i)+id.x;
        float r = (ASTEROID_RADIUS*2.5) + ASTEROID_RADIUS*hash(ii);
        vec3 v = normalize(hash31(ii) * 2.0 - 1.0);
    	d = boolSub(d,sphere(p+v*r,r * 0.8));       
    }
    return d;
}

float asteroidMap( const in vec3 p, const in vec3 id) {
    float d = asteroidRock(p, id) + noise(p*4.0) * ASTEROID_DISPLACEMENT;
    return d;
}

float asteroidMapDetailed( const in vec3 p, const in vec3 id) {
    float d = asteroidRock(p, id) + fbm(p*4.0,0.4,2.96) * ASTEROID_DISPLACEMENT;
    return d;
}

void asteroidTransForm(inout vec3 ro, const in vec3 id ) {
    float xyangle = (id.x-.5)*time*2.;
    ro.xy = rotate( xyangle, ro.xy );
    
    float yzangle = (id.y-.5)*time*2.;
    ro.yz = rotate( yzangle, ro.yz );
}

void asteroidUnTransForm(inout vec3 ro, const in vec3 id ) {
    float yzangle = (id.y-.5)*time*2.;
    ro.yz = rotate( -yzangle, ro.yz );

    float xyangle = (id.x-.5)*time*2.;
    ro.xy = rotate( -xyangle, ro.xy );  
}

vec3 asteroidGetNormal(vec3 p, vec3 id) {
    asteroidTransForm( p, id );
    
    vec3 n;
    n.x = asteroidMapDetailed(vec3(p.x+ASTEROID_EPSILON,p.y,p.z), id);
    n.y = asteroidMapDetailed(vec3(p.x,p.y+ASTEROID_EPSILON,p.z), id);
    n.z = asteroidMapDetailed(vec3(p.x,p.y,p.z+ASTEROID_EPSILON), id);
    n = normalize(n-asteroidMapDetailed(p, id));
    
    asteroidUnTransForm( n, id );
    return n;
}

vec2 asteroidSpheretracing(vec3 ori, vec3 dir, vec3 id) {
    asteroidTransForm( ori, id );
    asteroidTransForm( dir, id );
    
    vec2 td = vec2(0,1);
    for(int i = 0; i < ASTEROID_NUM_STEPS && abs(td.y) > ASTEROID_TRESHOLD; i++) {
        td.y = asteroidMap(ori + dir * td.x, id);
        td.x += td.y;
    }
    return td;
}

vec3 asteroidGetStoneColor(vec3 p, float c, vec3 l, vec3 n, vec3 e) {
	return mix( diffuse(n,l)*RING_COLOR_1*SUN_COLOR, SUN_COLOR*specular(n,l,e,3.0), .5*fresnel(n,e,5.));    
}

//-----------------------------------------------------
// Ring (by me ;))
//-----------------------------------------------------

const float RING_DETAIL_DISTANCE = 40.;
const float RING_VOXEL_STEP_SIZE = .03;

vec3 ringShadowColor( const in vec3 ro ) {
    if( iSphere( ro, SUN_DIRECTION, vec4( 0., 0., 0., EARTH_RADIUS ) ) > 0. ) {
        return vec3(0.);
    }
    return vec3(1.);
}

bool ringMap( const in vec3 ro ) {
    return ro.z < RING_HEIGHT/RING_VOXEL_STEP_SIZE && hash(ro)<.5;
}

vec4 renderRingNear( const in vec3 ro, const in vec3 rd ) { 
// find startpoint 
    float d1 = iPlane( ro, rd, vec4( 0., 0., 1., RING_HEIGHT ) );
    float d2 = iPlane( ro, rd, vec4( 0., 0., 1., -RING_HEIGHT ) );
    
    float d = min( max(d1,0.), max(d2,0.) );
   
    if( (d1 < 0. && d2 < 0.) || d > ASTEROID_MAX_DISTANCE ) {
        return vec4( 0. );
    } else {
        vec3 ros = ro + rd*d;

        // avoid precision problems..
        vec2 mroxy = mod(ros.xy, vec2(10.));
        vec2 roxy = ros.xy - mroxy;
        ros.xy -= roxy;
        ros /= RING_VOXEL_STEP_SIZE;
        //ros.xy -= vec2(.013,.112)*time*.5;

        vec3 pos = floor(ros);
        vec3 ri = 1.0/rd;
        vec3 rs = sign(rd);
        vec3 dis = (pos-ros + 0.5 + rs*0.5) * ri;
        
        float alpha = 0., col = 0.;
        if( ringMap( pos ) ) { alpha = 1.; col = hash(pos); }
        
        for( int i=0; i<RING_VOXEL_STEPS; i++ ) {
            if( alpha > 0.95 ) continue;
            vec3 mm = step(dis.xyz, dis.yxy) * step(dis.xyz, dis.zzx);
            dis += mm * rs * ri;
            pos += mm * rs;
            if( ringMap( pos ) ) { 
                float iAlpha = (1.-alpha);
                alpha += iAlpha; 
                col += iAlpha*hash(pos); 
            }
        }
        return vec4( vec3(col), alpha );
    }
    return vec4(0.);
}

vec3 renderRingFar( const in vec3 ro, const in vec3 rd, inout float maxd ) {
    // intersect ring
    float d1 = iPlane( ro, rd, vec4( 0., 0., 1., RING_HEIGHT ) );
    float d2 = iPlane( ro, rd, vec4( 0., 0., 1., -RING_HEIGHT ) );
    
    float d = min( max(d1,0.), max(d2,0.) );
    
    if( d > maxd && d1 > 0. && d2 > 0. ) return vec3(0.);
    
    if( (d1 < 0. && d2 < 0.) || d > MAX ) {
        return vec3( 0. );
    } else {
    	// intersect ring
        float d = (d1+d2)*.5;
        
        if( d < maxd ) {
            maxd = d;
            
            vec3 p = ro + rd*d;
            float l = length(p.xy);
            
            if( l > RING_INNER_RADIUS && l < RING_OUTER_RADIUS ) {
                float f = (l-RING_INNER_RADIUS) / (RING_OUTER_RADIUS-RING_INNER_RADIUS);
                
                float dens = 1.3;//texture( iChannel0, vec2(f,0.) ).x;
                dens *= 1.5;
                
                return mix( RING_COLOR_1, RING_COLOR_2, abs( noise(l*0.002) ) ) * dens * 1.5 * abs( noise(l*0.2) );
            }
        }
    }
    return vec3(0.);
}

//-----------------------------------------------------
// Stars (by me ;))
//-----------------------------------------------------

vec3 stars( const in vec3 rd ) {
    vec3 c = vec3(0.);
    float res = iResolution.x*2.5;
    
	for( float i=0.; i<4.; i++ ) {
        vec3 q = rd * res;
        
        vec3 p = floor(abs(q));
        vec3 f = fract(q);
        
        float d = cos( 20. * sin( p.x * 23. + p.y * 23. + p.z * 13. + i ) );
        
        if( d > .99 ) {
            float v = dot(f,f); 
            v = 1. - sqrt(v);
            c += (i+1.) * v * vec3( 1. );
        }
        res *= 0.7;
    }
    return c;
}

//-----------------------------------------------------
// Atmospheric Scattering
// 
// http://gltracy.org/
// https://www.shadertoy.com/view/lslXDr
//-----------------------------------------------------

// math const
const float PI2 = 6.28318530718;
const float PI_2 = 1.57079632679;

// scatter const
const float K_R = 0.166;
const float K_M = 0.0025;
const float E = 14.3; 						// light intensity
const vec3  C_R = vec3( 0.3, 0.7, 1.0 ); 	// 1 / wavelength ^ 4
const float G_M = -0.85;					// Mie g

const float R = EARTH_RADIUS;
const float R_INNER = R + 0.0;
const float R_OUTER = R + EARTH_ATMOSPHERE;

const float SCALE_H = 4.0 / ( R_OUTER - R_INNER );
const float SCALE_L = 1.0 / ( R_OUTER - R_INNER );

// phase function
float phase( float alpha, float g ) {
	float a = 3.0 * ( 1.0 - g * g );
	float b = 2.0 * ( 2.0 + g * g );
	float c = 1.0 + alpha * alpha;
	float d = pow( 1.0 + g * g - 2.0 * g * alpha, 1.5 );
	return ( a / b ) * ( c / d );
}

// atmospheric scattering
float atmospheric_depth( vec3 position, vec3 dir ) {
	float a = dot( dir, dir );
	float b = 2.0 * dot( dir, position );
	float c = dot( position, position ) - R_OUTER * R_OUTER;
	float det = b * b - 4.0 * a * c;
	float detSqrt = sqrt( det );
	float q = ( -b - detSqrt ) / 2.0;
	float t1 = c / q;
	return t1;
}

float horizon_depth( vec3 position, vec3 dir ) {
	float a = dot( dir, dir );
	float b = 2.0 * dot( dir, position );
	float c = dot( position, position ) - R_INNER * R_INNER;
	float det = b * b - 4.0 * a * c;
	float detSqrt = sqrt( det );
	float q = ( -b - detSqrt ) / 2.0;
	float t1 = c / q;
	return t1;
}

vec3 renderAtmosphere( vec3 eye, vec3 dir, vec3 sun_pos ) {
	float fFar = atmospheric_depth( eye, dir );
	float fHor = horizon_depth( eye, dir );
	
	if( fHor > 0.0 ) fFar = min( fFar, fHor );

	// raymarch atmosphere
	vec3 vPos = eye + dir * fFar;
	float fRayLength = fFar;
	float fStepLength = fRayLength / float(ATMOSPHERE_NUM_IN_SCATTER);
	float fScatterDepth = 0.0;
	vec2 vDepth = vec2( 0.0 );
	vec3 vAttenuate = vec3( 0.0 );
	vec3 vTotalColor = vec3( 0.0 );
	
	for( int i = 0; i < ATMOSPHERE_NUM_IN_SCATTER; i++ ) {
		// sample position (middle of the sample length)
		vec3 vSamplePos = vPos - dir * ( fStepLength * ( float(i) + 0.5 ) );
		
		// scattering factors
		float fHeight = length( vSamplePos ) - R_INNER;
		float fDepth = exp( -SCALE_H * fHeight );
        float fScatter = fDepth * fStepLength;
		fScatterDepth += fScatter;
		
		// density factors
		vec3 vSampleRay = vSamplePos;
		float fFar2 = atmospheric_depth( vSamplePos, sun_pos );
		float fRayLength2 = fFar2;
		float fStepLength2 = fRayLength2 / float(ATMOSPHERE_NUM_OUT_SCATTER);
		float fScatterDepth2 = 0.0;
		for( int j = 0; j < ATMOSPHERE_NUM_OUT_SCATTER; j++ ) {
			vec3 vSamplePos2 = vSamplePos + sun_pos * ( fStepLength2 * ( float( j ) + 0.5 ) );
			float fHeight2 = length( vSamplePos2 ) - R_INNER;
			float fDepth2 = exp( -SCALE_H * fHeight2 );
			fScatterDepth2 += fDepth2 * fStepLength2;
		}
		
		vec3 vAttenuate = exp( -fScatterDepth2 * ( C_R * K_R + K_M * 4.0 * PI ) - fScatterDepth * ( C_R * K_R + K_M * 4.0 * PI ) );
		vTotalColor += vAttenuate * fDepth * fStepLength;
	}
	
	float fAngle = dot( -dir, sun_pos );
	vec3 vMie = vTotalColor * phase( fAngle, G_M ) * K_M * E;
	vec3 vRayleigh = vTotalColor * phase( fAngle, 0.0 ) * K_R * E * C_R;
	return ( vMie + vRayleigh ) * SUN_COLOR;
}

//-----------------------------------------------------
// Ocean/Terrain/Planet functions
//-----------------------------------------------------

vec3 getAtmosphere(vec3 ro, vec3 rd) {
    return renderAtmosphere( ro, rd, SUN_DIRECTION);
}

vec3 getClouds(vec3 ro, vec3 rd);

vec3 renderPlanet( vec3 ro, vec3 rd, vec3 up, float maxd ) {
    float d = iSphere( ro, rd, vec4( 0., 0., 0., EARTH_RADIUS ) );
    
    vec3 col = vec3(0.);
    
    // atmosphere
    if( d < 0. ) {
        col = getAtmosphere(ro, rd);
        col += stars(rd);;
    } else {
        if( d > maxd ) {
             col = vec3(0.); // should render stars, but skipped to save performance
        } else {
    		vec3 p = ro + rd*d;
            vec3 n = normalize(p);
            
            // day/night
            vec3 night = vec3(0.05);  
            vec3 day = ringShadowColor(p) * 
                (vec3(0.2,0.25,0.4) + vec3(0.55,0.45,0.4)* step( 0., noise( n*5.+fbm(n*50.) ) ) ); // terrain           
            
    		// diffuse
            col = mix( night, day, smoothstep( -0.2, 0.2, dot(n, SUN_DIRECTION) ) );
            col = mix( col, vec3(0.25), .5*fbm(n*150.) );
            col += getAtmosphere(ro, rd);
        }
    }
 	
    return col;
}

//-----------------------------------------------------
// Main
//-----------------------------------------------------

void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
    time = iTime * .25;
    
	vec2 q = fragCoord.xy / iResolution.xy;
    vec2 p = -1.0 + 2.0 * q;
    p.x *= iResolution.x/iResolution.y;
    
    // camera    
    vec3 ro = vec3(0.,0.,4300.);
    vec3 ta = vec3(0.);
    
    // ro = vec3(0.,0.,2300.);
    
    ro.x = cos(time*.2)*4300.;
    ro.z = sin(time*.2)*4300.;
    ro.y = sin(time*.1)*1000.;
    
    // camera vectors
    vec3 cw = normalize( ta-ro );
    vec3 cp = vec3( 0.0, 1.0, 0.0 );
    vec3 cu = normalize( cross(cw,cp) );
    vec3 cv = normalize( cross(cu,cw) );
    vec3 rd = normalize( p.x*cu + p.y*cv + 3.5*cw ); // optics
    
    // CedarToy VR Logic
    if (iCameraMode > 0) {
        // Construct Basis from cu, cv, cw
        mat3 basis = mat3(cu, cv, cw);
        
        if (iCameraMode == 1) { // Equirect
             float lon = (q.x * 2.0 - 1.0) * PI;
             float lat = (q.y * 2.0 - 1.0) * (PI * 0.5);
             vec3 dir;
             dir.x = cos(lat) * sin(lon);
             dir.y = sin(lat);
             dir.z = cos(lat) * cos(lon);
             rd = normalize(basis * dir);
        } else if (iCameraMode == 2) { // LL180
            rd = cameraDirLL180(q, iCameraTiltDeg, basis);
        }
    }
    
    vec3 col = vec3(0.);
    
    // ring
    float maxd = MAX;
    col += renderRingFar(ro, rd, maxd);
    
    // planet + atmosphere
    col += renderPlanet(ro, rd, cp, maxd);
    
    // near ring
    vec4 ring = renderRingNear(ro, rd);
    col = mix( col, ring.xyz, ring.w );

    // asteroids
    vec3 c = vec3(0.);
    for( int i=0; i<3; i++ ) {
        // large asteroids in foreground
        float m = 3500. + float(i)*100.;
        
        vec3 roa = ro;
        roa.xy = rotate( time*0.1 + float(i)*10., roa.xy );
        
        float db = iCSphereF( roa, rd, m );
        
        if( db > 0. && db < maxd ) {
            vec3 pos = roa + rd*db;
            
            // cheap asteroid test
            if( noise(pos*.01) > .4 ) {
                // found one!
                // calculate local asteroid coordinate system
                
                vec3 id = floor(pos/120. + .5 );
                vec3 p2 = pos - id*120.;
                
               	vec2 t = asteroidSpheretracing( p2, rd, id );
                if( t.y < ASTEROID_TRESHOLD ) {
                    vec3 nor = asteroidGetNormal( p2 + t.x*rd, id );
                    c += asteroidGetStoneColor( p2, t.x, SUN_DIRECTION, nor, rd );
                }
            }
        }
    }
  	col += c;
    
    // post processing
    col = pow( col, vec3(0.5,0.6,0.7) );
    
    fragColor = vec4( col, 1.0 );
}
