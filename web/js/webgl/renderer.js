import { AudioTexture } from './audio-texture.js';

export class ShaderRenderer {
    constructor(canvas) {
        this.canvas = canvas;
        this.gl = canvas.getContext('webgl2');

        if (!this.gl) {
            throw new Error('WebGL2 not supported');
        }

        this.program = null;
        this.uniforms = {};
        this.startTime = Date.now();
        this.currentTime = 0;
        this.frameCount = 0;
        this.playing = false;
        this.audioTexture = new AudioTexture(this.gl);
        this.audioFFT = new Float32Array(512);
        this.audioWaveform = new Float32Array(512);

        // Camera controls (for CedarToy dome projection)
        this.cameraMode = 0; // 0=2D, 1=Equirect, 2=LL180
        this.cameraTilt = 0.0; // degrees
    }

    compileShader(source) {
        const gl = this.gl;

        // Vertex shader (fullscreen quad)
        const vertexShader = gl.createShader(gl.VERTEX_SHADER);
        gl.shaderSource(vertexShader, `#version 300 es
            in vec4 position;
            void main() {
                gl_Position = position;
            }
        `);
        gl.compileShader(vertexShader);

        // Fragment shader (user shader wrapped)
        const fragmentShaderSource = this.wrapShaderSource(source);
        const fragmentShader = gl.createShader(gl.FRAGMENT_SHADER);
        gl.shaderSource(fragmentShader, fragmentShaderSource);
        gl.compileShader(fragmentShader);

        // Check compilation
        if (!gl.getShaderParameter(fragmentShader, gl.COMPILE_STATUS)) {
            const error = gl.getShaderInfoLog(fragmentShader);
            console.error('Shader compilation error:', error);
            throw new Error(`Shader compilation failed: ${error}`);
        }

        // Link program
        this.program = gl.createProgram();
        gl.attachShader(this.program, vertexShader);
        gl.attachShader(this.program, fragmentShader);
        gl.linkProgram(this.program);

        if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
            const error = gl.getProgramInfoLog(this.program);
            throw new Error(`Program linking failed: ${error}`);
        }

        // Get uniform locations
        this.uniforms = {
            iResolution: gl.getUniformLocation(this.program, 'iResolution'),
            iTime: gl.getUniformLocation(this.program, 'iTime'),
            iTimeDelta: gl.getUniformLocation(this.program, 'iTimeDelta'),
            iFrame: gl.getUniformLocation(this.program, 'iFrame'),
            iMouse: gl.getUniformLocation(this.program, 'iMouse'),
            iDate: gl.getUniformLocation(this.program, 'iDate'),
            iSampleRate: gl.getUniformLocation(this.program, 'iSampleRate'),
            iChannel0: gl.getUniformLocation(this.program, 'iChannel0'),
            iChannel1: gl.getUniformLocation(this.program, 'iChannel1'),
            iChannel2: gl.getUniformLocation(this.program, 'iChannel2'),
            iChannel3: gl.getUniformLocation(this.program, 'iChannel3'),
            // CedarToy uniforms
            iCameraMode: gl.getUniformLocation(this.program, 'iCameraMode'),
            iCameraTiltDeg: gl.getUniformLocation(this.program, 'iCameraTiltDeg'),
            iJitter: gl.getUniformLocation(this.program, 'iJitter'),
            iSampleIndex: gl.getUniformLocation(this.program, 'iSampleIndex'),
        };

        // Get array uniform locations
        this.uniforms.iChannelTime = [];
        this.uniforms.iChannelResolution = [];
        for (let i = 0; i < 4; i++) {
            this.uniforms.iChannelTime[i] = gl.getUniformLocation(this.program, `iChannelTime[${i}]`);
            this.uniforms.iChannelResolution[i] = gl.getUniformLocation(this.program, `iChannelResolution[${i}]`);
        }

