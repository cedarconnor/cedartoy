class OutputPanel extends HTMLElement {
    constructor() {
        super();
        this.config = {};
    }

    connectedCallback() {
        // Seed from config-editor's persisted config so the fields show prior values.
        const ce = document.querySelector('config-editor');
        if (ce && ce.config) {
            this.config = { ...ce.config };
        }
        document.addEventListener('config-change', (e) => {
            this.config = { ...e.detail };
            this._syncFields();
            this._refreshEstimate();
        });
        this.render();
        this.attachEventListeners();
        this._refreshEstimate();
    }

    async _refreshEstimate() {
        if (this._estimateTimer) clearTimeout(this._estimateTimer);
        this._estimateTimer = setTimeout(async () => {
            const cfg = this.config;
            const out = this.querySelector('#render-estimate');
            if (!out) return;
            if (!cfg.shader || !cfg.width || !cfg.height || !cfg.fps) {
                out.textContent = 'Estimate: pick a shader and resolution.';
                return;
            }
            const basename = (cfg.shader.split(/[\\/]/).pop() || '').replace(/\.glsl$/, '');
            const body = {
                shader_basename: basename,
                width: cfg.width, height: cfg.height,
                fps: cfg.fps, duration_sec: cfg.duration_sec || 10,
                tile_count: (cfg.tiles_x || 1) * (cfg.tiles_y || 1),
                ss_scale: cfg.ss_scale || 1.0,
                format: cfg.default_output_format || 'png',
                bit_depth: this._bitDepthInt(cfg.default_bit_depth),
            };
            try {
                const r = await fetch('/api/render/estimate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!r.ok) {
                    const detail = await r.json().catch(() => ({}));
                    throw new Error(detail.detail || `HTTP ${r.status}`);
                }
                this._renderEstimate(await r.json());
            } catch (err) {
                out.textContent = `Estimate failed: ${err.message}`;
            }
        }, 250);
    }

    _bitDepthInt(s) {
        if (s === '16f') return 16;
        if (s === '32f') return 32;
        return 8;
    }

    _renderEstimate(e) {
        const out = this.querySelector('#render-estimate');
        if (!out) return;
        const dt = (e.total_seconds / 60).toFixed(1);
        const sz = (e.output_bytes / (1024 ** 3)).toFixed(1);
        const hint = e.history_hit ? '' : ' (no prior render data)';
        const warn = (e.exceeds_time_threshold_1h || e.exceeds_size_threshold_50gb)
            ? ' ⚠ over budget' : '';
        out.innerHTML =
            `Estimate: ${e.frame_time_sec.toFixed(1)} s/frame · ` +
            `${e.total_frames} frames · ~${dt} min · ${sz} GB${warn}` +
            `<span style="color:#666;">${hint}</span>`;
    }

    render() {
        const preset = this.config.camera_mode || 'equirect';
        const bitDepth = String(this.config.default_bit_depth || '8');
        this.innerHTML = `
            <div class="output-panel">
                <div class="output-grid">

                    <div class="output-card">
                        <div class="output-card-title">Geometry</div>
                        <div class="output-row">
                            <label title="Spherical output unwraps the shader onto a 2:1 rectangle for VR / dome. Flat 16:9 is a quick preview only.">Preset</label>
                            <select id="output-preset" title="Spherical presets (equirect / LL180) are the production-quality options for CedarToy.">
                                <option value="equirect" ${preset==='equirect'?'selected':''}>Equirectangular 2:1</option>
                                <option value="ll180" ${preset==='ll180'?'selected':''}>LL180 dome</option>
                                <option value="2d" ${preset==='2d'?'selected':''}>Flat 16:9 (preview)</option>
                            </select>
                            <button class="btn btn-secondary" id="apply-preset"
                                    style="padding:2px 8px;font-size:11px;"
                                    title="Apply this preset's recommended resolution (e.g. 8192×4096 for equirect).">Apply preset</button>
                        </div>
                        <div class="output-row">
                            <label title="Output resolution in pixels. Equirect → 8192×4096 is a common stage; LL180 → 4096×4096.">Resolution</label>
                            <input id="out-width" type="number" value="${this.config.width||1920}" min="64" max="32768" title="Width in pixels.">
                            <span style="color:#666;">×</span>
                            <input id="out-height" type="number" value="${this.config.height||1080}" min="64" max="32768" title="Height in pixels.">
                        </div>
                        <div class="output-row">
                            <label title="Camera tilt for spherical projection, in degrees. 0° = horizon centered.">Tilt</label>
                            <input id="out-tilt" type="number" min="0" max="90" value="${this.config.camera_tilt_deg||0}" title="Camera tilt in degrees (0–90).">
                            <span style="color:#666;">°</span>
                        </div>
                    </div>

                    <div class="output-card">
                        <div class="output-card-title">Time</div>
                        <div class="output-row">
                            <label title="Frames per second. Standard film/broadcast rates: 23.976, 24, 25, 29.97, 30, 50, 59.94, 60. Decimals are honored — type any rate, or pick one from the list.">FPS</label>
                            <input id="out-fps" type="number" step="0.001" list="fps-options"
                                   value="${this.config.fps||60}" min="1" max="240"
                                   title="Frames per second. Standard rates listed; type any decimal.">
                            <datalist id="fps-options">
                                <option value="23.976"></option>
                                <option value="24"></option>
                                <option value="25"></option>
                                <option value="29.97"></option>
                                <option value="30"></option>
                                <option value="48"></option>
                                <option value="50"></option>
                                <option value="59.94"></option>
                                <option value="60"></option>
                                <option value="120"></option>
                            </datalist>
                        </div>
                        <div class="output-row">
                            <label title="Render duration in seconds. Total frames = FPS × Duration.">Duration</label>
                            <input id="out-duration" type="number" step="0.1" value="${this.config.duration_sec||10}" min="0.05" title="Render duration in seconds.">
                            <span style="color:#666;">s</span>
                        </div>
                    </div>

                    <div class="output-card">
                        <div class="output-card-title">Quality</div>
                        <div class="output-row">
                            <label title="Render each pixel at N× resolution then downsample. 2 quadruples render cost but greatly reduces aliasing.">Supersample</label>
                            <input id="out-ss" type="number" min="1" max="4" step="0.5" value="${this.config.ss_scale||1.0}" title="Supersampling scale (1 = off, 2 = 4× cost).">
                        </div>
                        <div class="output-row">
                            <label title="Number of sub-frames per output frame (motion blur). ≥ 2 enables motion blur; cost scales linearly.">Temporal</label>
                            <input id="out-temporal" type="number" min="1" max="64" value="${this.config.temporal_samples||1}" title="Temporal samples per frame (1 = off, ≥ 2 = motion blur).">
                        </div>
                        <div class="output-row">
                            <label title="Shutter angle 0–1. Only used when Temporal ≥ 2. 0.5 = 180° shutter (filmic default).">Shutter</label>
                            <input id="out-shutter" type="number" min="0" max="1" step="0.1" value="${this.config.shutter ?? 0.5}" title="Shutter angle (0–1). Used with Temporal ≥ 2.">
                        </div>
                        <div class="output-row">
                            <label title="Split rendering into tiles to fit huge frames in GPU memory. Total frames in the job = tiles_x × tiles_y × time_frames.">Tiling</label>
                            <input id="out-tiles-x" type="number" min="1" max="64" value="${this.config.tiles_x||1}" title="Horizontal tiles.">
                            <span style="color:#666;">×</span>
                            <input id="out-tiles-y" type="number" min="1" max="64" value="${this.config.tiles_y||1}" title="Vertical tiles.">
                        </div>
                    </div>

                    <div class="output-card">
                        <div class="output-card-title">File</div>
                        <div class="output-row">
                            <label title="Output image format. PNG is lossless 8-bit/16-bit; EXR carries 16- or 32-bit float for HDR pipelines.">Format</label>
                            <select id="out-format" title="PNG for delivery; EXR for HDR / compositing.">
                                <option value="png" ${this.config.default_output_format==='png'?'selected':''}>PNG</option>
                                <option value="exr" ${this.config.default_output_format==='exr'?'selected':''}>EXR</option>
                            </select>
                        </div>
                        <div class="output-row">
                            <label title="Color depth per channel. 8-bit suits PNG; 16-bit / 32-bit float require EXR.">Bit depth</label>
                            <select id="out-bit-depth" title="8-bit (PNG) / 16-bit float (EXR) / 32-bit float (EXR).">
                                <option value="8" ${bitDepth==='8'?'selected':''}>8-bit</option>
                                <option value="16f" ${bitDepth==='16f'?'selected':''}>16-bit float</option>
                                <option value="32f" ${bitDepth==='32f'?'selected':''}>32-bit float</option>
                            </select>
                        </div>
                    </div>

                </div>

                <div id="render-estimate" class="output-estimate">Estimate: pick a shader and resolution.</div>
            </div>
        `;
    }

    _syncFields() {
        // Update displayed values without rerendering (preserves focus).
        const set = (sel, val) => {
            const el = this.querySelector(sel);
            if (el && el.value != val) el.value = val;
        };
        set('#out-width', this.config.width || 1920);
        set('#out-height', this.config.height || 1080);
        set('#out-fps', this.config.fps || 60);
        set('#out-duration', this.config.duration_sec || 10);
        set('#out-tiles-x', this.config.tiles_x || 1);
        set('#out-tiles-y', this.config.tiles_y || 1);
        set('#out-tilt', this.config.camera_tilt_deg || 0);
        set('#out-ss', this.config.ss_scale || 1.0);
        set('#out-temporal', this.config.temporal_samples || 1);
        set('#out-shutter', this.config.shutter ?? 0.5);
        set('#out-format', this.config.default_output_format || 'png');
        set('#out-bit-depth', String(this.config.default_bit_depth || '8'));
        set('#output-preset', this.config.camera_mode || 'equirect');
    }

    attachEventListeners() {
        this.querySelector('#apply-preset')?.addEventListener('click', () => {
            const p = this.querySelector('#output-preset').value;
            const w = this.querySelector('#out-width');
            const h = this.querySelector('#out-height');
            if (p === 'equirect') { w.value = 8192; h.value = 4096; }
            else if (p === 'll180') { w.value = 4096; h.value = 4096; }
            else if (p === '2d') { w.value = 1920; h.value = 1080; }
            this._fire();
        });
        ['#output-preset', '#out-width', '#out-height', '#out-fps',
         '#out-duration', '#out-tiles-x', '#out-tiles-y', '#out-tilt',
         '#out-ss', '#out-temporal', '#out-shutter',
         '#out-format', '#out-bit-depth'].forEach(sel => {
            this.querySelector(sel)?.addEventListener('change', () => this._fire());
        });
    }

    _fire() {
        this._refreshEstimate();
        const update = {
            camera_mode: this.querySelector('#output-preset').value,
            width: parseInt(this.querySelector('#out-width').value),
            height: parseInt(this.querySelector('#out-height').value),
            fps: parseFloat(this.querySelector('#out-fps').value),
            duration_sec: parseFloat(this.querySelector('#out-duration').value),
            tiles_x: parseInt(this.querySelector('#out-tiles-x').value),
            tiles_y: parseInt(this.querySelector('#out-tiles-y').value),
            camera_tilt_deg: parseInt(this.querySelector('#out-tilt').value),
            ss_scale: parseFloat(this.querySelector('#out-ss').value),
            temporal_samples: parseInt(this.querySelector('#out-temporal').value),
            shutter: parseFloat(this.querySelector('#out-shutter').value),
            default_output_format: this.querySelector('#out-format').value,
            default_bit_depth: this.querySelector('#out-bit-depth').value,
        };
        const ce = document.querySelector('config-editor');
        if (ce && ce.config) {
            Object.assign(ce.config, update);
            if (typeof ce.saveToLocalStorage === 'function') ce.saveToLocalStorage();
            document.dispatchEvent(new CustomEvent('config-change', { detail: ce.config }));
        } else {
            Object.assign(this.config, update);
            this.dispatchEvent(new CustomEvent('config-change', {
                detail: this.config, bubbles: true,
            }));
        }
    }
}

customElements.define('output-panel', OutputPanel);
