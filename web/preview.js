const canvas = document.getElementById("glcanvas");
const gl = canvas.getContext("webgl2");
const statusEl = document.getElementById("status");
const shaderSelect = document.getElementById("shaderSelect");

if (!gl) {
  alert("WebGL2 not supported");
  throw new Error("WebGL2 not supported");
}

const VERT_SRC = `#version 300 es
in vec2 in_vert;
in vec2 in_uv;
out vec2 uv;
void main() {
  gl_Position = vec4(in_vert, 0.0, 1.0);
  uv = in_uv;
}`;

const HELPERS_SRC = `
const float PI = 3.141592653589793238;
mat3 buildCameraBasis(vec3 camDir, vec3 camUp) {
  vec3 f = normalize(camDir);
  vec3 r = normalize(cross(camUp, f));
  vec3 u = cross(f, r);
  return mat3(r, u, f);
}
vec3 cameraDirLL180(vec2 uv, float tiltDeg, mat3 camBasis) {
  float lon = (uv.x * 2.0 - 1.0) * (0.5 * PI);
  float lat = (uv.y * 2.0 - 1.0) * (0.5 * PI);
  vec3 dirLocal;
  dirLocal.x = cos(lat) * sin(lon);
  dirLocal.y = sin(lat);
  dirLocal.z = cos(lat) * cos(lon);
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
vec2 sampleAudioHistoryLR(float tNorm, float freqNorm) {
  float frames = iAudioHistoryResolution.x;
  float bins2  = iAudioHistoryResolution.y;
  float bins   = bins2 * 0.5;
  float x = clamp(tNorm, 0.0, 1.0);
  float frameIndex = x * (frames - 1.0);
  x = frameIndex / max(frames - 1.0, 1.0);
  float yL = clamp(freqNorm, 0.0, 1.0) * (bins / bins2);
  float yR = 0.5 + clamp(freqNorm, 0.0, 1.0) * (bins / bins2);
  float L = texture(iAudioHistoryTex, vec2(x, yL)).r;
  float R = texture(iAudioHistoryTex, vec2(x, yR)).r;
  return vec2(L, R);
}`;

const FRAG_PREAMBLE = `#version 300 es
precision highp float;
uniform vec3      iResolution;
uniform float     iTime;
uniform float     iTimeDelta;
uniform float     iFrameRate;
uniform int       iFrame;
uniform float     iChannelTime[4];
uniform vec3      iChannelResolution[4];
uniform vec4      iMouse;
uniform sampler2D iChannel0;
uniform sampler2D iChannel1;
uniform sampler2D iChannel2;
uniform sampler2D iChannel3;
uniform vec4      iDate;
uniform float     iSampleRate;
uniform float     iDuration;
uniform int       iPassIndex;
uniform vec2      iTileOffset;
uniform int       iCameraMode;
uniform int       iCameraStereo;
uniform vec3      iCameraPos;
uniform vec3      iCameraDir;
uniform vec3      iCameraUp;
uniform float     iCameraFov;
uniform float     iCameraTiltDeg;
uniform float     iCameraIPD;
uniform sampler2D iAudioHistoryTex;
uniform vec3      iAudioHistoryResolution;
${HELPERS_SRC}
`;

const FRAG_FOOTER = `
out vec4 fragColor_out;
void main() {
  vec4 color = vec4(0.0);
  mainImage(color, gl_FragCoord.xy + iTileOffset);
  fragColor_out = color;
}`;

function compileShader(type, src) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(info || "Shader compile error");
  }
  return shader;
}

function linkProgram(vsSrc, fsSrc) {
  const vs = compileShader(gl.VERTEX_SHADER, vsSrc);
  const fs = compileShader(gl.FRAGMENT_SHADER, fsSrc);
  const prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    const info = gl.getProgramInfoLog(prog);
    gl.deleteProgram(prog);
    throw new Error(info || "Program link error");
  }
  return prog;
}

