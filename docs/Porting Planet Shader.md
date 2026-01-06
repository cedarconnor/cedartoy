

// by Nikos Papadopoulos, 4rknova / 2015
// Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.

#define EPS		.001
#define PI		3.14159265359
#define RADIAN	180. / PI
#define SPEED	25.

float hash(in float n) { return fract(sin(n)*43758.5453123); }

float hash(vec2 p)
{
    return fract(sin(dot(p,vec2(127.1,311.7))) * 43758.5453123);
}

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

	rd = normalize(mat3(rx, ry, rz) * rd);
    

	vec3 sp, sn;
	vec3 col = (rmarch(ro, rd, sp, sn) ?
		  vec3(.6) * dot(sn, normalize(vec3(cp.x, cp.y + .5, cp.z) - sp))
		: vec3(0.));
	
	return vec4(col, length(ro-sp));
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord.xy / iResolution.xy * 2. - 1.;
        
    if (abs(EPS + uv.y) >= .7) { 
		fragColor = vec4(0,0,0,1);
        return;
	}
	
    vec4 res = render(uv);
    
    vec3 col = res.xyz;
    
    col *= 1.75 * smoothstep(length(uv) * .35, .75, .4);
    float noise = hash((hash(uv.x) + uv.y) * iTime) * .15;
	col += noise;
	col *= smoothstep(EPS, 3.5, iTime);

    fragColor = vec4(col, 1);
}



### User Input

buffer A: const float PI = acos(-1.0);
const float TAU = PI + PI;
const float FAR = 30.0;

const int SAMPLES_PER_FRAME = 15;
const int TRAVERSAL_STEPS = 30;

#define saturate(x) clamp(x, 0.0, 1.0)
#define linearstep(a, b, x) min(max(((x) - (a)) / ((b) - (a)), 0.0), 1.0)

// == common =======================================================================================
uvec3 seed;

// https://www.shadertoy.com/view/XlXcW4
vec3 hash3f( vec3 s ) {
  uvec3 r = floatBitsToUint( s );
  r = ( ( r >> 16u ) ^ r.yzx ) * 1111111111u;
  r = ( ( r >> 16u ) ^ r.yzx ) * 1111111111u;
  r = ( ( r >> 16u ) ^ r.yzx ) * 1111111111u;
  return vec3( r ) / float( -1u );
}

vec2 cis(float t) {
  return vec2(cos(t), sin(t));
}

mat2 rotate2D(float t) {
  return mat2(cos(t), -sin(t), sin(t), cos(t));
}

mat3 orthBas(vec3 z) {
  z = normalize(z);
  vec3 up = abs(z.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
  vec3 x = normalize(cross(up, z));
  return mat3(x, cross(z, x), z);
}

// == noise ========================================================================================
vec3 cyclicNoise(vec3 p, float pers) {
  vec4 sum = vec4(0.0);

  for (int i = 0; i ++ < 4;) {
    p *= orthBas(vec3(-1.0, 2.0, -3.0));
    p += sin(p.yzx);
    sum = (sum + vec4(cross(sin(p.zxy), cos(p)), 1.0)) / pers;
    p *= 2.0;
  }

  return sum.xyz / sum.w;
}

// == isects =======================================================================================
vec4 isectBox(vec3 ro, vec3 rd, vec3 s) {
  vec3 xo = -ro / rd;
  vec3 xs = abs(s / rd);

  vec3 dfv = xo - xs;
  vec3 dbv = xo + xs;

  float df = max(max(dfv.x, dfv.y), dfv.z);
  float db = min(min(dbv.x, dbv.y), dbv.z);
  if (df < 0.0 || db < df) { return vec4(FAR); }

  vec3 n = -sign(rd) * step(vec3(df), dfv);
  return vec4(n, df);
}

vec4 isectSphere(vec3 ro, vec3 rd, float r) {
  float b = dot(ro, rd);
  float c = dot(ro, ro) - r * r;
  float h = b * b - c;

  float rl = -b - sqrt(h);
  if (h < 0.0 || rl < 0.0) { return vec4(FAR); }

  return vec4(normalize(ro + rd * rl), rl);
}

// == main =========================================================================================
void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
  fragColor *= 0.0;

  vec2 uv = fragCoord.xy / iResolution.xy;
  vec2 p = uv - 0.5;
  p.x *= iResolution.x / iResolution.y;

  vec3 seed = hash3f(vec3(p, iTime));
  float time = iTime;
  float beat = time * 135.0 / 60.0;

  for (int i = 0; i ++ < SAMPLES_PER_FRAME;) {
    vec3 colRem = mix(
      vec3(-0.0001, 0.0001, 1.0),
      vec3(-0.4, 0.1, 1.0),
      smoothstep(31.5, 32.5, beat) * smoothstep(224.5, 223.5, beat)
    );

    vec3 ro = orthBas(colRem) * vec3(1.5 * (p + (seed = hash3f(seed)).xy / iResolution.y) + vec2(0, 0.1 * time), 6.0) - vec3(0.0, 0.0, 2.0);
    vec3 rd = orthBas(colRem) * vec3(0.0, 0.0, -1.0);

    colRem /= colRem;

    for (int i = 0; i ++ < TRAVERSAL_STEPS;) {
      mat3 material = mat3(
        vec3(0.0),
        vec3(0.0),
        vec3(0.0, 1.0, 0.0)
      );

      vec4 isect = isectBox(ro + vec3(0.0, 0.0, 5.0), rd, vec3(1E3, 1E3, 0.01));
      vec4 isect2;

      {
        // quadtree subdivision
        ro += rd * 0.001;

        const float QUADTREE_SIZE = 0.5;
        const float QUADTREE_DEPTH = 6.0;

        float gen;
        vec3 cell = vec3(0.0, 0.0, 0.5 * FAR);
        vec3 cellSize = vec3(FAR);
        vec3 cellDice = vec3(1e9);

        if (ro.z < 0.0) {
          cellSize = vec3(QUADTREE_SIZE, QUADTREE_SIZE, QUADTREE_DEPTH);
          for (int i = 0; i ++ < 5; ) {
            cellSize.xy *= 0.5 + 0.5 * step(gen < 96.0 ? 0.3 : gen < 160.0 ? 0.4 : gen < 256.0 ? 0.5 : 0.3, cellDice.xy);
            cellSize.z = QUADTREE_DEPTH;

            cell = (floor(ro / cellSize) + 0.5) * cellSize;
            cell.z = 0.0;

            gen = floor(
              dot(cell + cellSize / 2.0 - vec3(0.0, 0.1 * time, 0.0), vec3(-0.03, 0.3, 0.0)) + beat
            );
            cellDice = hash3f(cell + clamp(gen, 31.0, 288.0));
          }
        }

        ro -= rd * 0.001;

        {
          // quadtree traversal
          vec3 i_src = -( ro - cell ) / rd;
          vec3 i_dst = abs( 0.5 * cellSize / rd );
          vec3 bvOrRot = i_src + i_dst;
          float distToNextCell = min(min(bvOrRot.x, bvOrRot.y), bvOrRot.z);

          vec3 rand = vec3(0.0);

          // scene
          bvOrRot = ro - cell + vec3(0.0, 0.0, 5.5 + cellDice.y);

          cellDice = hash3f(cellDice);

          isect2 = isectBox(
            bvOrRot,
            rd,
            vec3(0.5 * cellSize.xy - 0.004, 4.0)
          );

          if (cell.z != 0.0) {
            // skip

          } else if (cellSize.x == cellSize.y && cellSize.x < 1.0 && cellDice.x < 0.1) { // sphere
            if (isect2.w < isect.w) {
              isect = isect2;

              material = mat3(
                vec3(0.04),
                vec3(0.0),
                vec3(0.1, 0.0, 0.0)
              );
            }

            vec3 rotSphere = bvOrRot - vec3(0.0, 0.0, 4.0 + 0.5 * cellSize);
            isect2 = isectSphere(
              rotSphere,
              rd,
              0.4 * min(cellSize.x, cellSize.y)
            );

            if (isect2.w < isect.w) {
              isect = isect2;

              vec3 i_noise = cyclicNoise(4.0 * (ro + rd * isect.w + cellDice), 0.5);
              // vec3 coord = ((rotSphere + rd * isect.w) * orthBas(vec3(cis(time + TAU * cellDice.z), 3.0))) / cellSize.x;
              // material = mat3(
              //   mix(
              //     vec3(0.8, 0.6, 0.02),
              //     vec3(0.02),
              //     step(0.0, coord.z) * (
              //       step(length(abs(coord.xy * vec2(2.0, 1.0) - vec2(0.0, 0.15)) - vec2(0.2, 0.0)), 0.1)
              //       + step(abs(length(coord.xy) - 0.24), step(1.9, abs(atan(coord.x, coord.y))) * 0.01 + step(abs(abs(atan(coord.x, coord.y)) - 1.9), 0.05) * 0.02)
              //     )
              //   ),
              //   vec3(0.0),
              //   vec3(0.1, 0.0, 0.0)
              // );

              material = mat3(
                vec3(0.63, 0.65, 0.66),
                vec3(0.0),
                vec3(0.1, 1.0, 0.0)
              );
            }
          } else if (cellSize.x == cellSize.y && cellSize.x < 1.0 && cellDice.x < (gen > 63.0 ? 0.8 : 0.3)) { // holo
            if (isect2.w < isect.w) {
              isect = isect2;

              material = mat3(
                vec3(0.4),
                vec3(0.0),
                vec3(0.04, 1.0, 0.0)
              );
            }

            vec3 rotPlane = bvOrRot - vec3(0.0, 0.0, 4.02);
            isect2 = isectBox(
              rotPlane,
              rd,
              vec3(cellSize.xy, 0.001)
            );
            if (isect2.w < isect.w) {
              vec3 coord = (bvOrRot + rd * isect2.w);
              vec2 ncoord = ((coord / (0.5 * cellSize - 0.004)).xy);

              float mask = step(max(abs(ncoord.x), abs(ncoord.y)), 0.9) * (
                cellDice.y < 0.2 ? step(length(ncoord), 0.9) * step(0.5, length(ncoord)) :
                cellDice.y < 0.4 ? max(step(abs(ncoord.x + ncoord.y), 0.3), step(abs(ncoord.x - ncoord.y), 0.3)) :
                cellDice.y < 0.5 ? max(step(abs(ncoord.y), 0.2), step(abs(ncoord.x), 0.2)) :
                cellDice.y < 0.6 ? max(step(abs(ncoord.y), 0.22) * step(ncoord.x, 0.3), step(abs(abs(ncoord.y) + ncoord.x - 0.6), 0.3) * step(abs(ncoord.y), 0.8)) :
                cellDice.y < 0.7 ? step(abs(abs(ncoord.y) - 0.4), 0.2) :
                cellDice.y < 0.8 ? step(hash3f(floor(ncoord.xyy / 0.45) + cellDice).x, 0.5) * step(length(fract(ncoord / 0.45) - 0.5), 0.4) :
                cellDice.y < 0.9 ? step(max(abs(ncoord.x), abs(ncoord.y)), 0.9) * step(0.6, max(abs(ncoord.x), abs(ncoord.y))) :
                max(step(max(abs(ncoord.x), abs(ncoord.y)), 0.1), step(min(abs(ncoord.x), abs(ncoord.y)), 0.3) * step(0.3, max(abs(ncoord.x), abs(ncoord.y))) * step(max(abs(ncoord.x), abs(ncoord.y)), 0.5))
              );

              if (mask > 0.0) {
                isect = isect2;

                material = mat3(
                  vec3(0.0),
                  (0.54 - 0.5 * cos(9.0 * PI * max(smoothstep(128.5, 127.5, beat), smoothstep(159.5, 160.5, beat)))) * vec3(1.0, 2.0, 3.0) * (1.0 + 0.5 * sin(120.0 * (coord.y + time))),
                  vec3(0.0, 1.0, 0.0)
                );
              }
            }

          } else if (cellSize.x * cellSize.y < 0.125 && cellDice.x < 0.5 * pow(smoothstep(128.0, 160.0, gen), 2.0) * step(gen, 255.0)) { // grafix
            isect2 = isectBox(
              bvOrRot,
              rd,
              vec3(0.5 * cellSize.xy - 0.004, 3.5 + smoothstep(159.5, 160.5, beat))
            );

            if (isect2.w < isect.w) {
              isect = isect2;

              vec3 coord = (bvOrRot + rd * isect.w);
              vec3 i_gridcoord = (coord - vec3(0.0, 0.0, 4.5)) / (cellSize - 0.008) * cellSize;
              vec2 uv = 0.5 + ((coord / (cellSize - 0.008)).xy);
              vec3 grafix =
                cellDice.y < 0.05 ? vec3(1.0) :
                cellDice.y < 0.2 ? max(sin(80.0 * cyclicNoise(5.0 * coord + 8.0 * cellDice, 0.5).x + 20.0 * time + vec3(0.0, 1.0, 2.0)), 0.0) :
                cellDice.y < 0.4 ? saturate(abs(mod(6.0 * (uv.y + time + cellDice.z) + vec3(0, 4, 2), 6.0) - 3.0) - 1.0) :
                cellDice.y < 0.6 ? vec3(dot(1.0 - abs(isect.xyz), 1.0 - step(0.05, abs(fract(64.0 * i_gridcoord + 0.5) - 0.5)))) :
                cellDice.y < 0.8 ? step(0.5, vec3(fract(20.0 * (abs(coord.x) + abs(coord.y) + abs(coord.z) + cellDice.z) - 3.0 * time))) :
                cellDice.y < 0.95 ? vec3(step(hash3f(floor(coord * 256.0) + floor(beat * 4.0) + cellDice).x, 0.4)) :
                vec3(0.02, 0.02, 1.0);

              material = mat3(
                vec3(0.0),
                grafix,
                vec3(0.04, 0.0, 0.0)
              );
            }

          } else {
            if (isect2.w < isect.w) {
              isect = isect2;

              material = mat3(
                vec3(0.8, 0.82, 0.85),
                vec3(0.0),
                vec3(0.2, step(0.5, cellDice.y), 0.0)
              );
            }
          }

          rand += 1.0 + step(0.5, cellDice);

          // should we skip the cell?
          if (distToNextCell < isect.w) {
            ro += distToNextCell * rd;
            continue;
          }
        }
      }

      if (isect.w > FAR - 1.0) {
        break;
      }

      vec3 i_baseColor = material[0];
      vec3 i_emissive = material[1];
      float i_roughness = material[2].x;
      float i_metallic = material[2].y;

      fragColor.xyz += colRem * i_emissive;

      // if hit then
      ro += isect.w * rd + isect.xyz * 0.001;
      float sqRoughness = i_roughness * i_roughness;
      float sqSqRoughness = sqRoughness * sqRoughness;
      float halfSqRoughness = 0.5 * sqRoughness;

      {
        float NdotV = dot( isect.xyz, -rd );
        float Fn = mix( 0.04, 1.0, pow( 1.0 - NdotV, 5.0 ) );
        float spec = max(
          step((seed = hash3f(seed)).x, Fn), // non metallic, fresnel
          i_metallic // metallic
        );

        // sample ggx or lambert
        seed.y = sqrt( ( 1.0 - seed.y ) / ( 1.0 - spec * ( 1.0 - sqSqRoughness ) * seed.y ) );
        vec3 woOrH = orthBas( isect.xyz ) * vec3(
          sqrt( 1.0 - seed.y * seed.y ) * sin( TAU * seed.z + vec2( 0.0, TAU / 4.0 ) ),
          seed.y
        );

        if (spec > 0.0) {
          // specular
          // note: woOrH is H right now
          vec3 i_H = woOrH;
          vec3 i_wo = reflect(rd, i_H);
          if (dot(i_wo, isect.xyz) < 0.0) {
            break;
          }

          // vector math
          float NdotL = dot( isect.xyz, i_wo );
          float i_VdotH = dot( -rd, i_H );
          float i_NdotH = dot( isect.xyz, i_H );

          // fresnel
          vec3 i_F0 = mix(vec3(0.04), i_baseColor, i_metallic);
          vec3 i_Fh = mix(i_F0, vec3(1.0), pow(1.0 - i_VdotH, 5.0));

          // brdf
          // colRem *= Fh / Fn * G * VdotH / ( NdotH * NdotV );
          colRem *= max(
            i_Fh / mix(Fn, 1.0, i_metallic)
              / ( NdotV * ( 1.0 - halfSqRoughness ) + halfSqRoughness ) // G1V / NdotV
              * NdotL / ( NdotL * ( 1.0 - halfSqRoughness ) + halfSqRoughness ) // G1L
              * i_VdotH / i_NdotH,
            0.0
          );

          // wo is finally wo
          woOrH = i_wo;
        } else {
          // diffuse
          // note: woOrH is wo right now
          if (dot(woOrH, isect.xyz) < 0.0) {
            break;
          }

          // calc H
          // vector math
          vec3 i_H = normalize( -rd + woOrH );
          float i_VdotH = dot( -rd, i_H );

          // fresnel
          float i_Fh = mix(0.04, 1.0, pow(1.0 - i_VdotH, 5.0));

          // brdf
          colRem *= (1.0 - i_Fh) / (1.0 - Fn) * i_baseColor;
        }

        // prepare the rd for the next ray
        rd = woOrH;

        // if the ray goes beind the surface, invalidate it
        colRem *= max(step(0.0, dot(woOrH, isect.xyz)), 0.0);
      }

      if (dot(colRem, colRem) < 0.01) {
        break;
      }
    }

    fragColor.xyz += vec3(1.0, 2.0, 3.0) * step(0.0, saturate(rd.z)) * colRem * step(mod(beat - 1.25 + 0.5 * rd.y, 4.0), 0.1) * smoothstep(16.0, 32.0, beat);
  }

  fragColor = mix(
    max(sqrt(fragColor / float(SAMPLES_PER_FRAME)), 0.0),
    max(texture(iChannel0, uv), 0.0),
    0.5
  ) * smoothstep(0.0, 16.0, beat) * smoothstep(320.0, 288.0, beat);
}  Image: void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    fragColor = texture( iChannel0, fragCoord / iResolution.xy );
}  Sound: // This work is licensed under a Creative Commons Attribution-NonCommercial 4.0 International License.
// https://creativecommons.org/licenses/by-nc/4.0/