        // Create fullscreen quad
        this.createQuad();
    }

    wrapShaderSource(userSource) {
        // Strip any existing #version directive (we'll add our own)
        let cleanSource = userSource.replace(/^\s*#version\s+\d+\s+es\s*/m, '');

        // Strip our standard uniform declarations if they exist
        cleanSource = cleanSource.replace(/uniform\s+vec3\s+iResolution\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iTime\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iTimeDelta\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+int\s+iFrame\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+vec4\s+iMouse\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+vec4\s+iDate\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iSampleRate\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+sampler2D\s+iChannel0\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+sampler2D\s+iChannel1\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+sampler2D\s+iChannel2\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+sampler2D\s+iChannel3\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iChannelTime\s*\[\s*4\s*\]\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+vec3\s+iChannelResolution\s*\[\s*4\s*\]\s*;/g, '');

        // Strip fragColor output if it exists
        cleanSource = cleanSource.replace(/out\s+vec4\s+fragColor\s*;/g, '');

        // Check if shader has its own main function
        const hasMain = /void\s+main\s*\(\s*\)/.test(cleanSource);

        // Build final shader
        let finalShader = '#version 300 es\n';
        finalShader += 'precision highp float;\n\n';
        finalShader += '// Shadertoy standard uniforms\n';
        finalShader += 'uniform vec3 iResolution;\n';
        finalShader += 'uniform float iTime;\n';
        finalShader += 'uniform float iTimeDelta;\n';
        finalShader += 'uniform int iFrame;\n';
        finalShader += 'uniform vec4 iMouse;\n';
        finalShader += 'uniform vec4 iDate;\n';
        finalShader += 'uniform float iSampleRate;\n';
        finalShader += 'uniform sampler2D iChannel0;\n';
        finalShader += 'uniform sampler2D iChannel1;\n';
        finalShader += 'uniform sampler2D iChannel2;\n';
        finalShader += 'uniform sampler2D iChannel3;\n';
        finalShader += 'uniform float iChannelTime[4];\n';
        finalShader += 'uniform vec3 iChannelResolution[4];\n';
        finalShader += '// CedarToy uniforms\n';
        finalShader += 'uniform int iCameraMode;\n';
        finalShader += 'uniform float iCameraTiltDeg;\n';
        finalShader += 'uniform vec2 iJitter;\n';
        finalShader += 'uniform int iSampleIndex;\n\n';
        finalShader += 'out vec4 fragColor;\n\n';

        // Add CedarToy camera helper functions
        finalShader += `
// CedarToy Camera Constants and Helpers
const float PI = 3.141592653589793238;
const float HALFPI = 1.570796326794896619;

// Build camera basis from direction and up vectors
mat3 buildCameraBasis(vec3 camDir, vec3 camUp) {
    vec3 f = normalize(camDir);
    vec3 r = normalize(cross(camUp, f));
    vec3 u = cross(f, r);
    return mat3(r, u, f);
}

// Equirectangular projection (360x180 degree)
vec3 cameraDirEquirect(vec2 uv, mat3 camBasis) {
    // Map UV to longitude/latitude
    float lon = (uv.x * 2.0 - 1.0) * PI;      // -180 to +180 degrees
    float lat = (uv.y * 2.0 - 1.0) * HALFPI;  // -90 to +90 degrees

    // Convert to 3D direction (spherical coordinates)
    vec3 sphereDir;
    sphereDir.x = cos(lat) * sin(lon);
    sphereDir.y = sin(lat);
    sphereDir.z = cos(lat) * cos(lon);

    // Transform to world space
    return normalize(camBasis * sphereDir);
}

// LL180 dome projection (latitude-longitude 180-degree)
// Uses proper spherical coordinate mapping with latitude offset for horizon tilt
// This creates the curved horizon distortion effect
vec3 cameraDirLL180(vec2 uv, float tiltDeg, mat3 camBasis) {
    // Convert UV to centered coordinates [-1, 1]
    vec2 centered = (uv * 2.0 - 1.0);

    // Calculate radial distance from center and azimuth angle
    float r = length(centered);
    float azimuth = atan(centered.y, centered.x);

    // Clamp radius to hemisphere (avoid pixels outside the dome circle)
    r = min(r, 1.0);

    // LL180 hemisphere projection in spherical coordinates:
    // r maps to angular distance from view center (0° at center, 90° at edge)
    float theta = r * HALFPI;

    // Compute latitude with tilt offset applied in 2D spherical space
    // This is the key to creating the curved horizon effect!
    // tilt=0: center at horizon (lat=0°), edge at nadir (lat=-90°)
    // tilt=65: center at 65° above horizon, horizon curves at ~72% radius
    // tilt=90: center at zenith (lat=90°), horizon at edge
    float lat = radians(tiltDeg) - theta;

    // Longitude is the azimuthal angle around the view center
    float lon = azimuth;

    // Clamp latitude to valid range to avoid artifacts
    lat = clamp(lat, -HALFPI, HALFPI);

    // Convert spherical (lat, lon) to 3D Cartesian
    // World coordinates: Y=up, Z=forward, X=right
    vec3 dir;
    dir.x = cos(lat) * sin(lon);   // right/left
    dir.y = sin(lat);               // up/down
    dir.z = cos(lat) * cos(lon);   // forward/back

    // Note: We compute direction directly in world space, ignoring camBasis
    // This ensures tilt=0 looks at horizon regardless of shader's dome orientation
    return normalize(dir);
}

`;

        finalShader += cleanSource;

        // Add main wrapper if shader doesn't have one
        if (!hasMain) {
            finalShader += '\n\nvoid main() {\n    mainImage(fragColor, gl_FragCoord.xy);\n}\n';
        }

        return finalShader;
    }

    createQuad() {
        const gl = this.gl;

        const vertices = new Float32Array([
            -1, -1,
             1, -1,
            -1,  1,
             1,  1,
        ]);

        const buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

        const positionLoc = gl.getAttribLocation(this.program, 'position');
        gl.enableVertexAttribArray(positionLoc);
        gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);
    }

    render() {
        if (!this.program) return;

        const gl = this.gl;

        gl.viewport(0, 0, this.canvas.width, this.canvas.height);
        gl.clearColor(0, 0, 0, 1);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.useProgram(this.program);

        // Update and bind audio texture
        this.audioTexture.update(this.audioFFT, this.audioWaveform);
        this.audioTexture.bind(0);

        // Set standard Shadertoy uniforms
        gl.uniform3f(this.uniforms.iResolution, this.canvas.width, this.canvas.height, 1.0);
        gl.uniform1f(this.uniforms.iTime, this.currentTime);
        gl.uniform1f(this.uniforms.iTimeDelta, 0.016); // ~60fps
        gl.uniform1i(this.uniforms.iFrame, this.frameCount);
        gl.uniform4f(this.uniforms.iMouse, 0, 0, 0, 0); // TODO: mouse tracking

        // Set iDate (year, month, day, time in seconds)
        const now = new Date();
        if (this.uniforms.iDate !== null) {
            gl.uniform4f(this.uniforms.iDate,
                now.getFullYear(),
                now.getMonth(),
                now.getDate(),
                now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds() + now.getMilliseconds() / 1000
            );
        }

        // Set iSampleRate (audio sample rate, default 44100)
        if (this.uniforms.iSampleRate !== null) {
            gl.uniform1f(this.uniforms.iSampleRate, 44100.0);
        }

        // Bind texture channels
        if (this.uniforms.iChannel0 !== null) gl.uniform1i(this.uniforms.iChannel0, 0);
        if (this.uniforms.iChannel1 !== null) gl.uniform1i(this.uniforms.iChannel1, 1);
        if (this.uniforms.iChannel2 !== null) gl.uniform1i(this.uniforms.iChannel2, 2);
        if (this.uniforms.iChannel3 !== null) gl.uniform1i(this.uniforms.iChannel3, 3);

        // Set channel time and resolution arrays
        for (let i = 0; i < 4; i++) {
            if (this.uniforms.iChannelTime[i] !== null) {
                gl.uniform1f(this.uniforms.iChannelTime[i], 0.0);
            }
            if (this.uniforms.iChannelResolution[i] !== null) {
                gl.uniform3f(this.uniforms.iChannelResolution[i], 512, 2, 1);
            }
        }

        // CedarToy camera uniforms
        if (this.uniforms.iCameraMode !== null) {
            gl.uniform1i(this.uniforms.iCameraMode, this.cameraMode);
        }
        if (this.uniforms.iCameraTiltDeg !== null) {
            gl.uniform1f(this.uniforms.iCameraTiltDeg, this.cameraTilt);
        }

        // Jitter uniforms (preview uses no jitter - single sample)
        if (this.uniforms.iJitter !== null) {
            gl.uniform2f(this.uniforms.iJitter, 0.0, 0.0);
        }
        if (this.uniforms.iSampleIndex !== null) {
            gl.uniform1i(this.uniforms.iSampleIndex, 0);
        }

        // Draw
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

        this.frameCount++;
    }

    play() {
        this.playing = true;
        this.startTime = Date.now() - (this.currentTime * 1000);
        this.animate();
    }

    pause() {
        this.playing = false;
    }

    seek(time) {
        this.currentTime = time;
        this.startTime = Date.now() - (time * 1000);
        if (!this.playing) {
            this.render();
        }
    }

    animate() {
        if (!this.playing) return;

        this.currentTime = (Date.now() - this.startTime) / 1000;
        this.render();

        requestAnimationFrame(() => this.animate());
    }

    updateAudioData(fftData, waveformData) {
        // Update audio FFT and waveform data for shader
        if (fftData) {
            this.audioFFT = fftData;
        }
        if (waveformData) {
            this.audioWaveform = waveformData;
        }
    }
}
