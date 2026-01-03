import { api } from '../api.js';

class ConfigEditor extends HTMLElement {
    constructor() {
        super();
        this.config = {};
        this.schema = [];
    }

    async connectedCallback() {
        // Load schema and defaults
        const [schemaData, defaultsData] = await Promise.all([
            api.getSchema(),
            api.getDefaults()
        ]);

        this.schema = schemaData.options;

        // Load from localStorage or use defaults
        const savedConfig = this.loadFromLocalStorage();
        this.config = savedConfig || defaultsData.config;

        // Ensure camera settings have defaults if missing
        if (!this.config.camera_mode) {
            this.config.camera_mode = '2d';
        }
        // Ensure camera_tilt_deg exists at top level (not nested in camera_params)
        if (this.config.camera_tilt_deg === undefined) {
            // Try to migrate from old nested format
            if (this.config.camera_params?.tilt_deg !== undefined) {
                this.config.camera_tilt_deg = this.config.camera_params.tilt_deg;
            } else {
                this.config.camera_tilt_deg = 0;
            }
        }

        this.render();
        this.attachEventListeners();

        // Dispatch initial config to sync other components
        this.dispatchEvent(new CustomEvent('config-change', {
            detail: this.config,
            bubbles: true
        }));
    }

    render() {
        this.innerHTML = `
            <div class="config-editor-container">
                <div class="config-header">
                    <h2>Configuration</h2>
                    <div class="config-actions">
                        <button class="btn btn-secondary" id="export-btn">Export</button>
                    </div>
                </div>

                <div class="config-sections">
                    <div class="form-group">
                        <label class="form-label">Shader</label>
                        <input type="text" class="form-input" name="shader" value="${this.config.shader || ''}" placeholder="Select a shader from the browser">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Output Directory</label>
                        <input type="text" class="form-input" name="output_dir" value="${this.config.output_dir || 'output'}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Width</label>
                        <input type="number" class="form-input" name="width" value="${this.config.width || 1920}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Height</label>
                        <input type="number" class="form-input" name="height" value="${this.config.height || 1080}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">FPS</label>
                        <input type="number" class="form-input" name="fps" value="${this.config.fps || 60}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Duration (seconds)</label>
                        <input type="number" class="form-input" name="duration_sec" value="${this.config.duration_sec || 10}" step="0.1">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Camera Mode</label>
                        <select class="form-input" name="camera_mode">
                            <option value="2d" ${this.config.camera_mode === '2d' ? 'selected' : ''}>2D Standard</option>
                            <option value="equirect" ${this.config.camera_mode === 'equirect' ? 'selected' : ''}>Equirectangular</option>
                            <option value="ll180" ${this.config.camera_mode === 'll180' ? 'selected' : ''}>LL180 Dome</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Camera Tilt (degrees)</label>
                        <input type="number" class="form-input" name="camera_tilt_deg" value="${this.config.camera_tilt_deg || 0}" min="0" max="90" step="1">
                    </div>

                    <!-- Tiling Section -->
                    <details class="config-section">
                        <summary>Tiling (High-Res)</summary>
                        <div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">Tiles X</label>
                                    <input type="number" class="form-input" name="tiles_x" value="${this.config.tiles_x || 1}" min="1" max="16">
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Tiles Y</label>
                                    <input type="number" class="form-input" name="tiles_y" value="${this.config.tiles_y || 1}" min="1" max="16">
                                </div>
                            </div>
                            <p class="form-hint">Split render into tiles for very high resolutions. Total pixels = Width × Height × Tiles.</p>
                        </div>
                    </details>

                    <!-- Quality Section -->
                    <details class="config-section">
                        <summary>Quality</summary>
                        <div>
                            <div class="form-group">
                                <label class="form-label">Supersampling Scale</label>
                                <input type="number" class="form-input" name="ss_scale" value="${this.config.ss_scale || 1.0}" min="1" max="4" step="0.5">
                                <p class="form-hint">Render at higher resolution then downscale. 2 = 4x pixels.</p>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Temporal Samples</label>
                                <input type="number" class="form-input" name="temporal_samples" value="${this.config.temporal_samples || 1}" min="1" max="64">
                                <p class="form-hint">Motion blur samples per frame. Higher = smoother blur.</p>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Shutter Angle (0-1)</label>
                                <input type="number" class="form-input" name="shutter" value="${this.config.shutter || 0.5}" min="0" max="1" step="0.1">
                                <p class="form-hint">0 = no blur, 0.5 = 180°, 1 = full frame.</p>
                            </div>
                        </div>
                    </details>

                    <!-- Output Format Section -->
                    <details class="config-section">
                        <summary>Output Format</summary>
                        <div>
                            <div class="form-group">
                                <label class="form-label">Format</label>
                                <select class="form-input" name="default_output_format">
                                    <option value="png" ${this.config.default_output_format === 'png' ? 'selected' : ''}>PNG</option>
                                    <option value="exr" ${this.config.default_output_format === 'exr' ? 'selected' : ''}>EXR (HDR)</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Bit Depth</label>
                                <select class="form-input" name="default_bit_depth">
                                    <option value="8" ${this.config.default_bit_depth === '8' ? 'selected' : ''}>8-bit</option>
                                    <option value="16f" ${this.config.default_bit_depth === '16f' ? 'selected' : ''}>16-bit float</option>
                                    <option value="32f" ${this.config.default_bit_depth === '32f' ? 'selected' : ''}>32-bit float</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Filename Pattern</label>
                                <input type="text" class="form-input" name="output_pattern" value="${this.config.output_pattern || 'frame_{frame:05d}.{ext}'}">
                                <p class="form-hint">Variables: {frame}, {ext}, {buffer}</p>
                            </div>
                        </div>
                    </details>
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        // Form inputs - update config on change
        this.querySelectorAll('input').forEach(input => {
            input.addEventListener('change', (e) => {
                const name = e.target.name;
                let value = e.target.value;

                if (e.target.type === 'number') {
                    value = parseFloat(value);
                }

                // Store directly in config (no special nested handling needed)
                this.config[name] = value;
                this.saveToLocalStorage();
                this.dispatchEvent(new CustomEvent('config-change', { detail: this.config, bubbles: true }));
            });
        });

        // Select elements (camera_mode, etc.)
        this.querySelectorAll('select').forEach(select => {
            select.addEventListener('change', (e) => {
                const name = e.target.name;
                const value = e.target.value;
                this.config[name] = value;
                this.saveToLocalStorage();
                this.dispatchEvent(new CustomEvent('config-change', { detail: this.config, bubbles: true }));
            });
        });

        // Export button
        this.querySelector('#export-btn')?.addEventListener('click', async () => {
            const filename = prompt('Save as:', 'cedartoy.yaml');
            if (filename) {
                await api.saveConfig(this.config, filename);
                alert(`Saved to ${filename}`);
            }
        });
    }

    saveToLocalStorage() {
        localStorage.setItem('cedartoy_config', JSON.stringify(this.config));
    }

    loadFromLocalStorage() {
        const saved = localStorage.getItem('cedartoy_config');
        if (saved) {
            try {
                return JSON.parse(saved);
            } catch (err) {
                console.error('Failed to parse saved config:', err);
            }
        }
        return null;
    }

    getConfig() {
        return this.config;
    }
}

customElements.define('config-editor', ConfigEditor);