#define saturate(i) clamp(i,0.,1.)
#define linearstep(a,b,x) saturate(((x)-(a))/((b)-(a)))
#define p2f(i) (exp2(((i)-69.)/12.)*440.)
#define repeat(i, n) for(int i=0; i<(n); i++)
#define inRange(t,a,b) (step(a,t)*(1.-step(b,t)))
#define inRangeB(t,a,b) ((a<=t)&&(t<b))

const float PI = acos( -1.0 );
const float TAU = PI * 2.0;
const float GOLD = PI * (3.0 - sqrt(5.0));// 2.39996...

const float BPS = 2.25;
const float B2T = 1.0 / BPS;
const float S2T = 0.25 * B2T;
const float SWING = 1.15;

uvec3 hash3u(uvec3 v) {
  v = v * 1664525u + 1013904223u;

  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;

  v ^= v >> 16u;

  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;

  return v;
}
vec3 hash3f(vec3 v) {
  uvec3 u = hash3u(floatBitsToUint(v));
  return vec3(u) / float(-1u);
}

vec2 cis(float t) {
  return vec2(cos(t), sin(t));
}

mat2 rotate2D( float x ) {
  vec2 v = cis(x);
  return mat2(v.x, v.y, -v.y, v.x);
}

mat3 orthBas(vec3 z) {
  z = normalize(z);
  vec3 x = normalize(cross(vec3(0, 1, 0), z));
  vec3 y = cross(z, x);
  return mat3(x, y, z);
}

vec3 cyclicNoise(vec3 p, float pers) {
  vec4 sum = vec4(0.0);

  for (int i = 0; i ++ < 4;) {
    p *= orthBas(vec3(-1.0, 2.0, -3.0));
    p += sin(p.yzx);
    sum = (sum + vec4(cross(sin(p.zxy), cos(p)), 1.0)) / pers;
    p *= 2.0;
  }

  return sum.xyz / sum.w;
}


vec2 shotgun( float t, float spread ) {
  vec2 sum = vec2( 0.0 );

  for ( int i = 0; i < 64; i ++ ) {
    vec3 dice = hash3f( vec3( i ) );
    sum += vec2( sin( TAU * t * exp2( spread * dice.x ) ) ) * rotate2D( TAU * dice.y );
  }

  return sum / 64.0;
}

vec2 cheapnoise(float t) {
  uvec3 s=uvec3(t * 256.0);
  float p=fract(t * 256.0);

  vec3 dice;
  vec2 v = vec2(0.0);

  dice=vec3(hash3u(s + 0u)) / float(-1u) - vec3(0.5, 0.5, 0.0);
  v += dice.xy * smoothstep(1.0, 0.0, abs(p + dice.z));
  dice=vec3(hash3u(s + 1u)) / float(-1u) - vec3(0.5, 0.5, 1.0);
  v += dice.xy * smoothstep(1.0, 0.0, abs(p + dice.z));
  dice=vec3(hash3u(s + 2u)) / float(-1u) - vec3(0.5, 0.5, 2.0);
  v += dice.xy * smoothstep(1.0, 0.0, abs(p + dice.z));

  return 2.0 * v;
}

vec2 ladderLPF(float freq, float cutoff, float reso) {
  float omega = freq / cutoff;
  float omegaSq = omega * omega;

  float a = 4.0 * reso + omegaSq * omegaSq - 6.0 * omegaSq + 1.0;
  float b = 4.0 * omega * (omegaSq - 1.0);

  return vec2(
    1.0 / sqrt(a * a + b * b),
    atan(a, b)
  );
}

vec2 twoPoleHPF(float freq, float cutoff, float reso) {
  float omega = freq / cutoff;
  float omegaSq = omega * omega;

  float a = 2.0 * (1.0 - reso) * omega;
  float b = omegaSq - 1.0;

  return vec2(
    omegaSq / sqrt(a * a + b * b),
    atan(a, b)
  );
}

vec4 quant(float x, float ks, float kt, out float i) {
  i = floor(floor(x / ks + 1E-4) * ks / kt + 1E-4);

  float s = kt <= ks
    ? ks * floor(x / ks + 1E-4)
    : ks * ceil(i * kt / ks - 1E-4);
  float l = kt <= ks
    ? ks
    : ks * ceil((i + 1.0) * kt / ks - 1E-4) - s;

  float t = x - s;
  float q = l - t;

  return vec4(s, t, s + l, q);
}

vec4 quant(float x, float ks, float kt) {
  float i;
  return quant(x, ks, kt, i);
}

float swing(float x, float k) {
  float xm = mod(x, 2.0);
  return x + (1.0 - k) * linearstep(0.0, k, xm) * linearstep(2.0, k, xm);
}

float unswing(float x0, float x, float y, float k) {
  return (
    x0
    - 2.0 * floor((x - y) / 2.0)
    - k * linearstep(0.0, 1.0, mod(x - y, 2.0))
    - (2.0 - k) * linearstep(1.0, 2.0, mod(x - y, 2.0))
  );
}

float cheapFilterSaw( float phase, float k ) {
  float i_wave = fract( phase );
  float i_c = smoothstep( 1.0, 0.0, i_wave / k );
  return ( i_wave + i_c ) * 2.0 - 1.0 - k;
}

float CHORDS[] = float[](
  0.0, 2.0, 3.0, 7.0, 14.0, 15.0, 19.0, 22.0,
  -5.0, 2.0, 3.0, 5.0, 7.0, 10.0, 14.0, 15.0,
  -4.0, 0.0, 3.0, 7.0, 14.0, 15.0, 19.0, 24.0,
  -7.0, 0.0, 7.0, 8.0, 10.0, 12.0, 15.0, 19.0
);

vec2 mainSound( int samp, float _time ) {
  int SAMPLES_PER_STEP = int( iSampleRate / BPS / 4.0 );
  int SAMPLES_PER_BEAT = 4 * SAMPLES_PER_STEP;


  vec4 time = vec4(samp % (SAMPLES_PER_BEAT * ivec4(1, 4, 64, 65536))) / iSampleRate;
  vec4 beats = time * BPS;

  // return float( max( 0, frame + SAMPLES_PER_STEP * offset ) % ( SAMPLES_PER_STEP * every ) ) / SAMPLES_PER_SEC;

  vec2 dest = vec2(0);
  float sidechain;

  { // kick
    float t = time.x;
    float q = B2T - t;
    sidechain = 0.2 + 0.8 * smoothstep(0.0, 0.4, t) * smoothstep(0.0, 0.001, q);

    float env = smoothstep(0.0, 0.001, q) * smoothstep(2.0 * B2T, 0.1 * B2T, t);

    if (128.0 < beats.w && beats.w < 160.0) {
      env *= exp(-70.0 * t);
    }

    if (32.0 < beats.w && beats.w < 287.9) {
      float wave = sin(
        270.0 * t
        - 40.0 * exp(-t * 20.0)
        - 20.0 * exp(-t * 60.0)
        - 10.0 * exp(-t * 300.0)
        - 0.4 * sin(120.0 * t)
      );
      dest += 0.6 * tanh(2.0 * env * wave);
    }
  }

  if (64.0 - 0.75 < beats.w && beats.w < 256.0) { // hihat
    float t = mod(time.x, S2T);
    float st = mod(floor(time.y / S2T), 16.0);

    float vel = fract(st * 0.2 + 0.42);
    float env = exp(-exp2(7.0 - 3.0 * vel) * t);
    vec2 wave = shotgun(6000.0 * t, 2.0);
    dest += 0.2 * env * sidechain * tanh(8.0 * wave);
  }

  if (96.0 < beats.w && beats.w < 290.0) { // clap
    float t = mod(time.y + S2T, 4.0 * B2T);

    float env = mix(
      exp(-26.0 * t),
      exp(-200.0 * mod(t, 0.013)),
      exp(-80.0 * max(0.0, t - 0.02))
    );

    vec2 wave = cyclicNoise(vec3(4.0 * cis(800.0 * t), 1940.0 * t), 1.5).xy;

    dest += 0.1 * tanh(20.0 * env * wave);
  }

  if (32.0 < beats.w && beats.w < 256.0) { // shaker
    float t = mod(time.x, S2T);
    float st = mod(floor(time.y / S2T), 16.0);

    float vel = fract(st * 0.41 + 0.63);
    float env = smoothstep(0.0, 0.02, t) * exp(-exp2(6.0 - 3.0 * vel) * t);
    vec2 wave = cyclicNoise(vec3(cis(2800.0 * t), exp2(8.0 + 3.0 * vel) * t), 0.8).xy;
    dest += 0.15 * env * sidechain * tanh(2.0 * wave);
  }

  { // perc 1
    float t = mod(time.z - S2T, 6.0 * S2T);

    float env = mix(
      exp(-t),
      exp(-30.0 * t),
      0.95
    );
    vec2 wave = sin(7100.0 * t + vec2(0, PI / 2.0) + 10.0 * cheapnoise(t));
    dest += 0.3 * env * tanh(wave) * smoothstep(128.0, 160.0, beats.w);
  }

  { // perc 2
    float t = mod(time.z - 3.0 * S2T, 6.0 * S2T);

    float env = mix(
      exp(-t),
      exp(-30.0 * t),
      0.95
    );
    vec2 wave = 2.0 * fract(1200.0 * t + sin(1000.0 * t) + vec2(0.0, 0.25)) - 1.0;
    dest += 0.3 * env * tanh(wave) * smoothstep(128.0, 160.0, beats.w);
  }

  { // beep
    float t = mod(time.y - 5.0 * S2T, 16.0 * S2T);

    float env = smoothstep(0.0, 0.001, t) * mix(
      exp(-2.0 * t),
      smoothstep(0.0, 0.001, 0.07 - t),
      0.98
    );
    vec2 wave = sin(50000.0 * t + vec2(PI / 2.0, 0));
    dest += 0.2 * env * wave * smoothstep(16.0, 32.0, beats.w);
  }

  if (96.0 < beats.w) { // crash
    float t = mod(time.z - 32.0 * B2T, 64.0 * B2T);

    float env = mix(exp(-t), exp(-10.0 * t), 0.7);
    vec2 wave = shotgun(3800.0 * t, 2.0);
    dest += 0.3 * env * sidechain * tanh(8.0 * wave);
  }

  if (160.0 < beats.w && beats.w < 224.0) { // ride
    float t = mod(time.x, 2.0 * S2T);
    float q = 2.0 * S2T - t;

    float env = exp(-5.0 * t);

    vec2 sum = vec2(0.0);

    repeat(i, 8) {
      vec3 dice = hash3f(vec3(i));
      vec3 dice2 = hash3f(dice);

      vec2 wave = vec2(0.0);
      wave = 4.5 * env * sin(wave + exp2(12.10 + 0.1 * dice.x) * t + dice2.xy);
      wave = 2.2 * env * sin(wave + exp2(14.67 + 0.5 * dice.y) * t + dice2.yz);
      wave = 1.0 * env * sin(wave + exp2(13.89 + 1.0 * dice.z) * t + dice2.zx);

      sum += wave;
    }

    dest += 0.08 * env * sidechain * tanh(sum);
  }

  { // additive riff
    vec2 sum = vec2(0.0);

    float t = mod(time.x, S2T);
    float q = S2T - t;
    float st = floor(time.z / S2T);
    float env = smoothstep(0.0, 0.01, t) * smoothstep(0.0, 0.01, q);

    float basefreq = 80.0;
    float stmod = fract(0.615 * st);

    float cutenv = smoothstep(0.0, 0.01, t) * exp(-14.0 * t);
    float cutoff = exp2(
      5.0
      - 2.0 * smoothstep(32.0, 16.0, beats.w)
      + 2.5 * smoothstep(128.0, 160.0, beats.w)
      - step(256.0, beats.w)
      - 2.0 * smoothstep(288.0, 320.0, beats.w)
      + 3.0 * stmod
      + 4.0 * cutenv
    );

    repeat(i, 128) {
      float fi = float(i);

      float p = 1.0 + fi;
      p = pow(p, 1.1); // metal
      p = mix(p, 1.0, 0.1); // centroid
      float freq = basefreq * p;

      vec2 phase = vec2(t * freq);
      vec2 lpf = ladderLPF(freq, cutoff, 0.3);
      vec2 hpf = twoPoleHPF(freq, 200.0, 0.0);

      sum += sin(TAU * phase + lpf.y + hpf.y) / p * lpf.x * hpf.x * env * rotate2D(2.4 * fi);
    }

    dest += 0.2 * mix(0.2, 1.0, sidechain) * tanh(5.0 * sum) * smoothstep(8.0, 32.0, beats.w);
  }

  if (beats.w < 224.0) { // oidos drone
    vec2 sum=vec2(0.0);

    repeat(i, 2500) {
      vec3 diceA = hash3f(vec3(i / 50));
      vec3 diceB = hash3f(vec3(i));

      float t = mod(time.z - diceA.x * (64.0 * B2T), 64.0 * B2T);
      float env = sin(PI * t / (64.0 * B2T));

      float tone = 8.0 + 9.0 * diceA.y + 0.06 * diceB.y;
      float freq = exp2(tone);
      vec2 phase = t * freq + fract(diceB.xy * 999.0);
      phase += 0.1 * fract(32.0 * phase); // add high freq

      sum += sin(TAU * phase) * env / 1000.0;
    }

    dest += 1.0 * mix(0.2, 1.0, sidechain) * sum * smoothstep(0.0, 32.0, beats.w);
  }

  return clamp(dest, -1.0, 1.0) * smoothstep(320.0, 288.0, beats.w);
}



*Grep searched codebase*

*Edited relevant file*

*Edited relevant file*

### User Input

/*

	Bumped Sinusoidal Warp
	----------------------

	Sinusoidal planar deformation, or the 2D sine warp effect to people 
	like me. The effect has been around for years, and there are
	countless examples on the net. IQ's "Sculpture III" is basically a 
	much more sophisticated, spherical variation.

    This particular version was modified from Fabrice's "Plop 2," which in 
	turn was a simplified version of Fantomas's "Plop." I simply reduced 
	the frequency and iteration count in order to make it less busy.

	I also threw in a texture, added point-lit bump mapping, speckles... 
	and that's pretty much it. As for why a metallic surface would be 
	defying	the laws of physics and moving like this is anyone's guess. :)

	By the way, I have a 3D version, similar to this, that I'll put up at 
	a later date.
    


	Related examples:

    Fantomas - Plop
    https://www.shadertoy.com/view/ltSSDV

    Fabrice - Plop 2
    https://www.shadertoy.com/view/MlSSDV

	IQ - Sculpture III (loosely related)
	https://www.shadertoy.com/view/XtjSDK

	Shane - Lit Sine Warp (far less code)
	https://www.shadertoy.com/view/Ml2XDV

*/


// Warp function. Variations have been around for years. This is
// almost the same as Fabrice's version:
// Fabrice - Plop 2
// https://www.shadertoy.com/view/MlSSDV
vec2 W(vec2 p){
    
    p = (p + 3.)*4.;

    float t = iTime/2.;

    // Layered, sinusoidal feedback, with time component.
    for (int i=0; i<3; i++){
        p += cos(p.yx*3. + vec2(t, 1.57))/3.;
        p += sin(p.yx + t + vec2(1.57, 0))/2.;
        p *= 1.3;
    }

    // A bit of jitter to counter the high frequency sections.
    p += fract(sin(p+vec2(13, 7))*5e5)*.03 - .015;

    return mod(p, 2.) - 1.; // Range: [vec2(-1), vec2(1)]
    
}