function createFullscreenVAO(prog) {
  const vertices = new Float32Array([
    -1.0, -1.0, 0.0, 0.0,
    1.0, -1.0, 1.0, 0.0,
    -1.0, 1.0, 0.0, 1.0,
    1.0, 1.0, 1.0, 1.0,
  ]);
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);

  const stride = 4 * 4;
  const locVert = gl.getAttribLocation(prog, "in_vert");
  const locUv = gl.getAttribLocation(prog, "in_uv");
  gl.enableVertexAttribArray(locVert);
  gl.vertexAttribPointer(locVert, 2, gl.FLOAT, false, stride, 0);
  gl.enableVertexAttribArray(locUv);
  gl.vertexAttribPointer(locUv, 2, gl.FLOAT, false, stride, 2 * 4);

  gl.bindVertexArray(null);
  gl.bindBuffer(gl.ARRAY_BUFFER, null);
  return { vao, vbo };
}

function createBlackTexture(unit) {
  const tex = gl.createTexture();
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return tex;
}

const channelTextures = [
  createBlackTexture(0),
  createBlackTexture(1),
  createBlackTexture(2),
  createBlackTexture(3),
];
const historyTexture = createBlackTexture(4);

let program = null;
let fullscreen = null;
let uniforms = {};
let channelRes = [
  [1, 1, 1],
  [1, 1, 1],
  [1, 1, 1],
  [1, 1, 1],
];

let audioCtx = null;
let analyser = null;
let audioSource = null;
let freqData = null;
let timeData = null;
let audioEnabled = false;
let audioSampleRate = 0;
let startTime = performance.now() / 1000;
let lastTime = startTime;
let frameIndex = 0;
let mouse = [0, 0, 0, 0];
let mouseDown = false;

canvas.addEventListener("mousemove", (e) => {
  const rect = canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (canvas.width / rect.width);
  const y = (rect.bottom - e.clientY) * (canvas.height / rect.height);
  mouse[0] = x;
  mouse[1] = y;
  if (mouseDown) {
    mouse[2] = x;
    mouse[3] = y;
  }
});
canvas.addEventListener("mousedown", () => {
  mouseDown = true;
  mouse[2] = mouse[0];
  mouse[3] = mouse[1];
});
canvas.addEventListener("mouseup", () => {
  mouseDown = false;
});

function uploadImageToChannel(file, unit) {
  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => {
      const tmp = document.createElement("canvas");
      tmp.width = img.width;
      tmp.height = img.height;
      const ctx2d = tmp.getContext("2d");
      ctx2d.drawImage(img, 0, 0);
      const pixels = ctx2d.getImageData(0, 0, img.width, img.height).data;

      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, channelTextures[unit]);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA,
        img.width,
        img.height,
        0,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        pixels
      );
      gl.generateMipmap(gl.TEXTURE_2D);
      channelRes[unit] = [img.width, img.height, 1];
      statusEl.textContent = `Loaded iChannel${unit}`;
      if (unit === 0) audioEnabled = false;
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
}

function setupAudio(file) {
  if (!file) return;
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const reader = new FileReader();
  reader.onload = async () => {
    const arrayBuf = reader.result;
    const audioBuf = await audioCtx.decodeAudioData(arrayBuf);
    if (audioSource) audioSource.stop();
    audioSource = audioCtx.createBufferSource();
    audioSource.buffer = audioBuf;
    audioSource.loop = true;
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    freqData = new Uint8Array(analyser.frequencyBinCount);
    timeData = new Uint8Array(analyser.fftSize);
    audioSampleRate = audioBuf.sampleRate;
    audioSource.connect(analyser);
    analyser.connect(audioCtx.destination);
    audioSource.start(0);
    audioEnabled = true;
    statusEl.textContent = "Audio enabled";
  };
  reader.readAsArrayBuffer(file);
}

