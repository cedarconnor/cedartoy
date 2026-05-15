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
            // Don't echo our own updates back into a render loop.
            this.config = { ...e.detail };
            this._syncFields();
        });
        this.render();
        this.attachEventListeners();
    }

    render() {
        const preset = this.config.camera_mode || 'equirect';
        const bitDepth = String(this.config.default_bit_depth || '8');
        this.innerHTML = `
            <div class="output-panel">
                <h3>Output</h3>

                <label>Output preset</label>
                <select id="output-preset">
                    <option value="equirect" ${preset==='equirect'?'selected':''}>Equirectangular 2:1 (recommended)</option>
                    <option value="ll180" ${preset==='ll180'?'selected':''}>LL180 dome</option>
                    <option value="2d" ${preset==='2d'?'selected':''}>Flat 16:9 (preview / test only)</option>
                </select>
                <button class="btn btn-secondary" id="apply-preset"
                        style="margin-left:8px;padding:4px 10px;font-size:12px;">Apply preset</button>

                <label>Resolution</label>
                <input id="out-width" type="number" value="${this.config.width||1920}" min="64" max="32768">
                <span style="color:#666;">x</span>
                <input id="out-height" type="number" value="${this.config.height||1080}" min="64" max="32768">

                <label>FPS</label>
                <input id="out-fps" type="number" value="${this.config.fps||60}" min="1" max="240">

                <label>Duration (seconds)</label>
                <input id="out-duration" type="number" step="0.1" value="${this.config.duration_sec||10}" min="0.05">

                <label>Tiling</label>
                <input id="out-tiles-x" type="number" min="1" max="64" value="${this.config.tiles_x||1}">
                <span style="color:#666;">x</span>
                <input id="out-tiles-y" type="number" min="1" max="64" value="${this.config.tiles_y||1}">

                <label>Camera tilt (degrees)</label>
                <input id="out-tilt" type="number" min="0" max="90" value="${this.config.camera_tilt_deg||0}">

                <label>Format</label>
                <select id="out-format">
                    <option value="png" ${this.config.default_output_format==='png'?'selected':''}>PNG</option>
                    <option value="exr" ${this.config.default_output_format==='exr'?'selected':''}>EXR</option>
                </select>
                <select id="out-bit-depth">
                    <option value="8" ${bitDepth==='8'?'selected':''}>8-bit</option>
                    <option value="16f" ${bitDepth==='16f'?'selected':''}>16-bit float</option>
                    <option value="32f" ${bitDepth==='32f'?'selected':''}>32-bit float</option>
                </select>

                <div id="render-estimate">Estimate: pending (Plan B-2)</div>
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
         '#out-format', '#out-bit-depth'].forEach(sel => {
            this.querySelector(sel)?.addEventListener('change', () => this._fire());
        });
    }

    _fire() {
        const update = {
            camera_mode: this.querySelector('#output-preset').value,
            width: parseInt(this.querySelector('#out-width').value),
            height: parseInt(this.querySelector('#out-height').value),
            fps: parseInt(this.querySelector('#out-fps').value),
            duration_sec: parseFloat(this.querySelector('#out-duration').value),
            tiles_x: parseInt(this.querySelector('#out-tiles-x').value),
            tiles_y: parseInt(this.querySelector('#out-tiles-y').value),
            camera_tilt_deg: parseInt(this.querySelector('#out-tilt').value),
            default_output_format: this.querySelector('#out-format').value,
            default_bit_depth: this.querySelector('#out-bit-depth').value,
        };
        // Push updates into the source-of-truth config-editor so localStorage
        // and downstream consumers stay in sync.
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