// Bump mapping function. Put whatever you want here. In this case, 
// we're returning the length of the sinusoidal warp function.
float bumpFunc(vec2 p){ 

	return length(W(p))*.7071; // Range: [0, 1]

}

/*
// Standard ray-plane intersection.
vec3 rayPlane(vec3 p, vec3 o, vec3 n, vec3 rd) {
    
    float dn = dot(rd, n);

    float s = 1e8;
    
    if (abs(dn) > 0.0001) {
        s = dot(p-o, n) / dn;
        s += float(s < 0.0) * 1e8;
    }
    
    return o + s*rd;
}
*/

vec3 smoothFract(vec3 x){ x = fract(x); return min(x, x*(1.-x)*12.); }

void mainImage( out vec4 fragColor, in vec2 fragCoord ){

    // Screen coordinates.
	vec2 uv = (fragCoord - iResolution.xy*.5)/iResolution.y;
    
    
    // PLANE ROTATION
    //
    // Rotating the canvas back and forth. I don't feel it adds value, in this case,
    // but feel free to uncomment it.
    //float th = sin(iTime*0.1)*sin(iTime*0.12)*2.;
    //float cs = cos(th), si = sin(th);
    //uv *= mat2(cs, -si, si, cs);
  

    // VECTOR SETUP - surface postion, ray origin, unit direction vector, and light postion.
    //
    // Setup: I find 2D bump mapping more intuitive to pretend I'm raytracing, then lighting a 
    // bump mapped plane situated at the origin. Others may disagree. :)  
    vec3 sp = vec3(uv, 0); // Surface posion, or hit point. Essentially, a screen at the origin.
    vec3 rd = normalize(vec3(uv, 1)); // Unit direction vector. From the origin to the screen plane.
    vec3 lp = vec3(cos(iTime)*.5, sin(iTime)*.2, -1); // Light position - Back from the screen.
	vec3 sn = vec3(0, 0, -1); // Plane normal. Z pointing toward the viewer.
 
     
/*
	// I deliberately left this block in to show that the above is a simplified version
	// of a raytraced plane. The "rayPlane" equation is commented out above.
	vec3 rd = normalize(vec3(uv, 1));
	vec3 ro = vec3(0, 0, -1);

	// Plane normal.
	vec3 sn = normalize(vec3(cos(iTime)*.25, sin(iTime)*.25, -1));
    //vec3 sn = normalize(vec3(0, 0, -1));
	
	vec3 sp = rayPlane(vec3(0), ro, sn, rd);
    vec3 lp = vec3(cos(iTime)*.5, sin(iTime)*.25, -1); 
*/    
    
    
    // BUMP MAPPING - PERTURBING THE NORMAL
    //
    // Setting up the bump mapping variables. Normally, you'd amalgamate a lot of the following,
    // and roll it into a single function, but I wanted to show the workings.
    //
    // f - Function value
    // fx - Change in "f" in in the X-direction.
    // fy - Change in "f" in in the Y-direction.
    vec2 eps = vec2(4./iResolution.y, 0);
    
    float f = bumpFunc(sp.xy); // Sample value multiplied by the amplitude.
    float fx = bumpFunc(sp.xy - eps.xy); // Same for the nearby sample in the X-direction.
    float fy = bumpFunc(sp.xy - eps.yx); // Same for the nearby sample in the Y-direction.
   
 	// Controls how much the bump is accentuated.
	const float bumpFactor = .05;
    
    // Using the above to determine the dx and dy function gradients.
    fx = (fx - f)/eps.x; // Change in X
    fy = (fy - f)/eps.x; // Change in Y.
    // Using the gradient vector, "vec3(fx, fy, 0)," to perturb the XY plane normal ",vec3(0, 0, -1)."
    // By the way, there's a redundant step I'm skipping in this particular case, on account of the 
    // normal only having a Z-component. Normally, though, you'd need the commented stuff below.
    //vec3 grad = vec3(fx, fy, 0);
    //grad -= sn*dot(sn, grad);
    //sn = normalize(sn + grad*bumpFactor ); 
    sn = normalize(sn + vec3(fx, fy, 0)*bumpFactor);   
    // Equivalent to the following.
    //sn = cross(-vec3(1, 0, fx*bumpFactor), vec3(0, 1, fy*bumpFactor));
    //sn = normalize(sn);
   
    
    // LIGHTING
    //
	// Determine the light direction vector, calculate its distance, then normalize it.
	vec3 ld = lp - sp;
	float lDist = max(length(ld), .0001);
	ld /= lDist;

    // Light attenuation.    
    float atten = 1./(1. + lDist*lDist*.15);
	//float atten = min(1./(lDist*lDist*1.), 1.);
    
    // Using the bump function, "f," to darken the crevices. Completely optional, but I
    // find it gives extra depth.
    atten *= f*.9 + .1; // Or... f*f*.7 + .3; //  pow(f, .75); // etc.

	

	// Diffuse value.
	float diff = max(dot(sn, ld), 0.);  
    // Enhancing the diffuse value a bit. Made up.
    diff = pow(diff, 4.)*.66 + pow(diff, 8.)*.34; 
    // Specular highlighting.
    float spec = pow(max(dot( reflect(-ld, sn), -rd), 0.), 12.); 
    //float spec = pow(max(dot(normalize(ld - rd), sn), 0.), 32.);
    
	
    // TEXTURE COLOR
    //
	// Combining the surface postion with a fraction of the warped surface position to index 
    // into the texture. The result is a slightly warped texture, as a opposed to a completely 
    // warped one. By the way, the warp function is called above in the "bumpFunc" function,
    // so it's kind of wasteful doing it again here, but the function is kind of cheap, and
    // it's more readable this way.
    vec3 texCol = texture(iChannel0, sp.xy + W(sp.xy)/8.).xyz; 
    texCol *= texCol; // Rough sRGB to linear conversion... That's a whole other conversation. :)
    // A bit of color processing.
    texCol = smoothstep(.05, .75, pow(texCol, vec3(.75, .8, .85)));    
    
    // Textureless. Simple and elegant... so it clearly didn't come from me. Thanks Fabrice. :)
    //vec3 texCol = smoothFract( W(sp.xy).xyy )*.1 + .2;
    
	
    
    // FINAL COLOR
    // Using the values above to produce the final color.   
    vec3 col = (texCol*(diff*vec3(1, .97, .92)*2. + .5) + vec3(1, .6, .2)*spec*2.)*atten;
    
    // Faux environment mapping: I added this in at a later date out of sheer boredome, and  
    // because I like shiny stuff. You can comment it out if it's not to your liking. :)
    float ref = max(dot(reflect(rd, sn), vec3(1)), 0.);
    col += col*pow(ref, 4.)*vec3(.25, .5, 1)*3.;
    

    // Perform some statistically unlikely (but close enough) 2.0 gamma correction. :) 
	fragColor = vec4(sqrt(clamp(col, 0., 1.)), 1);
}

*Listed directory [cedartoy](file:///d:/cedartoy) *

*Listed directory [assets](file:///d:/cedartoy/cedartoy/assets) *

*Edited relevant file*

*Edited relevant file*

*Edited relevant file*

### User Input

// Shader by Frostbyte
// Licensed under CC BY-NC-SA 4.0

/*
Only 10 Raymarch Steps! Other looks can be found with as few as 5 steps.
This shader was influenced by Xor's Surf 2, but created using a different technique.
Xor's Surf 2: https://www.shadertoy.com/view/3fKSzc
Methods were drawn from my Abstract Series: https://www.shadertoy.com/playlist/D3VBDt
In this series, I aimed for creativity with low raymarch count volumetrics.
Many looks can be found with a few adjustments but the low ray march count makes it tricky and interesting.
One of the challenges is creating depth with the lower raymarch count. 
Accumulated glow/HDR is reduced. Less steps are taken along z and the distance along z is reduced.
Ways I added percieved depth here is through movement, turbulence, 
color contrast of background, some volumetric glow, and color variation along length(p.xy).

Notes: 
Aces tonemap > Tanh for higher contrast look in this scene.
Dot noise - volume that we are moving through.
Clear Tunnel for "Camera": 2.-length(p.xy)
Turbulent Effect: s+=abs(sin(p.z)); - Movement along z creates turbulent effect
Color like "Luminence": 1.+sin(i))/s; - s gives glow and sin(i) gives iterative color for each raymarch 
Volumetrics: p+=d*s; Accumulate along each step of d
*/

//2d rotation matrix
vec2 r(vec2 v,float t){float s=sin(t),c=cos(t);return mat2(c,-s,s,c)*v;}

// ACES tonemap: https://www.shadertoy.com/view/Xc3yzM
vec3 a(vec3 c)
{
mat3 m1=mat3(0.59719,0.07600,0.02840,0.35458,0.90834,0.13383,0.04823,0.01566,0.83777);
mat3 m2=mat3(1.60475,-0.10208,-0.00327,-0.53108,1.10813,-0.07276,-0.07367,-0.00605,1.07602);
vec3 v=m1*c,a=v*(v+0.0245786)-0.000090537,b=v*(0.983729*v+0.4329510)+0.238081;
return m2*(a/b);
}

//Xor's Dot Noise: https://www.shadertoy.com/view/wfsyRX
float n(vec3 p)
{
    const float PHI = 1.618033988;
    const mat3 GOLD = mat3(
    -0.571464913, +0.814921382, +0.096597072,
    -0.278044873, -0.303026659, +0.911518454,
    +0.772087367, +0.494042493, +0.399753815);
    return dot(cos(GOLD * p), sin(PHI * p * GOLD));
}

void mainImage(out vec4 o,in vec2 u){
    float i,s,t=iTime;
    vec3 p,l,b,d;p.z=t;
    d=normalize(vec3(2.*u-iResolution.xy,iResolution.y));
    for(o*=i;i<10.;i++){
        b=p;
        b.xy=r(sin(b.xy),t*1.5+b.z*3.);
        s=.001+abs(n(b*12.)/12.-n(b))*.4;
        s=max(s,2.-length(p.xy));
        s+=abs(p.y*.75+sin(p.z+t*.1+p.x*1.5))*.2;
        p+=d*s;
        l+=(1.+sin(i+length(p.xy*.1)+vec3(3,1.5,1)))/s;
    }
    o.rgb=a(l*l/6e2);
    
}


*Searched web for shadertoy Frostbyte "Only 10 Raymarch Steps"*

*Edited relevant file*

*Edited relevant file*

### User Input

// Planet Shadertoy. Created by Reinder Nijhoff 2015
// Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License.
// @reindernijhoff
//
// https://www.shadertoy.com/view/4tjGRh
//
// It uses code from the following shaders:
//
// Wet stone by TDM
// Atmospheric Scattering by GLtracy
// Seascape by TDM
// Elevated and Terrain Tubes by IQ
// LLamels by Eiffie
// Lens flare by Musk
// 

//#define HIGH_QUALITY
//#define MED_QUALITY
//#define LOW_QUALITY
#define VERY_LOW_QUALITY

const float PI = 3.14159265359;
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

        float alpha = 0., dint;
        vec3 offset = vec3(0), id, asteroidro;
        vec2 asteroid = vec2(0);

        for( int i=0; i<RING_VOXEL_STEPS; i++ ) {
            if( ringMap(pos) ) {
                id = hash33(pos);
                offset = id*(1.-2.*ASTEROID_RADIUS)+ASTEROID_RADIUS;
                dint = iSphere( ros, rd, vec4(pos+offset, ASTEROID_RADIUS) );

                if( dint > 0. ) {
                    asteroidro = ros+rd*dint-(pos+offset);
                    asteroid = asteroidSpheretracing( asteroidro, rd, id );

                    if( asteroid.y < .1 ) {
                        alpha = 1.;
                        break;	    
                    }
                }

            }
            vec3 mm = step(dis.xyz, dis.yxy) * step(dis.xyz, dis.zzx);
            dis += mm * rs * ri;
            pos += mm * rs;
        }

        if( alpha > 0. ) {       
            vec3 intersection = ros + rd*(asteroid.x+dint);
            vec3 n = asteroidGetNormal( asteroidro + rd*asteroid.x, id );

            vec3 col = asteroidGetStoneColor(intersection, .1, SUN_DIRECTION, n, rd);

            intersection *= RING_VOXEL_STEP_SIZE;
            intersection.xy += roxy;
          //  col *= ringShadowColor( intersection );

            return vec4( col, 1.-smoothstep(0.4*ASTEROID_MAX_DISTANCE, 0.5* ASTEROID_MAX_DISTANCE, distance( intersection, ro ) ) );
        } else {
            return vec4(0.);
        }
    }
}

//-----------------------------------------------------
// Ring (by me ;))
//-----------------------------------------------------

float renderRingFarShadow( const in vec3 ro, const in vec3 rd ) {
    // intersect plane
    float d = iPlane( ro, rd, vec4( 0., 0., 1., 0.) );
    
    if( d > 0. ) {
	    vec3 intersection = ro + rd*d;
        float l = length(intersection.xy);
        
        if( l > RING_INNER_RADIUS && l < RING_OUTER_RADIUS ) {
            return .5 + .5 * (.2+.8*noise( l*.07 )) * (.5+.5*noise(intersection.xy));
        } else {
            return 0.;
        }
    } else {
	    return 0.;
    }
}

vec4 renderRingFar( const in vec3 ro, const in vec3 rd, inout float maxd ) {
    // intersect plane
    float d = iPlane( ro, rd, vec4( 0., 0., 1., 0.) );
    
    if( d > 0. && d < maxd ) {
        maxd = d;
	    vec3 intersection = ro + rd*d;
        float l = length(intersection.xy);
        
        if( l > RING_INNER_RADIUS && l < RING_OUTER_RADIUS ) {
            float dens = .5 + .5 * (.2+.8*noise( l*.07 )) * (.5+.5*noise(intersection.xy));
            vec3 col = mix( RING_COLOR_1, RING_COLOR_2, abs( noise(l*0.2) ) ) * abs(dens) * 1.5;
            
            col *= ringShadowColor( intersection );
    		col *= .8+.3*diffuse( vec3(0,0,1), SUN_DIRECTION );
			col *= SUN_COLOR;
            return vec4( col, dens );
        } else {
            return vec4(0.);
        }
    } else {
	    return vec4(0.);
    }
}

vec4 renderRing( const in vec3 ro, const in vec3 rd, inout float maxd ) {
    vec4 far = renderRingFar( ro, rd, maxd );
    float l = length( ro.xy );

    if( abs(ro.z) < RING_HEIGHT+RING_DETAIL_DISTANCE 
        && l < RING_OUTER_RADIUS+RING_DETAIL_DISTANCE 
        && l > RING_INNER_RADIUS-RING_DETAIL_DISTANCE ) {
     	
	    float d = iPlane( ro, rd, vec4( 0., 0., 1., 0.) );
        float detail = mix( .5 * noise( fract(ro.xy+rd.xy*d) * 92.1)+.25, 1., smoothstep( 0.,RING_DETAIL_DISTANCE, d) );
        far.xyz *= detail;    
    }
    
	// are asteroids neaded ?
    if( abs(ro.z) < RING_HEIGHT+ASTEROID_MAX_DISTANCE 
        && l < RING_OUTER_RADIUS+ASTEROID_MAX_DISTANCE 
        && l > RING_INNER_RADIUS-ASTEROID_MAX_DISTANCE ) {
        
        vec4 near = renderRingNear( ro, rd );
        far = mix( far, near, near.w );
        maxd=0.;
    }
            
    return far;
}

//-----------------------------------------------------
// Stars (by me ;))
//-----------------------------------------------------

vec4 renderStars( const in vec3 rd ) {
	vec3 rds = rd;
	vec3 col = vec3(0);
    float v = 1.0/( 2. * ( 1. + rds.z ) );
    
    vec2 xy = vec2(rds.y * v, rds.x * v);
    float s = noise(rds*134.);
    
    s += noise(rds*470.);
    s = pow(s,19.0) * 0.00001;
    if (s > 0.5) {
        vec3 backStars = vec3(s)*.5 * vec3(0.95,0.8,0.9); 
        col += backStars;
    }
	return   vec4( col, 1 ); 
} 

//-----------------------------------------------------
// Atmospheric Scattering by GLtracy
// 
// https://www.shadertoy.com/view/lslXDr
//-----------------------------------------------------

const float ATMOSPHERE_K_R = 0.166;
const float ATMOSPHERE_K_M = 0.0025;
const float ATMOSPHERE_E = 12.3;
const vec3  ATMOSPHERE_C_R = vec3( 0.3, 0.7, 1.0 );
const float ATMOSPHERE_G_M = -0.85;

