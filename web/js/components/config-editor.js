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
        // Stage 2 (Shader) — shader path + dynamic shader parameters live here.
        // Audio / Bundle attachment moved to project-panel (stage 1).
        // Output / tiling / quality / format moved to output-panel (stage 3).
        // Bundle / audio fields are kept on this.config for downstream consumers,
        // but the UI for them is no longer rendered here.
        this.innerHTML = `
            <div class="config-editor-container">
                <div class="config-header">
                    <h2>Shader</h2>
                    <div class="config-actions">
                        <button class="btn btn-secondary" id="export-btn">Export</button>
                    </div>
                </div>

                <div class="config-sections">
                    <div class="form-group">
                        <label class="form-label">Shader</label>
                        <input type="text" class="form-input" name="shader"
                               value="${this.config.shader || ''}"
                               placeholder="Select a shader from the browser">
                    </div>

                    <!-- Shader Parameters Section (Dynamic) -->
                    <div id="shader-params-container"></div>

                    <div class="form-group">
                        <label class="form-label">Output Directory</label>
                        <input type="text" class="form-input" name="output_dir"
                               value="${this.config.output_dir || 'output'}">
                    </div>

                    <div class="form-group">
                        <label class="form-label">Filename Pattern</label>
                        <input type="text" class="form-input" name="output_pattern"
                               value="${this.config.output_pattern || 'frame_{frame:05d}.{ext}'}">
                        <p class="form-hint">Variables: {frame}, {ext}, {buffer}</p>
                    </div>
                </div>
            </div>
        `;
    }

    async updateShaderParams() {
        let shaderPath = this.config.shader;
        const container = this.querySelector('#shader-params-container');
        if (!shaderPath || !container) return;

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
        // Form inputs - update config on change (excluding dynamic shader params).
        this.querySelectorAll('input:not(.shader-param-input)').forEach(input => {
            input.addEventListener('change', (e) => {
                const name = e.target.name;
                let value = e.target.value;
                if (e.target.type === 'number') {
                    value = parseFloat(value);
                }
                this.config[name] = value;
                this.saveToLocalStorage();
                this.dispatchEvent(new CustomEvent('config-change', {
                    detail: this.config, bubbles: true,
                }));
                if (name === 'shader') {
                    this.updateShaderParams();
                }
            });
        });

        // Export button.
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
