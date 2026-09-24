import { AudioTexture } from './audio-texture.js';
import { MUSICAL_UNIFORMS, NO_NEXT_SECTION } from './cue-compose.js';

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

        // MusiCue bundle uniforms — updated each transport-frame by preview-panel.
        // All zeros when no bundle / no audio is playing.
        this.bundleUniforms = this._defaultBundleUniforms();

        // @param-declared shader uniforms. Populated by compileShader from
        // `// @param name type default min max "label"` lines in the source.
        // shaderParams[i] = {name, type, default}; values are kept in
        // shaderParamValues so setShaderParameters() can override per-frame.
        this.shaderParams = [];
        this.shaderParamValues = {};

        // Mouse tracking for iMouse uniform
        this.mouseX = 0;
        this.mouseY = 0;
        this.mouseClickX = 0;
        this.mouseClickY = 0;
        this.mouseDown = false;

        this._onMouseMove = (e) => {
            const rect = this.canvas.getBoundingClientRect();
            this.mouseX = (e.clientX - rect.left) * (this.canvas.width / rect.width);
            this.mouseY = this.canvas.height - (e.clientY - rect.top) * (this.canvas.height / rect.height);
        };
        this._onMouseDown = (e) => {
            this.mouseDown = true;
            const rect = this.canvas.getBoundingClientRect();
            this.mouseClickX = (e.clientX - rect.left) * (this.canvas.width / rect.width);
            this.mouseClickY = this.canvas.height - (e.clientY - rect.top) * (this.canvas.height / rect.height);
        };
        this._onMouseUp = () => {
            this.mouseDown = false;
        };

        this.canvas.addEventListener('mousemove', this._onMouseMove);
        this.canvas.addEventListener('mousedown', this._onMouseDown);
        this.canvas.addEventListener('mouseup', this._onMouseUp);
    }

    /** Parse `// @param name type default min max "label"` lines out of the
     * shader source. Mirrors the server-side _parse_shader_metadata regex so
     * the preview can bind defaults that the @param system only feeds in the
     * headless render path. Without this, any shader that drives motion off a
     * `@param` uniform (e.g. `iTime * pulse_speed`) would see the uniform as
     * zero in preview and freeze. */
    _parseShaderParams(source) {
        const re = /^[ \t]*\/\/[ \t]*@param[ \t]+(\w+)[ \t]+(\w+)[ \t]+(\S+)[ \t]+\S+[ \t]+\S+[ \t]+.+$/gm;
        const out = [];
        let m;
        while ((m = re.exec(source)) !== null) {
            const [, name, type, defStr] = m;
            const value = type === 'int' ? parseInt(defStr, 10) : parseFloat(defStr);
            out.push({ name, type, default: value });
        }
        return out;
    }

    /** Override @param values. Names not in `values` keep their parsed default.
     * Names not declared in the shader are ignored. */
    setShaderParameters(values) {
        if (!values || !this.shaderParamValues) return;
        for (const k of Object.keys(values)) {
            if (k in this.shaderParamValues) {
                this.shaderParamValues[k] = values[k];
            }
        }
    }

    /** No-bundle values: zeros, "no next section", and iMusicTime = null
     * (bound as iTime at draw time so shaders using it as an iTime
     * replacement keep moving). Mirrors musicue.py::masked_musical_uniforms. */
    _defaultBundleUniforms() {
        const out = { bpm: 0, beat: 0, bar: 0, energy: 0, sectionEnergy: 0, sectionId: 0 };
        for (const [name, key] of MUSICAL_UNIFORMS) {
            out[key] = name === 'iTimeToNextSection' ? NO_NEXT_SECTION : 0;
        }
        out.musicTime = null;
        return out;
    }

    /** Update the cached MusiCue bundle uniforms. Called per frame by preview-panel. */
    updateBundleUniforms(u) {
        if (!u) return;
        const out = this._defaultBundleUniforms();
        for (const k of Object.keys(out)) {
            if (u[k] !== undefined && u[k] !== null) out[k] = u[k];
        }
        this.bundleUniforms = out;
    }

    compileShader(source) {
        const gl = this.gl;

        // Clean up previous program and shaders to prevent GPU resource leaks
        if (this.program) {
            const shaders = gl.getAttachedShaders(this.program);
            if (shaders) {
                shaders.forEach(s => {
                    gl.detachShader(this.program, s);
                    gl.deleteShader(s);
                });
            }
            gl.deleteProgram(this.program);
            this.program = null;
        }

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
            // MusiCue bundle uniforms (preview binding — match headers in
            // shaders/common/header.glsl so the same shader source runs
            // both here and in the headless renderer).
            iBpm: gl.getUniformLocation(this.program, 'iBpm'),
            iBeat: gl.getUniformLocation(this.program, 'iBeat'),
            iBar: gl.getUniformLocation(this.program, 'iBar'),
            iSectionEnergy: gl.getUniformLocation(this.program, 'iSectionEnergy'),
            iSectionId: gl.getUniformLocation(this.program, 'iSectionId'),
            iEnergy: gl.getUniformLocation(this.program, 'iEnergy'),
        };
        // Musical-structure bundle uniforms (iBeatClock, iKick, iMusicTime, ...).
        for (const [name] of MUSICAL_UNIFORMS) {
            this.uniforms[name] = gl.getUniformLocation(this.program, name);
        }

        // Get array uniform locations
        this.uniforms.iChannelTime = [];
        this.uniforms.iChannelResolution = [];
        for (let i = 0; i < 4; i++) {
            this.uniforms.iChannelTime[i] = gl.getUniformLocation(this.program, `iChannelTime[${i}]`);
            this.uniforms.iChannelResolution[i] = gl.getUniformLocation(this.program, `iChannelResolution[${i}]`);
        }

        // Parse @param declarations and prepare per-param uniform bindings.
        // Keep previously-set values where the param name still exists so a
        // recompile (e.g. fix-it round trip) doesn't snap sliders back to
        // their defaults; otherwise initialise from parsed defaults.
        const prevValues = this.shaderParamValues || {};
        this.shaderParams = this._parseShaderParams(source);
        this.shaderParamValues = {};
        for (const p of this.shaderParams) {
            this.uniforms[p.name] = gl.getUniformLocation(this.program, p.name);
            this.shaderParamValues[p.name] = (p.name in prevValues)
                ? prevValues[p.name]
                : p.default;
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
        // MusiCue bundle uniforms — the cookbook tells shader authors to declare
        // these, but our wrapper also prepends them. Strip the author copy to
        // avoid `redefinition` errors at compile time.
        cleanSource = cleanSource.replace(/uniform\s+float\s+iBpm\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iBeat\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+int\s+iBar\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iSectionEnergy\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+int\s+iSectionId\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iEnergy\s*;/g, '');
        for (const [name] of MUSICAL_UNIFORMS) {
            cleanSource = cleanSource.replace(
                new RegExp(`uniform\\s+float\\s+${name}\\s*;`, 'g'), '');
        }
        // CedarToy camera/jitter uniforms — same reasoning.
        cleanSource = cleanSource.replace(/uniform\s+int\s+iCameraMode\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+float\s+iCameraTiltDeg\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+vec2\s+iJitter\s*;/g, '');
        cleanSource = cleanSource.replace(/uniform\s+int\s+iSampleIndex\s*;/g, '');

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
        finalShader += 'uniform int iSampleIndex;\n';
        finalShader += '// MusiCue bundle uniforms (same shape as shaders/common/header.glsl)\n';
        finalShader += 'uniform float iBpm;\n';
        finalShader += 'uniform float iBeat;\n';
        finalShader += 'uniform int   iBar;\n';
        finalShader += 'uniform float iSectionEnergy;\n';
        finalShader += 'uniform int   iSectionId;\n';
        finalShader += 'uniform float iEnergy;\n';
        for (const [name] of MUSICAL_UNIFORMS) {
            finalShader += `uniform float ${name};\n`;
        }
        finalShader += '\n';
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
// Matches shaders/common/header.glsl (headless render path) so preview and
// final render produce the same image. Each axis independently sweeps 180°:
// lon = (u·2 − 1) · π/2  and  lat = (v·2 − 1) · π/2. Tilt is an X-axis
// rotation applied to the local direction before the camera basis transform.
vec3 cameraDirLL180(vec2 uv, float tiltDeg, mat3 camBasis) {
    float lon = (uv.x * 2.0 - 1.0) * HALFPI;  // -pi/2 .. pi/2
    float lat = (uv.y * 2.0 - 1.0) * HALFPI;  // -pi/2 .. pi/2

    vec3 dirLocal;
    dirLocal.x = cos(lat) * sin(lon);
    dirLocal.y = sin(lat);
    dirLocal.z = cos(lat) * cos(lon);

    // X-axis tilt rotation (negative so positive tiltDeg tilts the dome up,
    // matching the headless renderer's convention).
    float tiltRad = radians(-tiltDeg);
    float c = cos(tiltRad);
    float s = sin(tiltRad);
    mat3 tiltX = mat3(
        1.0, 0.0, 0.0,
        0.0,  c, -s,
        0.0,  s,  c
    );

    dirLocal = tiltX * dirLocal;
    return normalize(camBasis * dirLocal);
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
        gl.uniform4f(this.uniforms.iMouse,
            this.mouseX, this.mouseY,
            this.mouseDown ? this.mouseClickX : 0,
            this.mouseDown ? this.mouseClickY : 0
        );

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

        // MusiCue bundle uniforms (set from the most recent transport-frame).
        const bu = this.bundleUniforms || this._defaultBundleUniforms();
        if (this.uniforms.iBpm !== null) gl.uniform1f(this.uniforms.iBpm, bu.bpm);
        if (this.uniforms.iBeat !== null) gl.uniform1f(this.uniforms.iBeat, bu.beat);
        if (this.uniforms.iBar !== null) gl.uniform1i(this.uniforms.iBar, bu.bar | 0);
        if (this.uniforms.iSectionEnergy !== null) gl.uniform1f(this.uniforms.iSectionEnergy, bu.sectionEnergy);
        if (this.uniforms.iSectionId !== null) gl.uniform1i(this.uniforms.iSectionId, bu.sectionId | 0);
        if (this.uniforms.iEnergy !== null) gl.uniform1f(this.uniforms.iEnergy, bu.energy);
        for (const [name, key] of MUSICAL_UNIFORMS) {
            const loc = this.uniforms[name];
            if (loc === null || loc === undefined) continue;
            let v = bu[key];
            if (name === 'iMusicTime' && (v === null || v === undefined)) v = this.currentTime;
            gl.uniform1f(loc, +v || 0);
        }

        // @param uniforms — keeps shaders that drive motion off these (e.g.
        // `iTime * pulse_speed`) from freezing when the param isn't otherwise
        // set. Headless render binds the same values via the job's
        // shader_parameters dict; preview now matches.
        for (const p of this.shaderParams) {
            const loc = this.uniforms[p.name];
            if (loc === null) continue;
            const v = this.shaderParamValues[p.name];
            if (p.type === 'int') gl.uniform1i(loc, v | 0);
            else gl.uniform1f(loc, +v);
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