const float ATMOSPHERE_SCALE_H = 4.0 / ( EARTH_ATMOSPHERE );
const float ATMOSPHERE_SCALE_L = 1.0 / ( EARTH_ATMOSPHERE );

const float ATMOSPHERE_FNUM_OUT_SCATTER = float(ATMOSPHERE_NUM_OUT_SCATTER);
const float ATMOSPHERE_FNUM_IN_SCATTER = float(ATMOSPHERE_NUM_IN_SCATTER);

const int   ATMOSPHERE_NUM_OUT_SCATTER_LOW = 2;
const int   ATMOSPHERE_NUM_IN_SCATTER_LOW = 4;
const float ATMOSPHERE_FNUM_OUT_SCATTER_LOW = float(ATMOSPHERE_NUM_OUT_SCATTER_LOW);
const float ATMOSPHERE_FNUM_IN_SCATTER_LOW = float(ATMOSPHERE_NUM_IN_SCATTER_LOW);

float atmosphericPhaseMie( float g, float c, float cc ) {
	float gg = g * g;
	float a = ( 1.0 - gg ) * ( 1.0 + cc );
	float b = 1.0 + gg - 2.0 * g * c;
    
	b *= sqrt( b );
	b *= 2.0 + gg;	
	
	return 1.5 * a / b;
}

float atmosphericPhaseReyleigh( float cc ) {
	return 0.75 * ( 1.0 + cc );
}

float atmosphericDensity( vec3 p ){
	return exp( -( length( p ) - EARTH_RADIUS ) * ATMOSPHERE_SCALE_H );
}

float atmosphericOptic( vec3 p, vec3 q ) {
	vec3 step = ( q - p ) / ATMOSPHERE_FNUM_OUT_SCATTER;
	vec3 v = p + step * 0.5;
	
	float sum = 0.0;
	for ( int i = 0; i < ATMOSPHERE_NUM_OUT_SCATTER; i++ ) {
		sum += atmosphericDensity( v );
		v += step;
	}
	sum *= length( step ) * ATMOSPHERE_SCALE_L;
	
	return sum;
}

vec4 atmosphericInScatter( vec3 o, vec3 dir, vec2 e, vec3 l ) {
	float len = ( e.y - e.x ) / ATMOSPHERE_FNUM_IN_SCATTER;
	vec3 step = dir * len;
	vec3 p = o + dir * e.x;
	vec3 v = p + dir * ( len * 0.5 );

    float sumdensity = 0.;
	vec3 sum = vec3( 0.0 );

    for ( int i = 0; i < ATMOSPHERE_NUM_IN_SCATTER; i++ ) {
        vec3 u = v + l * iCSphereF( v, l, EARTH_RADIUS + EARTH_ATMOSPHERE );
		float n = ( atmosphericOptic( p, v ) + atmosphericOptic( v, u ) ) * ( PI * 4.0 );
		float dens = atmosphericDensity( v );
  
	    float m = MAX;
		sum += dens * exp( -n * ( ATMOSPHERE_K_R * ATMOSPHERE_C_R + ATMOSPHERE_K_M ) ) 
    		* (1. - renderRingFarShadow( u, SUN_DIRECTION ) );
 		sumdensity += dens;
        
		v += step;
	}
	sum *= len * ATMOSPHERE_SCALE_L;
	
	float c  = dot( dir, -l );
	float cc = c * c;
	
	return vec4( sum * ( ATMOSPHERE_K_R * ATMOSPHERE_C_R * atmosphericPhaseReyleigh( cc ) + 
                         ATMOSPHERE_K_M * atmosphericPhaseMie( ATMOSPHERE_G_M, c, cc ) ) * ATMOSPHERE_E, 
                	     clamp(sumdensity * len * ATMOSPHERE_SCALE_L,0.,1.));
}

float atmosphericOpticLow( vec3 p, vec3 q ) {
	vec3 step = ( q - p ) / ATMOSPHERE_FNUM_OUT_SCATTER_LOW;
	vec3 v = p + step * 0.5;
	
	float sum = 0.0;
	for ( int i = 0; i < ATMOSPHERE_NUM_OUT_SCATTER_LOW; i++ ) {
		sum += atmosphericDensity( v );
		v += step;
	}
	sum *= length( step ) * ATMOSPHERE_SCALE_L;
	
	return sum;
}

vec3 atmosphericInScatterLow( vec3 o, vec3 dir, vec2 e, vec3 l ) {
	float len = ( e.y - e.x ) / ATMOSPHERE_FNUM_IN_SCATTER_LOW;
	vec3 step = dir * len;
	vec3 p = o + dir * e.x;
	vec3 v = p + dir * ( len * 0.5 );

	vec3 sum = vec3( 0.0 );

    for ( int i = 0; i < ATMOSPHERE_NUM_IN_SCATTER_LOW; i++ ) {
		vec3 u = v + l * iCSphereF( v, l, EARTH_RADIUS + EARTH_ATMOSPHERE );
		float n = ( atmosphericOpticLow( p, v ) + atmosphericOpticLow( v, u ) ) * ( PI * 4.0 );
	    float m = MAX;
		sum += atmosphericDensity( v ) * exp( -n * ( ATMOSPHERE_K_R * ATMOSPHERE_C_R + ATMOSPHERE_K_M ) );
		v += step;
	}
	sum *= len * ATMOSPHERE_SCALE_L;
	
	float c  = dot( dir, -l );
	float cc = c * c;
	
	return sum * ( ATMOSPHERE_K_R * ATMOSPHERE_C_R * atmosphericPhaseReyleigh( cc ) + 
                   ATMOSPHERE_K_M * atmosphericPhaseMie( ATMOSPHERE_G_M, c, cc ) ) * ATMOSPHERE_E;
}

vec4 renderAtmospheric( const in vec3 ro, const in vec3 rd, inout float d ) {    
    // inside or outside atmosphere?
    vec2 e = iCSphere2( ro, rd, EARTH_RADIUS + EARTH_ATMOSPHERE );
	vec2 f = iCSphere2( ro, rd, EARTH_RADIUS );
        
    if( length(ro) <= EARTH_RADIUS + EARTH_ATMOSPHERE ) {
        if( d < e.y ) {
            e.y = d;
        }
		d = e.y;
	    e.x = 0.;
        
	    if ( iSphere( ro, rd, vec4(0,0,0,EARTH_RADIUS)) > 0. ) {
	        d = iSphere( ro, rd, vec4(0,0,0,EARTH_RADIUS));
		}
    } else {
    	if(  iSphere( ro, rd, vec4(0,0,0,EARTH_RADIUS + EARTH_ATMOSPHERE )) < 0. ) return vec4(0.);
        
        if ( e.x > e.y ) {
        	d = MAX;
			return vec4(0.);
		}
		d = e.y = min( e.y, f.x );
    }
	return atmosphericInScatter( ro, rd, e, SUN_DIRECTION );
}

vec3 renderAtmosphericLow( const in vec3 ro, const in vec3 rd ) {    
    vec2 e = iCSphere2( ro, rd, EARTH_RADIUS + EARTH_ATMOSPHERE );
    e.x = 0.;
    return atmosphericInScatterLow( ro, rd, e, SUN_DIRECTION );
}

//-----------------------------------------------------
// Seascape by TDM
// 
// https://www.shadertoy.com/view/Ms2SD1
//-----------------------------------------------------

const int   SEA_ITER_GEOMETRY = 3;
const int   SEA_ITER_FRAGMENT = 5;

const float SEA_EPSILON	= 1e-3;
#define       SEA_EPSILON_NRM	(0.1 / iResolution.x)
const float SEA_HEIGHT = 0.6;
const float SEA_CHOPPY = 4.0;
const float SEA_SPEED = 0.8;
const float SEA_FREQ = 0.16;
const vec3  SEA_BASE = vec3(0.1,0.19,0.22);
const vec3  SEA_WATER_COLOR = vec3(0.8,0.9,0.6);
float       SEA_TIME;
const mat2  sea_octave_m = mat2(1.6,1.2,-1.2,1.6);

float seaOctave( in vec2 uv, const in float choppy) {
    uv += noise(uv);        
    vec2 wv = 1.0-abs(sin(uv));
    vec2 swv = abs(cos(uv));    
    wv = mix(wv,swv,wv);
    return pow(1.0-pow(wv.x * wv.y,0.65),choppy);
}

float seaMap(const in vec3 p) {
    float freq = SEA_FREQ;
    float amp = SEA_HEIGHT;
    float choppy = SEA_CHOPPY;
    vec2 uv = p.xz; uv.x *= 0.75;
    
    float d, h = 0.0;    
    for(int i = 0; i < SEA_ITER_GEOMETRY; i++) {        
    	d = seaOctave((uv+SEA_TIME)*freq,choppy);
    	d += seaOctave((uv-SEA_TIME)*freq,choppy);
        h += d * amp;        
    	uv *= sea_octave_m; freq *= 1.9; amp *= 0.22;
        choppy = mix(choppy,1.0,0.2);
    }
    return p.y - h;
}

float seaMapHigh(const in vec3 p) {
    float freq = SEA_FREQ;
    float amp = SEA_HEIGHT;
    float choppy = SEA_CHOPPY;
    vec2 uv = p.xz; uv.x *= 0.75;
    
    float d, h = 0.0;    
    for(int i = 0; i < SEA_ITER_FRAGMENT; i++) {        
    	d = seaOctave((uv+SEA_TIME)*freq,choppy);
    	d += seaOctave((uv-SEA_TIME)*freq,choppy);
        h += d * amp;        
    	uv *= sea_octave_m; freq *= 1.9; amp *= 0.22;
        choppy = mix(choppy,1.0,0.2);
    }
    return p.y - h;
}

vec3 seaGetColor( const in vec3 n, vec3 eye, const in vec3 l, const in float att, 
                  const in vec3 sunc, const in vec3 upc, const in vec3 reflected) {  
    vec3 refracted = SEA_BASE * upc + diffuse(n,l) * SEA_WATER_COLOR * 0.12 * sunc; 
    vec3 color = mix(refracted,reflected,fresnel(n, -eye, 3.)*.65 );
    
    color += upc*SEA_WATER_COLOR * (att * 0.18);
    color += sunc * vec3(specular(n,l,eye,60.0));
    
    return color;
}

vec3 seaGetNormal(const in vec3 p, const in float eps) {
    vec3 n;
    n.y = seaMapHigh(p);    
    n.x = seaMapHigh(vec3(p.x+eps,p.y,p.z)) - n.y;
    n.z = seaMapHigh(vec3(p.x,p.y,p.z+eps)) - n.y;
    n.y = eps;
    return normalize(n);
}

float seaHeightMapTracing(const in vec3 ori, const in vec3 dir, out vec3 p) {  
    float tm = 0.0;
    float tx = 1000.0;    
    float hx = seaMap(ori + dir * tx);
    if(hx > 0.0) return tx;   
    float hm = seaMap(ori + dir * tm);    
    float tmid = 0.0;
    for(int i = 0; i < SEA_NUM_STEPS; i++) {
        tmid = mix(tm,tx, hm/(hm-hx));                   
        p = ori + dir * tmid;                   
    	float hmid = seaMap(p);
		if(hmid < 0.0) {
        	tx = tmid;
            hx = hmid;
        } else {
            tm = tmid;
            hm = hmid;
        }
    }
    return tmid;
}

vec3 seaTransform( in vec3 x ) {
    x.yz = rotate( 0.8, x.yz );
    return x;
}

vec3 seaUntransform( in vec3 x ) {
    x.yz = rotate( -0.8, x.yz );
    return x;
}

void renderSea( const in vec3 ro, const in vec3 rd, inout vec3 n, inout float att ) {    
    vec3 p,
    rom = seaTransform(ro),
    rdm = seaTransform(rd);
    
    rom.y -= EARTH_RADIUS;
    rom *= 1000.;
    rom.xz += vec2(3.1,.2)*time;

    SEA_TIME = time * SEA_SPEED;
    
    seaHeightMapTracing(rom,rdm,p);
    float squareddist = dot(p - rom, p-rom );
    n = seaGetNormal(p, squareddist * SEA_EPSILON_NRM );
    
    n = seaUntransform(n);
    
    att = clamp(SEA_HEIGHT+p.y, 0.,1.);
}

//-----------------------------------------------------
// Terrain based on Elevated and Terrain Tubes by IQ
//
// https://www.shadertoy.com/view/MdX3Rr
// https://www.shadertoy.com/view/4sjXzG
//-----------------------------------------------------

#ifndef HIDE_TERRAIN

const mat2 terrainM2 = mat2(1.6,-1.2,1.2,1.6);

float terrainLow( vec2 p ) {
    p *= 0.0013;

    float s = 1.0;
	float t = 0.0;
	for( int i=0; i<2; i++ ) {
        t += s*tri( p );
		s *= 0.5 + 0.1*t;
        p = 0.97*terrainM2*p + (t-0.5)*0.12;
	}
	return t*33.0;
}

float terrainMed( vec2 p ) {
    p *= 0.0013;

    float s = 1.0;
	float t = 0.0;
	for( int i=0; i<6; i++ ) {
        t += s*tri( p );
		s *= 0.5 + 0.1*t;
        p = 0.97*terrainM2*p + (t-0.5)*0.12;
	}
            
    return t*33.0;
}

float terrainHigh( vec2 p ) {
    vec2 q = p;
    p *= 0.0013;

    float s = 1.0;
	float t = 0.0;
	for( int i=0; i<7; i++ ) {
        t += s*tri( p );
		s *= 0.5 + 0.1*t;
        p = 0.97*terrainM2*p + (t-0.5)*0.12;
	}
    
    t += t*0.015*fbm( q );
	return t*33.0;
}

float terrainMap( const in vec3 pos ) {
	return pos.y - terrainMed(pos.xz);  
}

float terrainMapH( const in vec3 pos ) {
    float y = terrainHigh(pos.xz);
    float h = pos.y - y;
    return h;
}

float terrainIntersect( in vec3 ro, in vec3 rd, in float tmin, in float tmax ) {
    float t = tmin;
	for( int i=0; i<TERRAIN_NUM_STEPS; i++ ) {
        vec3 pos = ro + t*rd;
        float res = terrainMap( pos );
        if( res<(0.001*t) || t>tmax  ) break;
        t += res*.9;
	}

	return t;
}

float terrainCalcShadow(in vec3 ro, in vec3 rd ) {
	vec2  eps = vec2(150.0,0.0);
    float h1 = terrainMed( ro.xz );
    float h2 = terrainLow( ro.xz );
    
    float d1 = 10.0;
    float d2 = 80.0;
    float d3 = 200.0;
    float s1 = clamp( 1.0*(h1 + rd.y*d1 - terrainMed(ro.xz + d1*rd.xz)), 0.0, 1.0 );
    float s2 = clamp( 0.5*(h1 + rd.y*d2 - terrainMed(ro.xz + d2*rd.xz)), 0.0, 1.0 );
    float s3 = clamp( 0.2*(h2 + rd.y*d3 - terrainLow(ro.xz + d3*rd.xz)), 0.0, 1.0 );

    return min(min(s1,s2),s3);
}
vec3 terrainCalcNormalHigh( in vec3 pos, float t ) {
    vec2 e = vec2(1.0,-1.0)*0.001*t;

    return normalize( e.xyy*terrainMapH( pos + e.xyy ) + 
					  e.yyx*terrainMapH( pos + e.yyx ) + 
					  e.yxy*terrainMapH( pos + e.yxy ) + 
					  e.xxx*terrainMapH( pos + e.xxx ) );
}

vec3 terrainCalcNormalMed( in vec3 pos, float t ) {
	float e = 0.005*t;
    vec2  eps = vec2(e,0.0);
    float h = terrainMed( pos.xz );
    return normalize(vec3( terrainMed(pos.xz-eps.xy)-h, e, terrainMed(pos.xz-eps.yx)-h ));
}

vec3 terrainTransform( in vec3 x ) {
    x.zy = rotate( -.83, x.zy );
    return x;
}

vec3 terrainUntransform( in vec3 x ) {
    x.zy = rotate( .83, x.zy );
    return x;
}


float llamelTime;
const float llamelScale = 5.;

vec3 llamelPosition() {
    llamelTime = time*2.5;
    vec2 pos = vec2( -400., 135.-llamelTime*0.075* llamelScale);
    return vec3( pos.x, terrainMed( pos ), pos.y );
}

vec3 terrainShade( const in vec3 col, const in vec3 pos, const in vec3 rd, const in vec3 n, const in float spec, 
                   const in vec3 sunc, const in vec3 upc, const in vec3 reflc ) {
	vec3 sunDirection =  terrainTransform(SUN_DIRECTION);
    float dif = diffuse( n, sunDirection );
    float bac = diffuse( n, vec3(-sunDirection.x, sunDirection.y, -sunDirection.z) );
    float sha = terrainCalcShadow( pos, sunDirection );
    float amb = clamp( n.y,0.0,1.0);
        
    vec3 lin  = vec3(0.0);
    lin += 2.*dif*sunc*vec3( sha, sha*sha*0.1+0.9*sha, sha*sha*0.2+0.8*sha );
    lin += 0.2*amb*upc;
    lin += 0.08*bac*clamp(vec3(1.)-sunc, vec3(0.), vec3(1.));
    return mix( col*lin*3., reflc, spec*fresnel(n,-terrainTransform(rd),5.0) );
}

