import { api } from '../api.js';

class ConfigEditor extends HTMLElement {
    constructor() {
        super();
        this.config = {};
        this.schema = [];
    }

    async connectedCallback() {
        const [schemaData, defaultsData] = await Promise.all([
            api.getSchema(),
            api.getDefaults()
        ]);

        this.schema = schemaData.options;
        const savedConfig = this.loadFromLocalStorage();
        this.config = savedConfig || defaultsData.config;

        if (!this.config.camera_mode) {
            this.config.camera_mode = '2d';
        }
        if (this.config.camera_tilt_deg === undefined) {
            if (this.config.camera_params?.tilt_deg !== undefined) {
                this.config.camera_tilt_deg = this.config.camera_params.tilt_deg;
            } else {
                this.config.camera_tilt_deg = 0;
            }
        }

        this.render();
        this.attachEventListeners();
        this.updateShaderParams();

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

                    <!-- Shader Parameters Section (Dynamic) -->
                    <div id="shader-params-container"></div>
                    
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
                                    <label class="form-label">Tile Count X</label>
                                    <input type="number" class="form-input" name="tiles_x" value="${this.config.tiles_x || 1}" min="1" max="64">
                                </div>
                                <div class="form-group">
                                    <label class="form-label">Tile Count Y</label>
                                    <input type="number" class="form-input" name="tiles_y" value="${this.config.tiles_y || 1}" min="1" max="64">
                                </div>
                            </div>
                            <p class="form-hint">Split image into X*Y tiles. Each tile renders a portion of the total Width x Height.</p>
                            <div id="tile-info-display" class="form-hint" style="margin-top: 5px; font-weight: bold;"></div>
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

    async updateShaderParams() {
        let shaderPath = this.config.shader;
        const container = this.querySelector('#shader-params-container');
        if (!shaderPath || !container) {
            console.warn('updateShaderParams aborted:', { shaderPath, container: !!container });
            return;
        }
        console.log('updateShaderParams calling for:', shaderPath);

        // Strip shaders/ prefix for API call if present
        if (shaderPath.startsWith('shaders/') || shaderPath.startsWith('shaders\\')) {
            shaderPath = shaderPath.substring(8);
        }

        try {
            const data = await api.getShader(shaderPath);
            console.log('updateShaderParams got data:', data);
            const params = data.metadata?.parameters || [];

            if (params.length === 0) {
                container.innerHTML = '';
                return;
            }

            // Ensure storage exists
            if (!this.config.shader_parameters) {
                this.config.shader_parameters = {};
            }

            let html = `
                <details class="config-section" open>
                    <summary>Shader Parameters</summary>
                    <div>
            `;

            params.forEach(p => {
                const val = this.config.shader_parameters[p.name] !== undefined
                    ? this.config.shader_parameters[p.name]
                    : p.default;

                html += `
                    <div class="form-group">
                        <label class="form-label">${p.label || p.name} (${p.min} - ${p.max})</label>
                        <input type="${p.type === 'float' || p.type === 'int' ? 'number' : 'text'}" 
                               class="form-input shader-param-input" 
                               data-param-name="${p.name}"
                               data-param-type="${p.type}"
                               value="${val}" 
                               step="${p.type === 'float' ? '0.01' : '1'}"
                               min="${p.min}" 
                               max="${p.max}">
                    </div>
                `;
            });

            html += `</div></details>`;
            container.innerHTML = html;

            container.querySelectorAll('.shader-param-input').forEach(input => {
                input.addEventListener('change', (e) => {
                    const name = e.target.dataset.paramName;
                    const type = e.target.dataset.paramType;
                    let val = e.target.value;

                    if (type === 'float') val = parseFloat(val);
                    else if (type === 'int') val = parseInt(val);

                    this.config.shader_parameters[name] = val;
                    this.saveToLocalStorage();
                    this.dispatchEvent(new CustomEvent('config-change', { detail: this.config, bubbles: true }));
                });
            });

        } catch (e) {
            console.error("Error loading shader params:", e);
        }
    }

    attachEventListeners() {
        // Tile calculation helper
        const updateTileInfo = () => {
            const w = parseInt(this.querySelector('input[name="width"]').value) || 0;
            const h = parseInt(this.querySelector('input[name="height"]').value) || 0;
            const tx = parseInt(this.querySelector('input[name="tiles_x"]').value) || 1;
            const ty = parseInt(this.querySelector('input[name="tiles_y"]').value) || 1;

            if (w && h && tx && ty) {
                const tw = Math.ceil(w / tx);
                const th = Math.ceil(h / ty);
                const total = tx * ty;
                const display = this.querySelector('#tile-info-display');
                if (display) {
                    let msg = `Total Tiles: ${total} | Tile Size: ${tw} x ${th} px`;
                    if (total > 256) {
                        msg += ' <span style="color: #ff4444;">(Warning: High tile count!)</span>';
                    }
                    if ((tw < 256 || th < 256) && total > 1) {
                        msg += ' <span style="color: #ffaa00;">(Warning: Small tiles inefficient)</span>';
                    }
                    display.innerHTML = msg;
                }
            }
        };

        // Call once to init
        updateTileInfo();

        // Form inputs - update config on change
        this.querySelectorAll('input:not(.shader-param-input)').forEach(input => {
            input.addEventListener('change', (e) => {
                const name = e.target.name;
                let value = e.target.value;

                if (e.target.type === 'number') {
                    value = parseFloat(value);
                }

                // Store directly in config (no special nested handling needed)
                this.config[name] = value;
                this.saveToLocalStorage();
                updateTileInfo();
                this.dispatchEvent(new CustomEvent('config-change', { detail: this.config, bubbles: true }));

                // Reload shader params if shader changes
                if (name === 'shader') {
                    this.updateShaderParams();
                }
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
