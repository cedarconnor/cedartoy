import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js?v=6';
import { modulatedValuesAt } from '../webgl/modulation-bind.js?v=1';
import { composeRow1, composeUniforms, effectiveSettings,
    applySettingsSeries, composeRow0FromValues }
    from '../webgl/cue-compose.js';

class PreviewPanel extends HTMLElement {
    constructor() {
        super();
        this.renderer = null;
        this.hasAudioTimeline = false;
        this.useAudioTimeline = false;
        this._zeroFft = new Float32Array(512);
        this._zeroWaveform = new Float32Array(512);
        this._timeline = null;       // /api/reactivity/track-timeline payload
        this._effSettings = {};      // effective per-track settings (mask)
        this._effSeries = {};        // per-track effective per-frame series
        this._timelineFps = 24.0;
        this._modSeries = null;      // /api/modulation/series payload
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();

        const canvas = this.querySelector('#preview-canvas');
        this.renderer = new ShaderRenderer(canvas);
        this._setUseAudioTimeline(false);

        document.addEventListener('shader-select', async (e) => {
            await this.loadShader(e.detail.path);
        });

        document.addEventListener('audio-data', (e) => {
            if (this.useAudioTimeline && this.renderer) {
                this.renderer.updateAudioData(e.detail.fft, e.detail.waveform);
            }
        });

        document.addEventListener('project-loaded', (e) => {
            this.hasAudioTimeline = !!e.detail?.audio_url;
            this._setUseAudioTimeline(!!e.detail?.audio_url);
        });

        // Fetch the per-track timeline so the preview can be driven by the
        // bundle (matching the render) instead of live FFT.
        document.addEventListener('project-loaded', async (e) => {
            const audio = e.detail?.audio_path || e.detail?.path;
            this._timeline = null;
            if (!audio) return;
            try {
                const ce = document.querySelector('config-editor');
                const avOff = (ce && ce.config && +ce.config.av_offset_ms) || 0;
                const r = await fetch('/api/reactivity/track-timeline?audio='
                    + encodeURIComponent(audio) + '&av_offset_ms=' + avOff);
                if (r.ok) {
                    this._timeline = await r.json();
                    this._timelineFps = this._timeline.fps || 24.0;
                    this._effSettings = effectiveSettings(
                        this._readPersistedSettings(), null);
                    this._rebuildEffSeries();
                }
            } catch (_) { this._timeline = null; }
        });

        document.addEventListener('track-settings-change', (e) => {
            this._effSettings = effectiveSettings(
                e.detail.trackSettings, e.detail.soloIds);
            this._rebuildEffSeries();
            this._persistSettings(e.detail.trackSettings);
            if (this.renderer) this._composeAndRender(this.renderer.currentTime || 0);
        });

        // Modulation matrix: per-frame @param values computed server-side.
        document.addEventListener('modulation-series', (e) => {
            this._modSeries = e.detail || null;
            if (!this.renderer) return;
            this._applyModulation(this.renderer.currentTime || 0);
            if (this.useAudioTimeline) this.renderer.render();
        });

        // Transport-strip drives time only when preview is connected to it.
        document.addEventListener('transport-frame', (e) => {
            if (!this.useAudioTimeline) return;
            if (!this.renderer) return;
            const t = e.detail.timeSec || 0;
            this.renderer.currentTime = t;
            if (this._timeline) {
                this._composeAndRender(t);
            } else {
                if (e.detail.bundle) this.renderer.updateBundleUniforms(e.detail.bundle);
                this._applyModulation(t);
                this.renderer.render();
            }
        });

        document.addEventListener('config-change', (e) => {
            const config = e.detail;
            const modeMap = { '2d': 0, 'equirect': 1, 'll180': 2 };
            if (config.camera_mode && this.renderer) {
                const modeIndex = modeMap[config.camera_mode] ?? 0;
                this.renderer.cameraMode = modeIndex;
                const sel = this.querySelector('#camera-mode');
                if (sel) sel.value = modeIndex;
            }
            const tiltValue = config.camera_tilt_deg ?? config.camera_params?.tilt_deg;
            if (tiltValue !== undefined && this.renderer) {
                this.renderer.cameraTilt = tiltValue;
                const slider = this.querySelector('#camera-tilt');
                const disp = this.querySelector('#tilt-display');
                if (slider) slider.value = tiltValue;
                if (disp) disp.textContent = `${tiltValue}°`;
            }
            if (config.shader_parameters && this.renderer) {
                this.renderer.setShaderParameters(config.shader_parameters);
            }
            if (this.renderer) this.renderer.render();
        });
    }