vec3 terrainGetColor( const in vec3 pos, const in vec3 rd, const in float t, const in vec3 sunc, const in vec3 upc, const in vec3 reflc ) {
    vec3 nor = terrainCalcNormalHigh( pos, t );
    vec3 sor = terrainCalcNormalMed( pos, t );
        
    float spec = 0.005;

#ifdef DISPLAY_TERRAIN_DETAIL
    float no = noise(5.*fbm(1.11*pos.xz));
#else
    const float no = 0.;
#endif
    float r = .5+.5*fbm(.95*pos.xz);
	vec3 col = (r*0.25+0.75)*0.9*mix( vec3(0.08,0.07,0.07), vec3(0.10,0.09,0.08), noise(0.4267*vec2(pos.x*2.,pos.y*9.8))+.01*no );
    col = mix( col, 0.20*vec3(0.45,.30,0.15)*(0.50+0.50*r),smoothstep(0.825,0.925,nor.y+.025*no) );
	col = mix( col, 0.15*vec3(0.30,.30,0.10)*(0.25+0.75*r),smoothstep(0.95,1.0,nor.y+.025*no) );
    col *= .88+.12*no;
        
    float s = nor.y + 0.03*pos.y + 0.35*fbm(0.05*pos.xz) - .35;
    float sf = fwidth(s) * 1.5;
    s = smoothstep(0.84-sf, 0.84+sf, s );
    col = mix( col, 0.29*vec3(0.62,0.65,0.7), s);
    nor = mix( nor, sor, 0.7*smoothstep(0.9, 0.95, s ) );
    spec = mix( spec, 0.45, smoothstep(0.9, 0.95, s ) );

   	col = terrainShade( col, pos, rd, nor, spec, sunc, upc, reflc );

#ifdef DISPLAY_LLAMEL
    col *= clamp( distance(pos.xz, llamelPosition().xz )*0.4, 0.4, 1.);
#endif
    
    return col;
}

vec3 terrainTransformRo( const in vec3 ro ) {
    vec3 rom = terrainTransform(ro);
    rom.y -= EARTH_RADIUS - 100.;
    rom.xz *= 5.;
    rom.xz += vec2(-170.,50.)+vec2(-4.,.4)*time;    
    rom.y += (terrainLow( rom.xz ) - 86.)*clamp( 1.-1.*(length(ro)-EARTH_RADIUS), 0., 1.);
    return rom;
}

vec4 renderTerrain( const in vec3 ro, const in vec3 rd, inout vec3 intersection, inout vec3 n ) {    
    vec3 p,
    rom = terrainTransformRo(ro),
    rdm = terrainTransform(rd);
        
    float tmin = 10.0;
    float tmax = 3200.0;
    
    float res = terrainIntersect( rom, rdm, tmin, tmax );
    
    if( res > tmax ) {
        res = -1.;
    } else {
        vec3 pos =  rom+rdm*res;
        n = terrainCalcNormalMed( pos, res );
        n = terrainUntransform( n );
        
        intersection = ro+rd*res/100.;
    }
    return vec4(res, rom+rdm*res);
}

#endif

//-----------------------------------------------------
// LLamels by Eiffie
//
// https://www.shadertoy.com/view/ltsGz4
//-----------------------------------------------------
#ifdef DISPLAY_LLAMEL
float llamelMapSMin(const in float a,const in float b,const in float k){
    float h=clamp(0.5+0.5*(b-a)/k,0.0,1.0);return b+h*(a-b-k+k*h);
}

float llamelMapLeg(vec3 p, vec3 j0, vec3 j3, vec3 l, vec4 r, vec3 rt){//z joint with tapered legs
	float lx2z=l.x/(l.x+l.z),h=l.y*lx2z;
	vec3 u=(j3-j0)*lx2z,q=u*(0.5+0.5*(l.x*l.x-h*h)/dot(u,u));
	q+=sqrt(max(0.0,l.x*l.x-dot(q,q)))*normalize(cross(u,rt));
	vec3 j1=j0+q,j2=j3-q*(1.0-lx2z)/lx2z;
	u=p-j0;q=j1-j0;
	h=clamp(dot(u,q)/dot(q,q),0.0,1.0);
	float d=length(u-q*h)-r.x-(r.y-r.x)*h;
	u=p-j1;q=j2-j1;
	h=clamp(dot(u,q)/dot(q,q),0.0,1.0);
	d=min(d,length(u-q*h)-r.y-(r.z-r.y)*h);
	u=p-j2;q=j3-j2;
	h=clamp(dot(u,q)/dot(q,q),0.0,1.0);
	return min(d,length(u-q*h)-r.z-(r.w-r.z)*h);
}

float llamelMap(in vec3 p) {
	const vec3 rt=vec3(0.0,0.0,1.0);	
	p.y += 0.25*llamelScale;
    p.xz -= 0.5*llamelScale;
    p.xz = vec2(-p.z, p.x);
    vec3 pori = p;
        
    p /= llamelScale;
    
	vec2 c=floor(p.xz);
	p.xz=fract(p.xz)-vec2(0.5);
    p.y -= p.x*.04*llamelScale;
	float sa=sin(c.x*2.0+c.y*4.5+llamelTime*0.05)*0.15;

    float b=0.83-abs(p.z);
	float a=c.x+117.0*c.y+sign(p.x)*1.57+sign(p.z)*1.57+llamelTime,ca=cos(a);
	vec3 j0=vec3(sign(p.x)*0.125,ca*0.01,sign(p.z)*0.05),j3=vec3(j0.x+sin(a)*0.1,max(-0.25+ca*0.1,-0.25),j0.z);
	float dL=llamelMapLeg(p,j0,j3,vec3(0.08,0.075,0.12),vec4(0.03,0.02,0.015,0.01),rt*sign(p.x));
	p.y-=0.03;
	float dB=(length(p.xyz*vec3(1.0,1.75,1.75))-0.14)*0.75;
	a=c.x+117.0*c.y+llamelTime;ca=cos(a);sa*=0.4;
	j0=vec3(0.125,0.03+abs(ca)*0.03,ca*0.01),j3=vec3(0.3,0.07+ca*sa,sa);
	float dH=llamelMapLeg(p,j0,j3,vec3(0.075,0.075,0.06),vec4(0.03,0.035,0.03,0.01),rt);
	dB=llamelMapSMin(min(dL,dH),dB,clamp(0.04+p.y,0.0,1.0));
	a=max(abs(p.z),p.y)+0.05;
	return max(min(dB,min(a,b)),length(pori.xz-vec2(0.5)*llamelScale)-.5*llamelScale);
}

vec3 llamelGetNormal( in vec3 ro ) {
    vec2 e = vec2(1.0,-1.0)*0.001;

    return normalize( e.xyy*llamelMap( ro + e.xyy ) + 
					  e.yyx*llamelMap( ro + e.yyx ) + 
					  e.yxy*llamelMap( ro + e.yxy ) + 
					  e.xxx*llamelMap( ro + e.xxx ) );
}

vec4 renderLlamel( in vec3 ro, const in vec3 rd, const in vec3 sunc, const in vec3 upc, const in vec3 reflc ) {
    ro -= llamelPosition();
	float t=.1*hash(rd.xy),d,dm=10.0,tm;
	for(int i=0;i<36;i++){
		t+=d=llamelMap(ro+rd*t);
		if(d<dm){dm=d;tm=t;}
		if(t>1000.0 || d<0.00001)break;
	}
	dm=max(0.0,dm);
    if( dm < .02 ) {
        vec3 col = vec3(0.45,.30,0.15)*.2;
        vec3 pos = ro + rd*tm;
        vec3 nor = llamelGetNormal( pos );
        col = terrainShade( col, pos, rd, nor, .01, sunc, upc, reflc );        
        return vec4(col, clamp( 1.-(dm-0.01)/0.01,0., 1.) );
    }
    
    return vec4(0.);
}
#endif

//-----------------------------------------------------
// Clouds (by me ;))
//-----------------------------------------------------

vec4 renderClouds( const in vec3 ro, const in vec3 rd, const in float d, const in vec3 n, const in float land, 
                   const in vec3 sunColor, const in vec3 upColor, inout float shadow ) {
	vec3 intersection = ro+rd*d;
    vec3 cint = intersection*0.009;
    float rot = -.2*length(cint.xy) + .6*fbm( cint*.4,0.5,2.96 ) + .05*land;

    cint.xy = rotate( rot, cint.xy );

    vec3 cdetail = mod(intersection*3.23,vec3(50.));
    cdetail.xy = rotate( .25*rot, cdetail.xy );

    float clouds = 1.3*(fbm( cint*(1.+.02*noise(intersection)),0.5,2.96)+.4*land-.3);

#ifdef DISPLAY_CLOUDS_DETAIL
    if( d < 200. ) {
        clouds += .3*(fbm(cdetail,0.5,2.96)-.5)*(1.-smoothstep(0.,200.,d));
    }
#endif

    shadow = clamp(1.-clouds, 0., 1.);

    clouds = clamp(clouds, 0., 1.);
    clouds *= clouds;
    clouds *= smoothstep(0.,0.4,d);

    vec3 clbasecolor = vec3(1.);
    vec3 clcol = .1*clbasecolor*sunColor * vec3(specular(n,SUN_DIRECTION,rd,36.0));
    clcol += .3*clbasecolor*sunColor;
    clcol += clbasecolor*(diffuse(n,SUN_DIRECTION)*sunColor+upColor);  
    
    return vec4( clcol, clouds );
}

//-----------------------------------------------------
// Planet (by me ;))
//-----------------------------------------------------

vec4 renderPlanet( const in vec3 ro, const in vec3 rd, const in vec3 up, inout float maxd ) {
    float d = iSphere( ro, rd, vec4( 0., 0., 0., EARTH_RADIUS ) );

    vec3 intersection = ro + rd*d;
    vec3 n = nSphere( intersection, vec4( 0., 0., 0., EARTH_RADIUS ) );
    vec4 res;

#ifndef HIDE_TERRAIN
    bool renderTerrainDetail = length(ro) < EARTH_RADIUS+EARTH_ATMOSPHERE && 
        					   dot( terrainUntransform( vec3(0.,1.,0.) ), normalize(ro) ) > .9996;
#endif
    bool renderSeaDetail     = d < 1. && dot( seaUntransform( vec3(0.,1.,0.) ), normalize(ro) ) > .9999; 
    float mixDetailColor = 0.;
        
	if( d < 0. || d > maxd) {
#ifndef HIDE_TERRAIN
        if( renderTerrainDetail ) {
       		intersection = ro;
            n = normalize( ro );
        } else { 	       
	        return vec4(0);
        }
#else 
      	return vec4(0.);
#endif
	}
    if( d > 0. ) {
	    maxd = d;
    }
    float att = 0.;
    
    if( dot(n,SUN_DIRECTION) < -0.1 ) return vec4( 0., 0., 0., 1. );
    
    float dm = MAX, e = 0.;
    vec3 col, detailCol, nDetail;
    
    // normal and intersection 
#ifndef HIDE_TERRAIN
    if( renderTerrainDetail ) {   
        res = renderTerrain( ro, rd, intersection, nDetail );
        if( res.x < 0. && d < 0. ) {
	        return vec4(0);
        }
        if( res.x >= 0. ) {
            maxd = pow(res.x/4000.,4.)*50.;
            e = -10.;
        }
        mixDetailColor = 1.-smoothstep(.75, 1., (length(ro)-EARTH_RADIUS) / EARTH_ATMOSPHERE);
        n = normalize( mix( n, nDetail, mixDetailColor ) );
    } else 
#endif        
    if( renderSeaDetail ) {    
        float attsea, mf = smoothstep(.5,1.,d);

        renderSea( ro, rd, nDetail, attsea );

        n = normalize(mix( nDetail, n, mf ));
        att = mix( attsea, att, mf );
    } else {
        e = fbm( .003*intersection+vec3(1.),0.4,2.96) + smoothstep(.85,.95, abs(intersection.z/EARTH_RADIUS));
#ifndef HIDE_TERRAIN
        if( d < 1500. ) {
            e += (-.03+.06* fbm( intersection*0.1,0.4,2.96))*(1.-d/1500.);
        }
#endif  
    }
    
    vec3 sunColor = .25*renderAtmosphericLow( intersection, SUN_DIRECTION).xyz;  
    vec3 upColor = 2.*renderAtmosphericLow( intersection, n).xyz;  
    vec3 reflColor = renderAtmosphericLow( intersection, reflect(rd,n)).xyz; 
                 
    // color  
#ifndef HIDE_TERRAIN
    if(renderTerrainDetail ) {
        detailCol = col =  terrainGetColor(res.yzw, rd, res.x, sunColor, upColor, reflColor);
		d = 0.;
    }   
#endif
     
    if( mixDetailColor < 1. ) {
        if( e < .45 ) {
            // sea
            col = seaGetColor(n,rd,SUN_DIRECTION, att, sunColor, upColor, reflColor);    
        } else {
            // planet (land) far
            float land1 = max(0.1, fbm( intersection*0.0013,0.4,2.96) );
            float land2 = max(0.1, fbm( intersection*0.0063,0.4,2.96) );
            float iceFactor = abs(pow(intersection.z/EARTH_RADIUS,13.0))*e;

            vec3 landColor1 = vec3(0.43,0.65,0.1) * land1;
            vec3 landColor2 = RING_COLOR_1 * land2;
            vec3 mixedLand = (landColor1 + landColor2)* 0.5;
            vec3 finalLand = mix(mixedLand, vec3(7.0, 7.0, 7.0) * land1 * 1.5, max(iceFactor+.02*land2-.02, 0.));

            col = (diffuse(n,SUN_DIRECTION)*sunColor+upColor)*finalLand*.75;
#ifdef HIGH_QUALITY
            col *= (.5+.5*fbm( intersection*0.23,0.4,2.96) );
#endif
        }
    }
    
    if( mixDetailColor > 0. ) {
        col = mix( col, detailCol, mixDetailColor );
    }
        
#ifdef DISPLAY_LLAMEL
    if(renderTerrainDetail ) {
        vec3 rom = terrainTransformRo(ro),
        rdm = terrainTransform(rd);
        d = iSphere( rom, rdm, vec4( llamelPosition(), llamelScale*3. ) );
        if( d > 0. ) {
            vec4 llamel = renderLlamel( rom+rdm*d, rdm, sunColor, upColor, reflColor );
            col = mix(col, llamel.rgb, llamel.a);
        }
    }
#endif
    
    d = iSphere( ro, rd, vec4( 0., 0., 0., EARTH_RADIUS+EARTH_CLOUDS ) );
    if( d > 0. ) { 
        float shadow;
		vec4 clouds = renderClouds( ro, rd, d, n, e, sunColor, upColor, shadow);
        col *= shadow; 
        col = mix( col, clouds.rgb, clouds.w );
    }
    
    float m = MAX;
    col *= (1. - renderRingFarShadow( ro+rd*d, SUN_DIRECTION ) );

 	return vec4( col, 1. ); 
}

//-----------------------------------------------------
// Lens flare by musk
//
// https://www.shadertoy.com/view/4sX3Rs
//-----------------------------------------------------

vec3 lensFlare( const in vec2 uv, const in vec2 pos) {
	vec2 main = uv-pos;
	vec2 uvd = uv*(length(uv));
	
	float f0 = 1.5/(length(uv-pos)*16.0+1.0);
	
	float f1 = max(0.01-pow(length(uv+1.2*pos),1.9),.0)*7.0;

	float f2 = max(1.0/(1.0+32.0*pow(length(uvd+0.8*pos),2.0)),.0)*00.25;
	float f22 = max(1.0/(1.0+32.0*pow(length(uvd+0.85*pos),2.0)),.0)*00.23;
	float f23 = max(1.0/(1.0+32.0*pow(length(uvd+0.9*pos),2.0)),.0)*00.21;
	
	vec2 uvx = mix(uv,uvd,-0.5);
	
	float f4 = max(0.01-pow(length(uvx+0.4*pos),2.4),.0)*6.0;
	float f42 = max(0.01-pow(length(uvx+0.45*pos),2.4),.0)*5.0;
	float f43 = max(0.01-pow(length(uvx+0.5*pos),2.4),.0)*3.0;
	
	vec3 c = vec3(.0);
	
	c.r+=f2+f4; c.g+=f22+f42; c.b+=f23+f43;
	c = c*.5 - vec3(length(uvd)*.05);
	c+=vec3(f0);
	
	return c;
}

