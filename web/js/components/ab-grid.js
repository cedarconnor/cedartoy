/**
 * <ab-grid> — 2x2 A/B comparison: same shader + playhead, four audio sources
 * (raw FFT / cued / blend / no-audio). A verification tool for "is the bundle
 * helping?". Idle (no renders) until activated via setActive(true).
 */
import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js?v=5';
import { composeRow1, composeUniforms, effectiveSettings,
    applySettingsSeries, composeRow0FromValues } from '../webgl/cue-compose.js';

const PANELS = ['raw', 'cued', 'blend', 'no-audio'];
const Z = new Float32Array(512);

class AbGrid extends HTMLElement {
    constructor() {
        super();
        this._active = false;
        this._renderers = {};            // panel -> ShaderRenderer
        this._source = null;             // current shader source
        this._timeline = null;
        this._fps = 24.0;
        this._effSettings = {};
        this._effSeries = {};
        this._liveFft = new Float32Array(512);
        this._liveWave = new Float32Array(512);
        this._t = 0;
    }

    connectedCallback() {
        this.render();
        for (const name of PANELS) {
            this._renderers[name] = new ShaderRenderer(this.querySelector(`#ab-${this._id(name)}`));
        }
        document.addEventListener('shader-select', (e) => this._loadShader(e.detail.path));
        document.addEventListener('audio-data', (e) => {
            this._liveFft = e.detail.fft; this._liveWave = e.detail.waveform;
        });
        document.addEventListener('project-loaded', (e) => this._onProject(e.detail));
        document.addEventListener('track-settings-change', (e) => {
            this._effSettings = effectiveSettings(e.detail.trackSettings, e.detail.soloIds);
            this._rebuildEffSeries();
            if (this._active) this._renderAll(this._t);
        });
        document.addEventListener('transport-frame', (e) => {
            this._t = e.detail.timeSec || 0;
            if (this._active) this._renderAll(this._t);
        });
    }

    _id(name) { return name.replace('-', ''); }

    render() {
        this.innerHTML = `<div class="ab-grid">
            ${PANELS.map((n) => `<div class="ab-cell">
                <span class="ab-label">${n}</span>
                <canvas id="ab-${this._id(n)}" width="320" height="180"></canvas>
            </div>`).join('')}
        </div>`;
    }

    setActive(on) {
        this._active = !!on;
        if (this._active && this._source) {
            // (re)compile lazily on first activation
            for (const name of PANELS) {
                try { this._renderers[name].compileShader(this._source); } catch (_) {}
            }
            this._rebuildEffSeries();
            this._renderAll(this._t);
        }
    }

    async _loadShader(path) {
        try {
            const data = await api.getShader(path);
            this._source = data.source;
            if (this._active) {
                for (const name of PANELS) {
                    try { this._renderers[name].compileShader(this._source); } catch (_) {}
                }
                this._renderAll(this._t);
            }
        } catch (_) { /* leave previous source */ }
    }

    async _onProject(detail) {
        const audio = detail?.audio_path || detail?.path;
        this._timeline = null;
        if (!audio) return;
        try {
            const ce0 = document.querySelector('config-editor');
            const avOff = (ce0 && ce0.config && +ce0.config.av_offset_ms) || 0;
            const r = await fetch('/api/reactivity/track-timeline?audio=' + encodeURIComponent(audio)
                + '&av_offset_ms=' + avOff);
            if (r.ok) {
                this._timeline = await r.json();
                this._fps = this._timeline.fps || 24.0;
                const ce = document.querySelector('config-editor');
                this._effSettings = effectiveSettings((ce && ce.config && ce.config.track_settings) || {}, null);
                this._rebuildEffSeries();
            }
        } catch (_) { this._timeline = null; }
    }

    _rebuildEffSeries() {
        this._effSeries = {};
        if (!this._timeline) return;
        const tracks = this._timeline.frame_data.tracks;
        for (const tid of Object.keys(tracks)) {
            this._effSeries[tid] = applySettingsSeries(tracks[tid], this._effSettings[tid]);
        }
    }

    _frameIndex(t) {
        if (!this._timeline) return 0;
        let f = Math.round(t * this._fps);
        if (f < 0) f = 0;
        if (f >= this._timeline.frames) f = this._timeline.frames - 1;
        return f;
    }

    _cuedRow0(f) {
        const bandValues = {};
        for (const tid of Object.keys(this._effSeries)) bandValues[tid] = this._effSeries[tid][f];
        return composeRow0FromValues(bandValues, this._timeline.frame_data.uniforms.sectionEnergy[f]);
    }

    _renderAll(t) {
        if (!this._source) return;
        const f = this._frameIndex(t);
        const cued = this._timeline ? this._cuedRow0(f) : Z;
        const row1 = this._timeline ? composeRow1(this._timeline.frame_data, f) : Z;
        const uni = this._timeline ? composeUniforms(this._timeline.frame_data, f, this._effSettings) : {};
        const blend = new Float32Array(512);
        for (let i = 0; i < 512; i++) blend[i] = 0.5 * this._liveFft[i] + 0.5 * cued[i];

        this._drive('raw', t, this._liveFft, this._liveWave, uni);
        this._drive('cued', t, cued, row1, uni);
        this._drive('blend', t, blend, row1, uni);
        this._drive('no-audio', t, Z, Z, {});
    }

    _drive(name, t, fft, wave, uniforms) {
        const r = this._renderers[name];
        if (!r) return;
        r.currentTime = t;
        r.updateAudioData(fft, wave);
        r.updateBundleUniforms(uniforms);
        r.render();
    }
}

customElements.define('ab-grid', AbGrid);