document.getElementById("chan0").addEventListener("change", (e) => uploadImageToChannel(e.target.files[0], 0));
document.getElementById("chan1").addEventListener("change", (e) => uploadImageToChannel(e.target.files[0], 1));
document.getElementById("chan2").addEventListener("change", (e) => uploadImageToChannel(e.target.files[0], 2));
document.getElementById("chan3").addEventListener("change", (e) => uploadImageToChannel(e.target.files[0], 3));
document.getElementById("audioFile").addEventListener("change", (e) => {
  if (channelRes[0][0] !== 1 || channelRes[0][1] !== 1) {
    statusEl.textContent = "iChannel0 already has an image; clear it to use audio.";
    return;
  }
  setupAudio(e.target.files[0]);
});

function cacheUniforms(prog) {
  const names = [
    "iResolution", "iTime", "iTimeDelta", "iFrameRate", "iFrame", "iMouse",
    "iDate", "iSampleRate", "iDuration", "iPassIndex", "iTileOffset",
    "iCameraMode", "iCameraStereo", "iCameraPos", "iCameraDir", "iCameraUp",
    "iCameraFov", "iCameraTiltDeg", "iCameraIPD",
    "iChannelTime", "iChannelResolution", "iAudioHistoryResolution",
    "iChannel0", "iChannel1", "iChannel2", "iChannel3", "iAudioHistoryTex",
  ];
  const out = {};
  for (const n of names) out[n] = gl.getUniformLocation(prog, n);
  return out;
}

async function loadShaderList() {
  const res = await fetch("/api/shaders");
  const json = await res.json();
  shaderSelect.innerHTML = "";
  for (const s of json.shaders || []) {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    shaderSelect.appendChild(opt);
  }
}

async function loadAndCompile(relPath) {
  statusEl.textContent = "Compiling...";
  const res = await fetch(`/api/shader?path=${encodeURIComponent(relPath)}&v=${Date.now()}`);
  const userSrcRaw = await res.text();
  const userSrc = userSrcRaw
    .split("\n")
    .filter((l) => !l.trim().startsWith("#version"))
    .join("\n");

  const fragSrc = `${FRAG_PREAMBLE}\n${userSrc}\n${FRAG_FOOTER}`;

  try {
    const newProg = linkProgram(VERT_SRC, fragSrc);
    if (program) gl.deleteProgram(program);
    program = newProg;
    uniforms = cacheUniforms(program);
    if (fullscreen) {
      gl.deleteVertexArray(fullscreen.vao);
      gl.deleteBuffer(fullscreen.vbo);
    }
    fullscreen = createFullscreenVAO(program);

    gl.useProgram(program);
    for (let i = 0; i < 4; i++) {
      if (uniforms[`iChannel${i}`]) gl.uniform1i(uniforms[`iChannel${i}`], i);
    }
    if (uniforms.iAudioHistoryTex) gl.uniform1i(uniforms.iAudioHistoryTex, 4);

    frameIndex = 0;
    startTime = performance.now() / 1000;
    lastTime = startTime;
    statusEl.textContent = "Ready";
  } catch (e) {
    statusEl.textContent = String(e);
    console.error(e);
  }
}

document.getElementById("reload").addEventListener("click", () => {
  loadAndCompile(shaderSelect.value || "test.glsl");
});
shaderSelect.addEventListener("change", () => {
  loadAndCompile(shaderSelect.value);
});