//-----------------------------------------------------
// cameraPath
//-----------------------------------------------------

vec3 pro, pta, pup;
float dro, dta, dup;

void camint( inout vec3 ret, const in float t, const in float duration, const in vec3 dest, inout vec3 prev, inout float prevt ) {
    if( t >= prevt && t <= prevt+duration ) {
    	ret = mix( prev, dest, smoothstep(prevt, prevt+duration, t) );
    }
    prev = dest;
    prevt += duration;
}

void cameraPath( in float t, out vec3 ro, out vec3 ta, out vec3 up ) {
#ifndef HIDE_TERRAIN
    time = t = mod( t, 92. );
#else
    time = t = mod( t, 66. );
#endif
    dro = dta = dup = 0.;

    pro = ro = vec3(900. ,7000. ,1500. );
    pta = ta = vec3(    0. ,    0. ,   0. );
    pup = up = vec3(    0. ,    0.4,   1. ); 
   
    camint( ro, t, 5., vec3(-4300. ,-1000. , 500. ), pro, dro );
    camint( ta, t, 5., vec3(    0. ,    0. ,   0. ), pta, dta );
    camint( up, t, 7., vec3(    0. ,    0.1,   1. ), pup, dup ); 
 
    camint( ro, t, 3., vec3(-1355. , 1795. , 1.2 ), pro, dro );
    camint( ta, t, 1., vec3(    0. , 300. ,-600. ), pta, dta );
    camint( up, t, 6., vec3(    0. ,  0.1,    1. ), pup, dup );

    camint( ro, t, 10., vec3(-1355. , 1795. , 1.2 ), pro, dro );
    camint( ta, t, 14., vec3(    0. , 100. ,   600. ), pta, dta );
    camint( up, t, 13., vec3(    0. ,  0.3,    1. ), pup, dup );
    
    vec3 roe = seaUntransform( vec3( 0., EARTH_RADIUS+0.004, 0. ) );
    vec3 upe = seaUntransform( vec3( 0., 1., 0. ) );
    
    camint( ro, t, 7.,roe, pro, dro );
    camint( ta, t, 7., vec3( EARTH_RADIUS + 0., EARTH_RADIUS - 500., 500. ), pta, dta );
    camint( up, t, 6., upe, pup, dup );
        
    camint( ro, t, 17.,roe, pro, dro );
    camint( ta, t, 17., vec3( EARTH_RADIUS + 500., EARTH_RADIUS + 1300., -100. ), pta, dta );
    camint( up, t, 18., vec3(.0,1.,1.), pup, dup );
    
    camint( ro, t, 11., vec3(  3102. ,  0. , 1450. ), pro, dro );
    camint( ta, t, 4., vec3(    0. ,   -100. ,   0. ), pta, dta );
    camint( up, t, 8., vec3(    0. ,    0.15,   1. ), pup, dup ); 
#ifndef HIDE_TERRAIN    
    roe = terrainUntransform( vec3( 0., EARTH_RADIUS+0.004, 0. ) );
    upe = terrainUntransform( vec3( 0., 1., 0. ) );
    
    camint( ro, t, 7., roe, pro, dro );
    camint( ta, t, 12., vec3( -EARTH_RADIUS, EARTH_RADIUS+200., 100.), pta, dta );
    camint( up, t, 2., upe, pup, dup );
        
    roe = terrainUntransform( vec3( 0., EARTH_RADIUS+0.001, 0. ) );
    camint( ro, t, 17.,roe, pro, dro );
    camint( ta, t, 18., roe + vec3( 5000., EARTH_RADIUS-100., -2000.), pta, dta );
    camint( up, t, 18., vec3(.0,1.,1.), pup, dup );
        
    roe = terrainUntransform( vec3( 0., EARTH_RADIUS+1.8, 0. ) );
    camint( ro, t, 4.,roe, pro, dro );
    camint( ta, t, 4.5, roe + vec3( EARTH_RADIUS, EARTH_RADIUS+2000., -30.), pta, dta );
    camint( up, t, 4., vec3(.0,1.,1.), pup, dup );
#endif    
    camint( ro, t, 10., vec3(900. ,7000. , 1500. ), pro, dro );
    camint( ta, t, 2., vec3(    0. ,    0. ,   0. ), pta, dta );
    camint( up, t, 10., vec3(    0. ,    0.4,   1. ), pup, dup ); 
    
    up = normalize( up );
}

//-----------------------------------------------------
// mainImage
//-----------------------------------------------------

void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
	vec2 uv = fragCoord.xy / iResolution.xy;
    
    vec2 p = -1.0 + 2.0 * (fragCoord.xy) / iResolution.xy;
    p.x *= iResolution.x/iResolution.y;
    
    vec3 col;
    
// black bands
    vec2 bandy = vec2(.1,.9);
    if( uv.y < bandy.x || uv.y > bandy.y ) {
        col = vec3(0.);
    } else {
        // camera
        vec3 ro, ta, up;
        cameraPath( iTime*.7, ro, ta, up );

        vec3 ww = normalize( ta - ro );
        vec3 uu = normalize( cross(ww,up) );
        vec3 vv = normalize( cross(uu,ww));
        vec3 rd = normalize( -p.x*uu + p.y*vv + 2.2*ww );

        float maxd = MAX;  
        col = renderStars( rd ).xyz;

        vec4 planet = renderPlanet( ro, rd, up, maxd );       
        if( planet.w > 0. ) col.xyz = planet.xyz;

        float atmosphered = maxd;
        vec4 atmosphere = .85*renderAtmospheric( ro, rd, atmosphered );
        col = col * (1.-atmosphere.w ) + atmosphere.xyz; 

        vec4 ring = renderRing( ro, rd, maxd );
        if( ring.w > 0. && atmosphered < maxd ) {
           ring.xyz = ring.xyz * (1.-atmosphere.w ) + atmosphere.xyz; 
        }
        col = col * (1.-ring.w ) + ring.xyz;

#ifdef DISPLAY_CLOUDS
        float lro = length(ro);
        if( lro < EARTH_RADIUS+EARTH_CLOUDS*1.25 ) {
            vec3 sunColor = 2.*renderAtmosphericLow( ro, SUN_DIRECTION);  
            vec3 upColor = 4.*renderAtmosphericLow( ro, vec3(-SUN_DIRECTION.x, SUN_DIRECTION.y, -SUN_DIRECTION.z));  

            if( lro < EARTH_RADIUS+EARTH_CLOUDS ) {
                // clouds
                float d = iCSphereF( ro, rd, EARTH_RADIUS + EARTH_CLOUDS );
                if( d < maxd ) {
                    float shadow;
                    vec4 clouds = renderClouds( ro, rd, d, normalize(ro), 0., sunColor, upColor, shadow );
                    clouds.w *= 1.-smoothstep(0.8*EARTH_CLOUDS,EARTH_CLOUDS,lro-EARTH_RADIUS);
                    col = mix(col, clouds.rgb, clouds.w * (1.-smoothstep( 10., 30., d)) );
                }
            }
            float offset = lro-EARTH_RADIUS-EARTH_CLOUDS;
            col = mix( col, .5*sunColor, .15*abs(noise(offset*100.))*clamp(1.-4.*abs(offset)/EARTH_CLOUDS, 0., 1.) );
        }
#endif 

        // post processing
        col = pow( clamp(col,0.0,1.0), vec3(0.4545) );
        col *= vec3(1.,0.99,0.95);   
        col = clamp(1.06*col-0.03, 0., 1.);      

        vec2 sunuv =  2.7*vec2( dot( SUN_DIRECTION, -uu ), dot( SUN_DIRECTION, vv ) );
        float flare = dot( SUN_DIRECTION, normalize(ta-ro) );
        col += vec3(1.4,1.2,1.0)*lensFlare(p, sunuv)*clamp( flare+.3, 0., 1.);

        uv.y = (uv.y-bandy.x)*(1./(bandy.y-bandy.x));
        col *= 0.5 + 0.5*pow( 16.0*uv.x*uv.y*(1.0-uv.x)*(1.0-uv.y), 0.1 ); 
    }
    fragColor = vec4( col ,1.0);
}

void mainVR( out vec4 fragColor, in vec2 fragCoord, in vec3 ro, in vec3 rd ) {
    float maxd = MAX;  
    time = iTime * .7;
    
    rd = rd.xzy;
    ro = (ro.xzy * .1) + vec3(-1355. , 1795. , 1. );
    
    vec3 col = renderStars( rd ).xyz;

    vec4 planet = renderPlanet( ro, rd, vec3(0,.1,1), maxd );       
    if( planet.w > 0. ) col.xyz = planet.xyz;

    float atmosphered = maxd;
    vec4 atmosphere = .85*renderAtmospheric( ro, rd, atmosphered );
    col = col * (1.-atmosphere.w ) + atmosphere.xyz; 

    vec4 ring = renderRing( ro, rd, maxd );
    col = col * (1.-ring.w ) + ring.xyz;
    
    // post processing
    col = pow( clamp(col,0.0,1.0), vec3(0.4545) );
    col *= vec3(1.,0.99,0.95);   
    col = clamp(1.06*col-0.03, 0., 1.);      
    fragColor = vec4( col ,1.0);
}  Sound: 
//----------------------------------------------------------------------
// Wind function by Dave Hoskins https://www.shadertoy.com/view/4ssXW2


float hash( float n ) {
    return fract(sin(n)*43758.5453123);
}
vec2 Hash( vec2 p) {
    return vec2( hash(p.x), hash(p.y) );
}

//--------------------------------------------------------------------------
vec2 Noise( in vec2 x ) {
    vec2 p = floor(x);
    vec2 f = fract(x);
    f = f*f*(3.0-2.0*f);
    vec2 res = mix(mix( Hash(p + 0.0), Hash(p + vec2(1.0, 0.0)),f.x),
                   mix( Hash(p + vec2(0.0, 1.0) ), Hash(p + vec2(1.0, 1.0)),f.x),f.y);
    return res-.5;
}

//--------------------------------------------------------------------------
vec2 FBM( vec2 p ) {
    vec2 f;
	f  = 0.5000	 * Noise(p); p = p * 2.32;
	f += 0.2500  * Noise(p); p = p * 2.23;
	f += 0.1250  * Noise(p); p = p * 2.31;
    f += 0.0625  * Noise(p); p = p * 2.28;
    f += 0.03125 * Noise(p);
    return f;
}

//--------------------------------------------------------------------------
vec2 Wind(float n) {
    vec2 pos = vec2(n * (162.017331), n * (132.066927));
    vec2 vol = Noise(vec2(n*23.131, -n*42.13254))*1.0 + 1.0;
    
    vec2 noise = vec2(FBM(pos*33.313))* vol.x *.5 + vec2(FBM(pos*4.519)) * vol.y;
    
	return noise;
}

//----------------------------------------------------------------------



vec2 mainSound( in int samp,float time) {
    //16 - 38
 //   time -= 7.5;
    time *= .7;
    float vol = 1.-smoothstep(6.,8.5, time);
    vol += smoothstep(16.5,20., time);
    vol *= 1.-smoothstep(23.5,25.5, time);
    vol += smoothstep(47.5,51.5, time);
    vol = vol*.8+.2;
    
	return Wind(time*.05) * vol;
}

### User Input

/*
 * "Seascape" by Alexander Alekseev aka TDM - 2014
 * License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
 * Contact: tdmaav@gmail.com
 */

const int NUM_STEPS = 32;
const float PI	 	= 3.141592;
const float EPSILON	= 1e-3;
#define EPSILON_NRM (0.1 / iResolution.x)
//#define AA

// sea
const int ITER_GEOMETRY = 3;
const int ITER_FRAGMENT = 5;
const float SEA_HEIGHT = 0.6;
const float SEA_CHOPPY = 4.0;
const float SEA_SPEED = 0.8;
const float SEA_FREQ = 0.16;
const vec3 SEA_BASE = vec3(0.0,0.09,0.18);
const vec3 SEA_WATER_COLOR = vec3(0.8,0.9,0.6)*0.6;
#define SEA_TIME (1.0 + iTime * SEA_SPEED)
const mat2 octave_m = mat2(1.6,1.2,-1.2,1.6);

// math
mat3 fromEuler(vec3 ang) {
	vec2 a1 = vec2(sin(ang.x),cos(ang.x));
    vec2 a2 = vec2(sin(ang.y),cos(ang.y));
    vec2 a3 = vec2(sin(ang.z),cos(ang.z));
    mat3 m;
    m[0] = vec3(a1.y*a3.y+a1.x*a2.x*a3.x,a1.y*a2.x*a3.x+a3.y*a1.x,-a2.y*a3.x);
	m[1] = vec3(-a2.y*a1.x,a1.y*a2.y,a2.x);
	m[2] = vec3(a3.y*a1.x*a2.x+a1.y*a3.x,a1.x*a3.x-a1.y*a3.y*a2.x,a2.y*a3.y);
	return m;
}
float hash( vec2 p ) {
	float h = dot(p,vec2(127.1,311.7));	
    return fract(sin(h)*43758.5453123);
}
float noise( in vec2 p ) {
    vec2 i = floor( p );
    vec2 f = fract( p );	
	vec2 u = f*f*(3.0-2.0*f);
    return -1.0+2.0*mix( mix( hash( i + vec2(0.0,0.0) ), 
                     hash( i + vec2(1.0,0.0) ), u.x),
                mix( hash( i + vec2(0.0,1.0) ), 
                     hash( i + vec2(1.0,1.0) ), u.x), u.y);
}

// lighting
float diffuse(vec3 n,vec3 l,float p) {
    return pow(dot(n,l) * 0.4 + 0.6,p);
}
float specular(vec3 n,vec3 l,vec3 e,float s) {    
    float nrm = (s + 8.0) / (PI * 8.0);
    return pow(max(dot(reflect(e,n),l),0.0),s) * nrm;
}

// sky
vec3 getSkyColor(vec3 e) {
    e.y = (max(e.y,0.0)*0.8+0.2)*0.8;
    return vec3(pow(1.0-e.y,2.0), 1.0-e.y, 0.6+(1.0-e.y)*0.4) * 1.1;
}

// sea
float sea_octave(vec2 uv, float choppy) {
    uv += noise(uv);        
    vec2 wv = 1.0-abs(sin(uv));
    vec2 swv = abs(cos(uv));    
    wv = mix(wv,swv,wv);
    return pow(1.0-pow(wv.x * wv.y,0.65),choppy);
}

float map(vec3 p) {
    float freq = SEA_FREQ;
    float amp = SEA_HEIGHT;
    float choppy = SEA_CHOPPY;
    vec2 uv = p.xz; uv.x *= 0.75;
    
    float d, h = 0.0;    
    for(int i = 0; i < ITER_GEOMETRY; i++) {        
    	d = sea_octave((uv+SEA_TIME)*freq,choppy);
    	d += sea_octave((uv-SEA_TIME)*freq,choppy);
        h += d * amp;        
    	uv *= octave_m; freq *= 1.9; amp *= 0.22;
        choppy = mix(choppy,1.0,0.2);
    }
    return p.y - h;
}

float map_detailed(vec3 p) {
    float freq = SEA_FREQ;
    float amp = SEA_HEIGHT;
    float choppy = SEA_CHOPPY;
    vec2 uv = p.xz; uv.x *= 0.75;
    
    float d, h = 0.0;    
    for(int i = 0; i < ITER_FRAGMENT; i++) {        
    	d = sea_octave((uv+SEA_TIME)*freq,choppy);
    	d += sea_octave((uv-SEA_TIME)*freq,choppy);
        h += d * amp;        
    	uv *= octave_m; freq *= 1.9; amp *= 0.22;
        choppy = mix(choppy,1.0,0.2);
    }
    return p.y - h;
}

vec3 getSeaColor(vec3 p, vec3 n, vec3 l, vec3 eye, vec3 dist) {  
    float fresnel = clamp(1.0 - dot(n, -eye), 0.0, 1.0);
    fresnel = min(fresnel * fresnel * fresnel, 0.5);
    
    vec3 reflected = getSkyColor(reflect(eye, n));    
    vec3 refracted = SEA_BASE + diffuse(n, l, 80.0) * SEA_WATER_COLOR * 0.12; 
    
    vec3 color = mix(refracted, reflected, fresnel);
    
    float atten = max(1.0 - dot(dist, dist) * 0.001, 0.0);
    color += SEA_WATER_COLOR * (p.y - SEA_HEIGHT) * 0.18 * atten;
    
    color += specular(n, l, eye, 600.0 * inversesqrt(dot(dist,dist)));
    
    return color;
}

// tracing
vec3 getNormal(vec3 p, float eps) {
    vec3 n;
    n.y = map_detailed(p);    
    n.x = map_detailed(vec3(p.x+eps,p.y,p.z)) - n.y;
    n.z = map_detailed(vec3(p.x,p.y,p.z+eps)) - n.y;
    n.y = eps;
    return normalize(n);
}