    render() {
        this.innerHTML = `
            <div class="preview-container">
                <h3>Preview</h3>
                <div style="position: relative;">
                    <canvas id="preview-canvas" width="640" height="360"
                        style="width: 100%; background: #000; border-radius: 4px;"></canvas>
                    <div id="preview-error" style="display: none; position: absolute; top: 50%; left: 50%;
                        transform: translate(-50%, -50%); color: var(--error); font-weight: bold;">
                    </div>
                </div>
                <div class="preview-clock-controls" style="margin-top: 8px; display: flex; align-items: center; gap: 10px; font-size: 0.85rem;">
                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                        <input type="checkbox" id="preview-use-timeline">
                        <span>Use audio timeline</span>
                    </label>
                    <span id="preview-clock-mode" style="color: var(--text-secondary);">Free run</span>
                </div>
                <div class="camera-controls" style="margin-top: 8px; padding: 8px; background: var(--bg-secondary); border-radius: 4px;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                        <label style="font-size: 0.85rem; width: 100px;">Camera Mode:</label>
                        <select id="camera-mode" style="flex: 1; padding: 4px; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border); border-radius: 4px;">
                            <option value="0">2D Standard</option>
                            <option value="1">Equirectangular</option>
                            <option value="2">LL180 Dome</option>
                        </select>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <label style="font-size: 0.85rem; width: 100px;">Camera Tilt:</label>
                        <input type="range" id="camera-tilt" min="0" max="90" value="0" step="1"
                            style="flex: 1;">
                        <span id="tilt-display" style="font-size: 0.85rem; width: 40px;">0°</span>
                    </div>
                </div>
                <div style="margin-top: 8px; font-size: 0.8rem; color: var(--text-secondary);">
                    Note: Preview is single-pass only. Full multipass rendering in final output.
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        const cameraModeSelect = this.querySelector('#camera-mode');
        const cameraTiltSlider = this.querySelector('#camera-tilt');
        const tiltDisplay = this.querySelector('#tilt-display');
        const timelineToggle = this.querySelector('#preview-use-timeline');

        timelineToggle.addEventListener('change', (e) => {
            this._setUseAudioTimeline(e.target.checked);
        });

        cameraModeSelect.addEventListener('change', (e) => {
            const modeIndex = parseInt(e.target.value);
            if (this.renderer) {
                this.renderer.cameraMode = modeIndex;
                this.renderer.render();
            }
            const modeNames = ['2d', 'equirect', 'll180'];
            const ce = document.querySelector('config-editor');
            if (ce) {
                ce.config.camera_mode = modeNames[modeIndex];
                ce.saveToLocalStorage();
            }
        });

        cameraTiltSlider.addEventListener('input', (e) => {
            const tilt = parseFloat(e.target.value);
            tiltDisplay.textContent = `${tilt}°`;
            if (this.renderer) {
                this.renderer.cameraTilt = tilt;
                this.renderer.render();
            }
            const ce = document.querySelector('config-editor');
            if (ce) {
                ce.config.camera_tilt_deg = tilt;
                ce.saveToLocalStorage();
            }
        });
    }

    _setUseAudioTimeline(useTimeline) {
        this.useAudioTimeline = !!useTimeline && this.hasAudioTimeline;

        const toggle = this.querySelector('#preview-use-timeline');
        const modeLabel = this.querySelector('#preview-clock-mode');
        if (toggle) {
            toggle.checked = this.useAudioTimeline;
            toggle.disabled = !this.hasAudioTimeline;
            toggle.title = this.hasAudioTimeline ? '' : 'No audio timeline loaded';
        }
        if (modeLabel) {
            modeLabel.textContent = this.useAudioTimeline ? 'Audio timeline' : 'Free run';
        }

        if (!this.renderer) return;

        if (this.useAudioTimeline) {
            this.renderer.pause();
            document.dispatchEvent(new CustomEvent('transport-sync-request'));
            this.renderer.render();
            return;
        }

        this.renderer.updateAudioData(this._zeroFft, this._zeroWaveform);
        this.renderer.updateBundleUniforms({});
        this.renderer.paramOverrides = null;   // free run: base @param values
        if (!this.renderer.playing) {
            this.renderer.play();
        }
    }

    _rebuildEffSeries() {
        this._effSeries = {};
        if (!this._timeline) return;
        const tracks = this._timeline.frame_data.tracks;
        for (const tid of Object.keys(tracks)) {
            this._effSeries[tid] = applySettingsSeries(tracks[tid], this._effSettings[tid]);
        }
    }

    _composeAndRender(t) {
        const tl = this._timeline;
        const n = tl.frames;
        let f = Math.round(t * this._timelineFps);
        if (f < 0) f = 0;
        if (f >= n) f = n - 1;
        const bandValues = {};
        for (const tid of Object.keys(this._effSeries)) bandValues[tid] = this._effSeries[tid][f];
        const row0 = composeRow0FromValues(bandValues, tl.frame_data.uniforms.sectionEnergy[f]);
        const row1 = composeRow1(tl.frame_data, f);
        this.renderer.updateAudioData(row0, row1);
        this.renderer.updateBundleUniforms(composeUniforms(tl.frame_data, f, this._effSettings));
        this._applyModulation(t);
        this.renderer.render();
        this._emitCueFrame(f, t);
    }

    /** Bind modulated @param values at transport time t (timeline mode only;
     * free run keeps the base slider values). */
    _applyModulation(t) {
        if (!this.renderer) return;
        this.renderer.paramOverrides = (this.useAudioTimeline && this._modSeries)
            ? modulatedValuesAt(this._modSeries, t) : null;
    }

    _emitCueFrame(f, t) {
        const tl = this._timeline;
        const fd = tl.frame_data;
        const trackValues = {};
        for (const tid of Object.keys(fd.tracks)) {
            trackValues[tid] = (this._effSeries[tid] || [])[f] || 0;
        }
        let sectionLabel = '—';
        const blocks = (tl.tracks.sections && tl.tracks.sections.blocks) || [];
        for (const b of blocks) {
            if (b.start <= t && t < b.end) { sectionLabel = b.label || '—'; break; }
        }
        document.dispatchEvent(new CustomEvent('cue-frame', { detail: {
            frame: f, timeSec: t, sectionLabel, bundleMode: 'cued',
            uniforms: composeUniforms(fd, f, this._effSettings),
            trackValues,
        }}));
    }

    _readPersistedSettings() {
        const ce = document.querySelector('config-editor');
        return (ce && ce.config && ce.config.track_settings) || {};
    }

    _persistSettings(trackSettings) {
        const ce = document.querySelector('config-editor');
        if (ce && ce.config) {
            ce.config.track_settings = trackSettings;
            ce.saveToLocalStorage();
        }
    }

    async loadShader(path) {
        const errorDiv = this.querySelector('#preview-error');
        errorDiv.style.display = 'none';
        let ok = true;
        let log = '';
        try {
            const shaderData = await api.getShader(path);
            this.renderer.compileShader(shaderData.source);
            // Push any saved @param values from config-editor into the freshly
            // compiled program so user-tuned values survive shader reloads.
            const ce = document.querySelector('config-editor');
            if (ce?.config?.shader_parameters) {
                this.renderer.setShaderParameters(ce.config.shader_parameters);
            }
            this.renderer.render();
        } catch (err) {
            ok = false;
            log = err && err.message ? err.message : String(err);
            console.error('Failed to load shader:', err);
            errorDiv.textContent = `Shader Error: ${log}`;
            errorDiv.style.display = 'block';
        }
        document.dispatchEvent(new CustomEvent('shader-compile-result', {
            detail: { ok, log, path },
        }));
    }
}

customElements.define('preview-panel', PreviewPanel);
