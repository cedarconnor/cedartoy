import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js';

class PreviewPanel extends HTMLElement {
    constructor() {
        super();
        this.renderer = null;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();

        const canvas = this.querySelector('#preview-canvas');
        this.renderer = new ShaderRenderer(canvas);

        document.addEventListener('shader-select', async (e) => {
            await this.loadShader(e.detail.path);
        });

        document.addEventListener('audio-data', (e) => {
            if (this.renderer) {
                this.renderer.updateAudioData(e.detail.fft, e.detail.waveform);
            }
        });

        // Transport-strip drives time; preview-panel is a passive subscriber.
        document.addEventListener('transport-frame', (e) => {
            if (this.renderer) {
                this.renderer.currentTime = e.detail.timeSec || 0;
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

    async loadShader(path) {
        try {
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.style.display = 'none';
            const shaderData = await api.getShader(path);
            this.renderer.compileShader(shaderData.source);
            this.renderer.render();
        } catch (err) {
            console.error('Failed to load shader:', err);
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.textContent = `Shader Error: ${err.message}`;
            errorDiv.style.display = 'block';
        }
    }
}

customElements.define('preview-panel', PreviewPanel);