float heightMapTracing(vec3 ori, vec3 dir, out vec3 p) {  
    float tm = 0.0;
    float tx = 1000.0;    
    float hx = map(ori + dir * tx);
    if(hx > 0.0) {
        p = ori + dir * tx;
        return tx;   
    }
    float hm = map(ori);    
    for(int i = 0; i < NUM_STEPS; i++) {
        float tmid = mix(tm, tx, hm / (hm - hx));
        p = ori + dir * tmid;
        float hmid = map(p);        
        if(hmid < 0.0) {
            tx = tmid;
            hx = hmid;
        } else {
            tm = tmid;
            hm = hmid;
        }        
        if(abs(hmid) < EPSILON) break;
    }
    return mix(tm, tx, hm / (hm - hx));
}

vec3 getPixel(in vec2 coord, float time) {    
    vec2 uv = coord / iResolution.xy;
    uv = uv * 2.0 - 1.0;
    uv.x *= iResolution.x / iResolution.y;    
        
    // ray
    vec3 ang = vec3(sin(time*3.0)*0.1,sin(time)*0.2+0.3,time);    
    vec3 ori = vec3(0.0,3.5,time*5.0);
    vec3 dir = normalize(vec3(uv.xy,-2.0)); dir.z += length(uv) * 0.14;
    dir = normalize(dir) * fromEuler(ang);
    
    // tracing
    vec3 p;
    heightMapTracing(ori,dir,p);
    vec3 dist = p - ori;
    vec3 n = getNormal(p, dot(dist,dist) * EPSILON_NRM);
    vec3 light = normalize(vec3(0.0,1.0,0.8)); 
             
    // color
    return mix(
        getSkyColor(dir),
        getSeaColor(p,n,light,dir,dist),
    	pow(smoothstep(0.0,-0.02,dir.y),0.2));
}

// main
void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
    float time = iTime * 0.3 + iMouse.x*0.01;
	
#ifdef AA
    vec3 color = vec3(0.0);
    for(int i = -1; i <= 1; i++) {
        for(int j = -1; j <= 1; j++) {
        	vec2 uv = fragCoord+vec2(i,j)/3.0;
    		color += getPixel(uv, time);
        }
    }
    color /= 9.0;
#else
    vec3 color = getPixel(fragCoord, time);
#endif
    
    // post
	fragColor = vec4(pow(color,vec3(0.65)), 1.0);
}

### User Input

// http://www.pouet.net/prod.php?which=57245
// If you intend to reuse this shader, please add credits to 'Danilo Guanabara'

#define t iTime
#define r iResolution.xy

void mainImage( out vec4 fragColor, in vec2 fragCoord ){
	vec3 c;
	float l,z=t;
	for(int i=0;i<3;i++) {
		vec2 uv,p=fragCoord.xy/r;
		uv=p;
		p-=.5;
		p.x*=r.x/r.y;
		z+=.07;
		l=length(p);
		uv+=p/l*(sin(z)+1.)*abs(sin(l*9.-z-z));
		c[i]=.01/length(mod(uv,1.)-.5);
	}
	fragColor=vec4(c/l,t);
}

### User Input

// Created by evilryu
// License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.


// whether turn on the animation
//#define phase_shift_on 

float stime, ctime;
 void ry(inout vec3 p, float a){  
 	float c,s;vec3 q=p;  
  	c = cos(a); s = sin(a);  
  	p.x = c * q.x + s * q.z;  
  	p.z = -s * q.x + c * q.z; 
 }  

float pixel_size = 0.0;

/* 

z = r*(sin(theta)cos(phi) + i cos(theta) + j sin(theta)sin(phi)

zn+1 = zn^8 +c

z^8 = r^8 * (sin(8*theta)*cos(8*phi) + i cos(8*theta) + j sin(8*theta)*sin(8*theta)

zn+1' = 8 * zn^7 * zn' + 1

*/

vec3 mb(vec3 p) {
	p.xyz = p.xzy;
	vec3 z = p;
	vec3 dz=vec3(0.0);
	float power = 8.0;
	float r, theta, phi;
	float dr = 1.0;
	
	float t0 = 1.0;
	for(int i = 0; i < 7; ++i) {
		r = length(z);
		if(r > 2.0) continue;
		theta = atan(z.y / z.x);
        #ifdef phase_shift_on
		phi = asin(z.z / r) + iTime*0.1;
        #else
        phi = asin(z.z / r);
        #endif
		
		dr = pow(r, power - 1.0) * dr * power + 1.0;
	
		r = pow(r, power);
		theta = theta * power;
		phi = phi * power;
		
		z = r * vec3(cos(theta)*cos(phi), sin(theta)*cos(phi), sin(phi)) + p;
		
		t0 = min(t0, r);
	}
	return vec3(0.5 * log(r) * r / dr, t0, 0.0);
}

 vec3 f(vec3 p){ 
	 ry(p, iTime*0.2);
     return mb(p); 
 } 


 float softshadow(vec3 ro, vec3 rd, float k ){ 
     float akuma=1.0,h=0.0; 
	 float t = 0.01;
     for(int i=0; i < 50; ++i){ 
         h=f(ro+rd*t).x; 
         if(h<0.001)return 0.02; 
         akuma=min(akuma, k*h/t); 
 		 t+=clamp(h,0.01,2.0); 
     } 
     return akuma; 
 } 

vec3 nor( in vec3 pos )
{
    vec3 eps = vec3(0.001,0.0,0.0);
	return normalize( vec3(
           f(pos+eps.xyy).x - f(pos-eps.xyy).x,
           f(pos+eps.yxy).x - f(pos-eps.yxy).x,
           f(pos+eps.yyx).x - f(pos-eps.yyx).x ) );
}

vec3 intersect( in vec3 ro, in vec3 rd )
{
    float t = 1.0;
    float res_t = 0.0;
    float res_d = 1000.0;
    vec3 c, res_c;
    float max_error = 1000.0;
	float d = 1.0;
    float pd = 100.0;
    float os = 0.0;
    float step = 0.0;
    float error = 1000.0;
    
    for( int i=0; i<48; i++ )
    {
        if( error < pixel_size*0.5 || t > 20.0 )
        {
        }
        else{  // avoid broken shader on windows
        
            c = f(ro + rd*t);
            d = c.x;

            if(d > os)
            {
                os = 0.4 * d*d/pd;
                step = d + os;
                pd = d;
            }
            else
            {
                step =-os; os = 0.0; pd = 100.0; d = 1.0;
            }

            error = d / t;

            if(error < max_error) 
            {
                max_error = error;
                res_t = t;
                res_c = c;
            }
        
            t += step;
        }

    }
	if( t>20.0/* || max_error > pixel_size*/ ) res_t=-1.0;
    return vec3(res_t, res_c.y, res_c.z);
}

 void mainImage( out vec4 fragColor, in vec2 fragCoord ) 
 { 
    vec2 q=fragCoord.xy/iResolution.xy; 
 	vec2 uv = -1.0 + 2.0*q; 
 	uv.x*=iResolution.x/iResolution.y; 
     
    pixel_size = 1.0/(iResolution.x * 3.0);
	// camera
 	stime=0.7+0.3*sin(iTime*0.4); 
 	ctime=0.7+0.3*cos(iTime*0.4); 

 	vec3 ta=vec3(0.0,0.0,0.0); 
	vec3 ro = vec3(0.0, 3.*stime*ctime, 3.*(1.-stime*ctime));

 	vec3 cf = normalize(ta-ro); 
    vec3 cs = normalize(cross(cf,vec3(0.0,1.0,0.0))); 
    vec3 cu = normalize(cross(cs,cf)); 
 	vec3 rd = normalize(uv.x*cs + uv.y*cu + 3.0*cf);  // transform from view to world

    vec3 sundir = normalize(vec3(0.1, 0.8, 0.6)); 
    vec3 sun = vec3(1.64, 1.27, 0.99); 
    vec3 skycolor = vec3(0.6, 1.5, 1.0); 

	vec3 bg = exp(uv.y-2.0)*vec3(0.4, 1.6, 1.0);

    float halo=clamp(dot(normalize(vec3(-ro.x, -ro.y, -ro.z)), rd), 0.0, 1.0); 
    vec3 col=bg+vec3(1.0,0.8,0.4)*pow(halo,17.0); 


    float t=0.0;
    vec3 p=ro; 
	 
	vec3 res = intersect(ro, rd);
	 if(res.x > 0.0){
		   p = ro + res.x * rd;
           vec3 n=nor(p); 
           float shadow = softshadow(p, sundir, 10.0 );

           float dif = max(0.0, dot(n, sundir)); 
           float sky = 0.6 + 0.4 * max(0.0, dot(n, vec3(0.0, 1.0, 0.0))); 
 		   float bac = max(0.3 + 0.7 * dot(vec3(-sundir.x, -1.0, -sundir.z), n), 0.0); 
           float spe = max(0.0, pow(clamp(dot(sundir, reflect(rd, n)), 0.0, 1.0), 10.0)); 

           vec3 lin = 4.5 * sun * dif * shadow; 
           lin += 0.8 * bac * sun; 
           lin += 0.6 * sky * skycolor*shadow; 
           lin += 3.0 * spe * shadow; 

		   res.y = pow(clamp(res.y, 0.0, 1.0), 0.55);
		   vec3 tc0 = 0.5 + 0.5 * sin(3.0 + 4.2 * res.y + vec3(0.0, 0.5, 1.0));
           col = lin *vec3(0.9, 0.8, 0.6) *  0.2 * tc0;
 		   col=mix(col,bg, 1.0-exp(-0.001*res.x*res.x)); 
    } 

    // post
    col=pow(clamp(col,0.0,1.0),vec3(0.45)); 
    col=col*0.6+0.4*col*col*(3.0-2.0*col);  // contrast
    col=mix(col, vec3(dot(col, vec3(0.33))), -0.5);  // satuation
    col*=0.5+0.5*pow(16.0*q.x*q.y*(1.0-q.x)*(1.0-q.y),0.7);  // vigneting
 	fragColor = vec4(col.xyz, smoothstep(0.55, .76, 1.-res.x/5.)); 
 }

### User Input

precision highp float;


mat2 rot(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c,s,-s,c);
}

const float pi = acos(-1.0);
const float pi2 = pi*2.0;

vec2 pmod(vec2 p, float r) {
    float a = atan(p.x, p.y) + pi/r;
    float n = pi2 / r;
    a = floor(a/n)*n;
    return p*rot(-a);
}

float box( vec3 p, vec3 b ) {
    vec3 d = abs(p) - b;
    return min(max(d.x,max(d.y,d.z)),0.0) + length(max(d,0.0));
}

float ifsBox(vec3 p) {
    for (int i=0; i<5; i++) {
        p = abs(p) - 1.0;
        p.xy *= rot(iTime*0.3);
        p.xz *= rot(iTime*0.1);
    }
    p.xz *= rot(iTime);
    return box(p, vec3(0.4,0.8,0.3));
}

float map(vec3 p, vec3 cPos) {
    vec3 p1 = p;
    p1.x = mod(p1.x-5., 10.) - 5.;
    p1.y = mod(p1.y-5., 10.) - 5.;
    p1.z = mod(p1.z, 16.)-8.;
    p1.xy = pmod(p1.xy, 5.0);
    return ifsBox(p1);
}

void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
    vec2 p = (fragCoord.xy * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);

    vec3 cPos = vec3(0.0,0.0, -3.0 * iTime);
    // vec3 cPos = vec3(0.3*sin(iTime*0.8), 0.4*cos(iTime*0.3), -6.0 * iTime);
    vec3 cDir = normalize(vec3(0.0, 0.0, -1.0));
    vec3 cUp  = vec3(sin(iTime), 1.0, 0.0);
    vec3 cSide = cross(cDir, cUp);

    vec3 ray = normalize(cSide * p.x + cUp * p.y + cDir);

    // Phantom Mode https://www.shadertoy.com/view/MtScWW by aiekick
    float acc = 0.0;
    float acc2 = 0.0;
    float t = 0.0;
    for (int i = 0; i < 99; i++) {
        vec3 pos = cPos + ray * t;
        float dist = map(pos, cPos);
        dist = max(abs(dist), 0.02);
        float a = exp(-dist*3.0);
        if (mod(length(pos)+24.0*iTime, 30.0) < 3.0) {
            a *= 2.0;
            acc2 += a;
        }
        acc += a;
        t += dist * 0.5;
    }

    vec3 col = vec3(acc * 0.01, acc * 0.011 + acc2*0.002, acc * 0.012+ acc2*0.005);
    fragColor = vec4(col, 1.0 - t * 0.03);
}

### User Input

// Protean clouds by nimitz (twitter: @stormoid)
// https://www.shadertoy.com/view/3l23Rh
// License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License
// Contact the author for other licensing options

/*
	Technical details:

	The main volume noise is generated from a deformed periodic grid, which can produce
	a large range of noise-like patterns at very cheap evalutation cost. Allowing for multiple
	fetches of volume gradient computation for improved lighting.

	To further accelerate marching, since the volume is smooth, more than half the the density
	information isn't used to rendering or shading but only as an underlying volume	distance to 
	determine dynamic step size, by carefully selecting an equation	(polynomial for speed) to 
	step as a function of overall density (not necessarily rendered) the visual results can be 
	the	same as a naive implementation with ~40% increase in rendering performance.

	Since the dynamic marching step size is even less uniform due to steps not being rendered at all
	the fog is evaluated as the difference of the fog integral at each rendered step.

*/

mat2 rot(in float a){float c = cos(a), s = sin(a);return mat2(c,s,-s,c);}
const mat3 m3 = mat3(0.33338, 0.56034, -0.71817, -0.87887, 0.32651, -0.15323, 0.15162, 0.69596, 0.61339)*1.93;
float mag2(vec2 p){return dot(p,p);}
float linstep(in float mn, in float mx, in float x){ return clamp((x - mn)/(mx - mn), 0., 1.); }
float prm1 = 0.;
vec2 bsMo = vec2(0);

vec2 disp(float t){ return vec2(sin(t*0.22)*1., cos(t*0.175)*1.)*2.; }

vec2 map(vec3 p)
{
    vec3 p2 = p;
    p2.xy -= disp(p.z).xy;
    p.xy *= rot(sin(p.z+iTime)*(0.1 + prm1*0.05) + iTime*0.09);
    float cl = mag2(p2.xy);
    float d = 0.;
    p *= .61;
    float z = 1.;
    float trk = 1.;
    float dspAmp = 0.1 + prm1*0.2;
    for(int i = 0; i < 5; i++)
    {
		p += sin(p.zxy*0.75*trk + iTime*trk*.8)*dspAmp;
        d -= abs(dot(cos(p), sin(p.yzx))*z);
        z *= 0.57;
        trk *= 1.4;
        p = p*m3;
    }
    d = abs(d + prm1*3.)+ prm1*.3 - 2.5 + bsMo.y;
    return vec2(d + cl*.2 + 0.25, cl);
}

vec4 render( in vec3 ro, in vec3 rd, float time )
{
	vec4 rez = vec4(0);
    const float ldst = 8.;
	vec3 lpos = vec3(disp(time + ldst)*0.5, time + ldst);
	float t = 1.5;
	float fogT = 0.;
	for(int i=0; i<130; i++)
	{
		if(rez.a > 0.99)break;

		vec3 pos = ro + t*rd;
        vec2 mpv = map(pos);
		float den = clamp(mpv.x-0.3,0.,1.)*1.12;
		float dn = clamp((mpv.x + 2.),0.,3.);
        
		vec4 col = vec4(0);
        if (mpv.x > 0.6)
        {
        
            col = vec4(sin(vec3(5.,0.4,0.2) + mpv.y*0.1 +sin(pos.z*0.4)*0.5 + 1.8)*0.5 + 0.5,0.08);
            col *= den*den*den;
			col.rgb *= linstep(4.,-2.5, mpv.x)*2.3;
            float dif =  clamp((den - map(pos+.8).x)/9., 0.001, 1. );
            dif += clamp((den - map(pos+.35).x)/2.5, 0.001, 1. );
            col.xyz *= den*(vec3(0.005,.045,.075) + 1.5*vec3(0.033,0.07,0.03)*dif);
        }
		
		float fogC = exp(t*0.2 - 2.2);
		col.rgba += vec4(0.06,0.11,0.11, 0.1)*clamp(fogC-fogT, 0., 1.);
		fogT = fogC;
		rez = rez + col*(1. - rez.a);
		t += clamp(0.5 - dn*dn*.05, 0.09, 0.3);
	}
	return clamp(rez, 0.0, 1.0);
}

