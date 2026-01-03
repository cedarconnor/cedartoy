import { api } from '../api.js';
import { ShaderRenderer } from '../webgl/renderer.js';

class PreviewPanel extends HTMLElement {
    constructor() {
        super();
        this.renderer = null;
        this.duration = 10.0;
        this.playing = false;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();

        // Initialize WebGL
        const canvas = this.querySelector('#preview-canvas');
        this.renderer = new ShaderRenderer(canvas);

        // Listen for shader selection
        document.addEventListener('shader-select', async (e) => {
            await this.loadShader(e.detail.path);
        });

        // Listen for audio data updates
        document.addEventListener('audio-data', (e) => {
            if (this.renderer) {
                this.renderer.updateAudioData(e.detail.fft, e.detail.waveform);
            }
        });

        // Sync camera settings with config editor
        document.addEventListener('config-change', (e) => {
            const config = e.detail;
            const modeMap = { '2d': 0, 'equirect': 1, 'll180': 2 };

            if (config.camera_mode && this.renderer) {
                const modeIndex = modeMap[config.camera_mode] || 0;
                this.renderer.cameraMode = modeIndex;
                const cameraModeSelect = this.querySelector('#camera-mode');
                if (cameraModeSelect) cameraModeSelect.value = modeIndex;
            }

            // Support both new flat format (camera_tilt_deg) and old nested format
            const tiltValue = config.camera_tilt_deg ?? config.camera_params?.tilt_deg;
            if (tiltValue !== undefined && this.renderer) {
                this.renderer.cameraTilt = tiltValue;
                const cameraTiltSlider = this.querySelector('#camera-tilt');
                const tiltDisplay = this.querySelector('#tilt-display');
                if (cameraTiltSlider) cameraTiltSlider.value = tiltValue;
                if (tiltDisplay) tiltDisplay.textContent = `${tiltValue}°`;
            }

            // Re-render with updated settings
            if (!this.playing && this.renderer) {
                this.renderer.render();
            }
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
                <div class="preview-controls" style="margin-top: 8px; display: flex; align-items: center; gap: 8px;">
                    <button class="btn btn-primary" id="play-btn">▶</button>
                    <input type="range" id="time-slider" min="0" max="1000" value="0"
                        style="flex: 1;">
                    <span id="time-display">00:00 / ${this.formatTime(this.duration)}</span>
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
        const playBtn = this.querySelector('#play-btn');
        const timeSlider = this.querySelector('#time-slider');
        const cameraModeSelect = this.querySelector('#camera-mode');
        const cameraTiltSlider = this.querySelector('#camera-tilt');
        const tiltDisplay = this.querySelector('#tilt-display');

        playBtn.addEventListener('click', () => {
            this.togglePlay();
        });

        timeSlider.addEventListener('input', (e) => {
            const time = (parseFloat(e.target.value) / 1000) * this.duration;
            this.renderer.seek(time);
            this.updateTimeDisplay();

            // Emit seek event for audio sync
            document.dispatchEvent(new CustomEvent('preview-seek', {
                detail: { time }
            }));
        });

        // Camera mode control - update renderer and sync to config editor
        cameraModeSelect.addEventListener('change', (e) => {
            const modeIndex = parseInt(e.target.value);
            if (this.renderer) {
                this.renderer.cameraMode = modeIndex;
                // Re-render with new camera mode
                if (!this.playing) {
                    this.renderer.render();
                }
            }
            // Sync to config editor
            const modeNames = ['2d', 'equirect', 'll180'];
            const configEditor = document.querySelector('config-editor');
            if (configEditor) {
                configEditor.config.camera_mode = modeNames[modeIndex];
                configEditor.saveToLocalStorage();
                // Update config editor UI
                const selectEl = configEditor.querySelector('select[name="camera_mode"]');
                if (selectEl) selectEl.value = modeNames[modeIndex];
            }
        });

        // Camera tilt control - update renderer and sync to config editor
        cameraTiltSlider.addEventListener('input', (e) => {
            const tilt = parseFloat(e.target.value);
            tiltDisplay.textContent = `${tilt}°`;
            if (this.renderer) {
                this.renderer.cameraTilt = tilt;
                // Re-render with new tilt
                if (!this.playing) {
                    this.renderer.render();
                }
            }
            // Sync to config editor (use flat camera_tilt_deg format)
            const configEditor = document.querySelector('config-editor');
            if (configEditor) {
                configEditor.config.camera_tilt_deg = tilt;
                configEditor.saveToLocalStorage();
                // Update config editor UI
                const inputEl = configEditor.querySelector('input[name="camera_tilt_deg"]');
                if (inputEl) inputEl.value = tilt;
            }
        });

        // Update slider during playback
        setInterval(() => {
            if (this.playing && this.renderer) {
                const progress = (this.renderer.currentTime / this.duration) * 1000;
                timeSlider.value = Math.min(progress, 1000);
                this.updateTimeDisplay();
            }
        }, 100);
    }

    async loadShader(path) {
        try {
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.style.display = 'none';

            const shaderData = await api.getShader(path);
            this.renderer.compileShader(shaderData.source);
            this.renderer.render(); // Render first frame

            console.log('Shader loaded successfully');
        } catch (err) {
            console.error('Failed to load shader:', err);
            const errorDiv = this.querySelector('#preview-error');
            errorDiv.textContent = `Shader Error: ${err.message}`;
            errorDiv.style.display = 'block';
        }
    }

    togglePlay() {
        this.playing = !this.playing;
        const playBtn = this.querySelector('#play-btn');

        if (this.playing) {
            this.renderer.play();
            playBtn.textContent = '⏸';

            // Emit play event for audio sync
            document.dispatchEvent(new CustomEvent('preview-play'));
        } else {
            this.renderer.pause();
            playBtn.textContent = '▶';

            // Emit pause event for audio sync
            document.dispatchEvent(new CustomEvent('preview-pause'));
        }
    }

    updateTimeDisplay() {
        const timeDisplay = this.querySelector('#time-display');
        const current = this.renderer.currentTime;
        timeDisplay.textContent = `${this.formatTime(current)} / ${this.formatTime(this.duration)}`;
    }

    formatTime(seconds) {
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60);
        return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
    }
}

customElements.define('preview-panel', PreviewPanel);