function renderLoop(nowMs) {
  if (!program || !fullscreen) {
    requestAnimationFrame(renderLoop);
    return;
  }
  const now = nowMs / 1000;
  const t = now - startTime;
  const dt = now - lastTime;
  lastTime = now;

  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.useProgram(program);
  gl.bindVertexArray(fullscreen.vao);

  if (uniforms.iResolution) gl.uniform3f(uniforms.iResolution, canvas.width, canvas.height, 1.0);
  if (uniforms.iTime) gl.uniform1f(uniforms.iTime, t);
  if (uniforms.iTimeDelta) gl.uniform1f(uniforms.iTimeDelta, dt);
  if (uniforms.iFrameRate) gl.uniform1f(uniforms.iFrameRate, dt > 0 ? 1.0 / dt : 0.0);
  if (uniforms.iFrame) gl.uniform1i(uniforms.iFrame, frameIndex);
  if (uniforms.iMouse) gl.uniform4f(uniforms.iMouse, mouse[0], mouse[1], mouse[2], mouse[3]);

  const d = new Date();
  const seconds = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds() + d.getMilliseconds() / 1000;
  if (uniforms.iDate) gl.uniform4f(uniforms.iDate, d.getFullYear(), d.getMonth() + 1, d.getDate(), seconds);

  if (uniforms.iSampleRate) gl.uniform1f(uniforms.iSampleRate, 0.0);
  if (uniforms.iDuration) gl.uniform1f(uniforms.iDuration, 0.0);
  if (uniforms.iPassIndex) gl.uniform1i(uniforms.iPassIndex, 0);
  if (uniforms.iTileOffset) gl.uniform2f(uniforms.iTileOffset, 0.0, 0.0);

  if (uniforms.iCameraMode) gl.uniform1i(uniforms.iCameraMode, 0);
  if (uniforms.iCameraStereo) gl.uniform1i(uniforms.iCameraStereo, 0);
  if (uniforms.iCameraPos) gl.uniform3f(uniforms.iCameraPos, 0.0, 0.0, 0.0);
  if (uniforms.iCameraDir) gl.uniform3f(uniforms.iCameraDir, 0.0, 0.0, -1.0);
  if (uniforms.iCameraUp) gl.uniform3f(uniforms.iCameraUp, 0.0, 1.0, 0.0);
  if (uniforms.iCameraFov) gl.uniform1f(uniforms.iCameraFov, Math.PI / 2);
  if (uniforms.iCameraTiltDeg) gl.uniform1f(uniforms.iCameraTiltDeg, 65.0);
  if (uniforms.iCameraIPD) gl.uniform1f(uniforms.iCameraIPD, 0.064);

  if (uniforms.iChannelTime) gl.uniform1fv(uniforms.iChannelTime, new Float32Array([t, t, t, t]));
  if (uniforms.iChannelResolution) gl.uniform3fv(uniforms.iChannelResolution, new Float32Array([
    channelRes[0][0], channelRes[0][1], channelRes[0][2],
    channelRes[1][0], channelRes[1][1], channelRes[1][2],
    channelRes[2][0], channelRes[2][1], channelRes[2][2],
    channelRes[3][0], channelRes[3][1], channelRes[3][2],
  ]));
  if (uniforms.iAudioHistoryResolution) gl.uniform3f(uniforms.iAudioHistoryResolution, 1, 1, 1);

  if (audioEnabled && analyser) {
    analyser.getByteFrequencyData(freqData);
    analyser.getByteTimeDomainData(timeData);
    const fftRow = new Float32Array(512);
    const waveRow = new Float32Array(512);
    for (let i = 0; i < 512; i++) {
      fftRow[i] = (freqData[i] || 0) / 255.0;
      waveRow[i] = (timeData[i] || 128) / 255.0;
    }
    const texData = new Float32Array(512 * 2);
    texData.set(fftRow, 0);
    texData.set(waveRow, 512);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, channelTextures[0]);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, 512, 2, 0, gl.RED, gl.FLOAT, texData);
    channelRes[0] = [512, 2, 1];
    if (uniforms.iSampleRate) gl.uniform1f(uniforms.iSampleRate, audioSampleRate);
  }

  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  gl.bindVertexArray(null);
  frameIndex++;
  requestAnimationFrame(renderLoop);
}

loadShaderList()
  .then(() => {
    if (shaderSelect.options.length > 0) shaderSelect.value = shaderSelect.options[0].value;
    return loadAndCompile(shaderSelect.value || "test.glsl");
  })
  .then(() => requestAnimationFrame(renderLoop));