float getsat(vec3 c)
{
    float mi = min(min(c.x, c.y), c.z);
    float ma = max(max(c.x, c.y), c.z);
    return (ma - mi)/(ma+ 1e-7);
}

//from my "Will it blend" shader (https://www.shadertoy.com/view/lsdGzN)
vec3 iLerp(in vec3 a, in vec3 b, in float x)
{
    vec3 ic = mix(a, b, x) + vec3(1e-6,0.,0.);
    float sd = abs(getsat(ic) - mix(getsat(a), getsat(b), x));
    vec3 dir = normalize(vec3(2.*ic.x - ic.y - ic.z, 2.*ic.y - ic.x - ic.z, 2.*ic.z - ic.y - ic.x));
    float lgt = dot(vec3(1.0), ic);
    float ff = dot(dir, normalize(ic));
    ic += 1.5*dir*sd*ff*lgt;
    return clamp(ic,0.,1.);
}

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{	
	vec2 q = fragCoord.xy/iResolution.xy;
    vec2 p = (gl_FragCoord.xy - 0.5*iResolution.xy)/iResolution.y;
    bsMo = (iMouse.xy - 0.5*iResolution.xy)/iResolution.y;
    
    float time = iTime*3.;
    vec3 ro = vec3(0,0,time);
    
    ro += vec3(sin(iTime)*0.5,sin(iTime*1.)*0.,0);
        
    float dspAmp = .85;
    ro.xy += disp(ro.z)*dspAmp;
    float tgtDst = 3.5;
    
    vec3 target = normalize(ro - vec3(disp(time + tgtDst)*dspAmp, time + tgtDst));
    ro.x -= bsMo.x*2.;
    vec3 rightdir = normalize(cross(target, vec3(0,1,0)));
    vec3 updir = normalize(cross(rightdir, target));
    rightdir = normalize(cross(updir, target));
	vec3 rd=normalize((p.x*rightdir + p.y*updir)*1. - target);
    rd.xy *= rot(-disp(time + 3.5).x*0.2 + bsMo.x);
    prm1 = smoothstep(-0.4, 0.4,sin(iTime*0.3));
	vec4 scn = render(ro, rd, time);
		
    vec3 col = scn.rgb;
    col = iLerp(col.bgr, col.rgb, clamp(1.-prm1,0.05,1.));
    
    col = pow(col, vec3(.55,0.65,0.6))*vec3(1.,.97,.9);

    col *= pow( 16.0*q.x*q.y*(1.0-q.x)*(1.0-q.y), 0.12)*0.7+0.3; //Vign
    
	fragColor = vec4( col, 1.0 );
}

### User Input

//CBS
//Parallax scrolling fractal galaxy.
//Inspired by JoshP's Simplicity shader: https://www.shadertoy.com/view/lslGWr

// http://www.fractalforums.com/new-theories-and-research/very-simple-formula-for-fractal-patterns/
float field(in vec3 p,float s) {
	float strength = 7. + .03 * log(1.e-6 + fract(sin(iTime) * 4373.11));
	float accum = s/4.;
	float prev = 0.;
	float tw = 0.;
	for (int i = 0; i < 26; ++i) {
		float mag = dot(p, p);
		p = abs(p) / mag + vec3(-.5, -.4, -1.5);
		float w = exp(-float(i) / 7.);
		accum += w * exp(-strength * pow(abs(mag - prev), 2.2));
		tw += w;
		prev = mag;
	}
	return max(0., 5. * accum / tw - .7);
}

// Less iterations for second layer
float field2(in vec3 p, float s) {
	float strength = 7. + .03 * log(1.e-6 + fract(sin(iTime) * 4373.11));
	float accum = s/4.;
	float prev = 0.;
	float tw = 0.;
	for (int i = 0; i < 18; ++i) {
		float mag = dot(p, p);
		p = abs(p) / mag + vec3(-.5, -.4, -1.5);
		float w = exp(-float(i) / 7.);
		accum += w * exp(-strength * pow(abs(mag - prev), 2.2));
		tw += w;
		prev = mag;
	}
	return max(0., 5. * accum / tw - .7);
}

vec3 nrand3( vec2 co )
{
	vec3 a = fract( cos( co.x*8.3e-3 + co.y )*vec3(1.3e5, 4.7e5, 2.9e5) );
	vec3 b = fract( sin( co.x*0.3e-3 + co.y )*vec3(8.1e5, 1.0e5, 0.1e5) );
	vec3 c = mix(a, b, 0.5);
	return c;
}


void mainImage( out vec4 fragColor, in vec2 fragCoord ) {
    vec2 uv = 2. * fragCoord.xy / iResolution.xy - 1.;
	vec2 uvs = uv * iResolution.xy / max(iResolution.x, iResolution.y);
	vec3 p = vec3(uvs / 4., 0) + vec3(1., -1.3, 0.);
	p += .2 * vec3(sin(iTime / 16.), sin(iTime / 12.),  sin(iTime / 128.));
	
	float freqs[4];
	//Sound
	freqs[0] = texture( iChannel0, vec2( 0.01, 0.25 ) ).x;
	freqs[1] = texture( iChannel0, vec2( 0.07, 0.25 ) ).x;
	freqs[2] = texture( iChannel0, vec2( 0.15, 0.25 ) ).x;
	freqs[3] = texture( iChannel0, vec2( 0.30, 0.25 ) ).x;

	float t = field(p,freqs[2]);
	float v = (1. - exp((abs(uv.x) - 1.) * 6.)) * (1. - exp((abs(uv.y) - 1.) * 6.));
	
    //Second Layer
	vec3 p2 = vec3(uvs / (4.+sin(iTime*0.11)*0.2+0.2+sin(iTime*0.15)*0.3+0.4), 1.5) + vec3(2., -1.3, -1.);
	p2 += 0.25 * vec3(sin(iTime / 16.), sin(iTime / 12.),  sin(iTime / 128.));
	float t2 = field2(p2,freqs[3]);
	vec4 c2 = mix(.4, 1., v) * vec4(1.3 * t2 * t2 * t2 ,1.8  * t2 * t2 , t2* freqs[0], t2);
	
	
	//Let's add some stars
	//Thanks to http://glsl.heroku.com/e#6904.0
	vec2 seed = p.xy * 2.0;	
	seed = floor(seed * iResolution.x);
	vec3 rnd = nrand3( seed );
	vec4 starcolor = vec4(pow(rnd.y,40.0));
	
	//Second Layer
	vec2 seed2 = p2.xy * 2.0;
	seed2 = floor(seed2 * iResolution.x);
	vec3 rnd2 = nrand3( seed2 );
	starcolor += vec4(pow(rnd2.y,40.0));
	
	fragColor = mix(freqs[3]-.3, 1., v) * vec4(1.5*freqs[2] * t * t* t , 1.2*freqs[1] * t * t, freqs[3]*t, 1.0)+c2+starcolor;
}

### User Input

// Auroras by nimitz 2017 (twitter: @stormoid)
// License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License
// Contact the author for other licensing options

/*
	
	There are two main hurdles I encountered rendering this effect. 
	First, the nature of the texture that needs to be generated to get a believable effect
	needs to be very specific, with large scale band-like structures, small scale non-smooth variations
	to create the trail-like effect, a method for animating said texture smoothly and finally doing all
	of this cheaply enough to be able to evaluate it several times per fragment/pixel.

	The second obstacle is the need to render a large volume while keeping the computational cost low.
	Since the effect requires the trails to extend way up in the atmosphere to look good, this means
	that the evaluated volume cannot be as constrained as with cloud effects. My solution was to make
	the sample stride increase polynomially, which works very well as long as the trails are lower opcaity than
	the rest of the effect. Which is always the case for auroras.

	After that, there were some issues with getting the correct emission curves and removing banding at lowered
	sample densities, this was fixed by a combination of sample number influenced dithering and slight sample blending.

	N.B. the base setup is from an old shader and ideally the effect would take an arbitrary ray origin and
	direction. But this was not required for this demo and would be trivial to fix.
*/

#define time iTime

mat2 mm2(in float a){float c = cos(a), s = sin(a);return mat2(c,s,-s,c);}
mat2 m2 = mat2(0.95534, 0.29552, -0.29552, 0.95534);
float tri(in float x){return clamp(abs(fract(x)-.5),0.01,0.49);}
vec2 tri2(in vec2 p){return vec2(tri(p.x)+tri(p.y),tri(p.y+tri(p.x)));}

float triNoise2d(in vec2 p, float spd)
{
    float z=1.8;
    float z2=2.5;
	float rz = 0.;
    p *= mm2(p.x*0.06);
    vec2 bp = p;
	for (float i=0.; i<5.; i++ )
	{
        vec2 dg = tri2(bp*1.85)*.75;
        dg *= mm2(time*spd);
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
    
    for(float i=0.;i<50.;i++)
    {
        float of = 0.006*hash21(gl_FragCoord.xy)*smoothstep(0.,15., i);
        float pt = ((.8+pow(i,1.4)*.002)-ro.y)/(rd.y*2.+0.4);
        pt -= of;
    	vec3 bpos = ro + pt*rd;
        vec2 p = bpos.zx;
        float rzt = triNoise2d(p, 0.06);
        vec4 col2 = vec4(0,0,0, rzt);
        col2.rgb = (sin(1.-vec3(2.15,-.5, 1.2)+i*0.043)*0.5+0.5)*rzt;
        avgCol =  mix(avgCol, col2, .5);
        col += avgCol*exp2(-i*0.065 - 2.5)*smoothstep(0.,5., i);
        
    }
    
    col *= (clamp(rd.y*15.+.4,0.,1.));
    
    
    //return clamp(pow(col,vec4(1.3))*1.5,0.,1.);
    //return clamp(pow(col,vec4(1.7))*2.,0.,1.);
    //return clamp(pow(col,vec4(1.5))*2.5,0.,1.);
    //return clamp(pow(col,vec4(1.8))*1.5,0.,1.);
    
    //return smoothstep(0.,1.1,pow(col,vec4(1.))*1.5);
    return col*1.8;
    //return pow(col,vec4(1.))*2.
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
    vec2 mo = iMouse.xy / iResolution.xy-.5;
    mo = (mo==vec2(-.5))?mo=vec2(-0.1,0.1):mo;
	mo.x *= iResolution.x/iResolution.y;
    rd.yz *= mm2(mo.y);
    rd.xz *= mm2(mo.x + sin(time*0.05)*0.2);
    
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
        float nz2 = triNoise2d(pos.xz*vec2(.5,.7), 0.);
        col += mix(vec3(0.2,0.25,0.5)*0.08,vec3(0.3,0.3,0.5)*0.7, nz2*0.4);
    }
    
	fragColor = vec4(col, 1.);
}


### User Input

// Sirenian Dawn by nimitz (twitter: @stormoid)
// https://www.shadertoy.com/view/XsyGWV
// License Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License
// Contact the author for other licensing options

/*
	See: https://en.wikipedia.org/wiki/Terra_Sirenum

	Things of interest in this shader:
		-A technique I call "relaxation marching", see march() function
		-A buffer based technique for anti-alisaing
		-Cheap and smooth procedural starfield
		-Non-constant fog from iq
		-Completely faked atmosphere :)
		-Terrain based on noise derivatives
*/

/*
	More about the antialiasing:
		The fragments with high enough iteration count/distance ratio 
		get blended with the past frame, I tried a few different 
		input for the blend trigger: distance delta, color delta, 
		normal delta, scene curvature.  But none of them provides 
		good enough info about the problem areas to allow for proper
		antialiasing without making the whole scene blurry.
		
		On the other hand iteration count (modulated by a power
		of distance) does a pretty good job without requiring to
		store past frame info in the alpha channel (which can then
		be used for something else, nothing in this case)

*/

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
	fragColor = vec4(texture(iChannel0, fragCoord.xy/iResolution.xy).rgb, 1.0);
}

### User Input

// based on https://www.shadertoy.com/view/lsf3RH by
// trisomie21 (THANKS!)
// My apologies for the ugly code.

float snoise(vec3 uv, float res)	// by trisomie21
{
	const vec3 s = vec3(1e0, 1e2, 1e4);
	
	uv *= res;
	
	vec3 uv0 = floor(mod(uv, res))*s;
	vec3 uv1 = floor(mod(uv+vec3(1.), res))*s;
	
	vec3 f = fract(uv); f = f*f*(3.0-2.0*f);
	
	vec4 v = vec4(uv0.x+uv0.y+uv0.z, uv1.x+uv0.y+uv0.z,
		      	  uv0.x+uv1.y+uv0.z, uv1.x+uv1.y+uv0.z);
	
	vec4 r = fract(sin(v*1e-3)*1e5);
	float r0 = mix(mix(r.x, r.y, f.x), mix(r.z, r.w, f.x), f.y);
	
	r = fract(sin((v + uv1.z - uv0.z)*1e-3)*1e5);
	float r1 = mix(mix(r.x, r.y, f.x), mix(r.z, r.w, f.x), f.y);
	
	return mix(r0, r1, f.z)*2.-1.;
}

float freqs[4];

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
	freqs[0] = texture( iChannel1, vec2( 0.01, 0.25 ) ).x;
	freqs[1] = texture( iChannel1, vec2( 0.07, 0.25 ) ).x;
	freqs[2] = texture( iChannel1, vec2( 0.15, 0.25 ) ).x;
	freqs[3] = texture( iChannel1, vec2( 0.30, 0.25 ) ).x;

	float brightness	= freqs[1] * 0.25 + freqs[2] * 0.25;
	float radius		= 0.24 + brightness * 0.2;
	float invRadius 	= 1.0/radius;
	
	vec3 orange			= vec3( 0.8, 0.65, 0.3 );
	vec3 orangeRed		= vec3( 0.8, 0.35, 0.1 );
	float time		= iTime * 0.1;
	float aspect	= iResolution.x/iResolution.y;
	vec2 uv			= fragCoord.xy / iResolution.xy;
	vec2 p 			= -0.5 + uv;
	p.x *= aspect;

	float fade		= pow( length( 2.0 * p ), 0.5 );
	float fVal1		= 1.0 - fade;
	float fVal2		= 1.0 - fade;
	
	float angle		= atan( p.x, p.y )/6.2832;
	float dist		= length(p);
	vec3 coord		= vec3( angle, dist, time * 0.1 );
	
	float newTime1	= abs( snoise( coord + vec3( 0.0, -time * ( 0.35 + brightness * 0.001 ), time * 0.015 ), 15.0 ) );
	float newTime2	= abs( snoise( coord + vec3( 0.0, -time * ( 0.15 + brightness * 0.001 ), time * 0.015 ), 45.0 ) );	
	for( int i=1; i<=7; i++ ){
		float power = pow( 2.0, float(i + 1) );
		fVal1 += ( 0.5 / power ) * snoise( coord + vec3( 0.0, -time, time * 0.2 ), ( power * ( 10.0 ) * ( newTime1 + 1.0 ) ) );
		fVal2 += ( 0.5 / power ) * snoise( coord + vec3( 0.0, -time, time * 0.2 ), ( power * ( 25.0 ) * ( newTime2 + 1.0 ) ) );
	}
	
	float corona		= pow( fVal1 * max( 1.1 - fade, 0.0 ), 2.0 ) * 50.0;
	corona				+= pow( fVal2 * max( 1.1 - fade, 0.0 ), 2.0 ) * 50.0;
	corona				*= 1.2 - newTime1;
	vec3 sphereNormal 	= vec3( 0.0, 0.0, 1.0 );
	vec3 dir 			= vec3( 0.0 );
	vec3 center			= vec3( 0.5, 0.5, 1.0 );
	vec3 starSphere		= vec3( 0.0 );
	
	vec2 sp = -1.0 + 2.0 * uv;
	sp.x *= aspect;
	sp *= ( 2.0 - brightness );
  	float r = dot(sp,sp);
	float f = (1.0-sqrt(abs(1.0-r)))/(r) + brightness * 0.5;
	if( dist < radius ){
		corona			*= pow( dist * invRadius, 24.0 );
  		vec2 newUv;
 		newUv.x = sp.x*f;
  		newUv.y = sp.y*f;
		newUv += vec2( time, 0.0 );
		
		vec3 texSample 	= texture( iChannel0, newUv ).rgb;
		float uOff		= ( texSample.g * brightness * 4.5 + time );
		vec2 starUV		= newUv + vec2( uOff, 0.0 );
		starSphere		= texture( iChannel0, starUV ).rgb;
	}
	
	float starGlow	= min( max( 1.0 - dist * ( 1.0 - brightness ), 0.0 ), 1.0 );
	//fragColor.rgb	= vec3( r );
	fragColor.rgb	= vec3( f * ( 0.75 + brightness * 0.3 ) * orange ) + starSphere + corona * orange + starGlow * orangeRed;
	fragColor.a		= 1.0;
}



### User Input

review all of these shader and make sure they work with cedartoy. some require an image input. lets add that to the UI. 