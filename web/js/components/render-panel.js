import { api } from '../api.js';
import { wsClient } from '../websocket.js';

class RenderPanel extends HTMLElement {
    constructor() {
        super();
        this.state = 'idle'; // idle, rendering, complete, error
        this.progress = { frame: 0, total: 0, eta_sec: 0, elapsed_sec: 0 };
        this.logs = [];
        this.outputDir = null;
    }

    async connectedCallback() {
        this.render();
        this.attachEventListeners();

        // Connect WebSocket
        try {
            await wsClient.connect();
            this.setupWebSocketHandlers();
        } catch (err) {
            console.error('Failed to connect WebSocket:', err);
            this.addLog('WebSocket connection failed. Progress may not update.');
        }
    }

    render() {
        const progressPercent = this.progress.total > 0
            ? Math.round((this.progress.frame / this.progress.total) * 100)
            : 0;

        const etaMin = Math.floor(this.progress.eta_sec / 60);
        const etaSec = Math.floor(this.progress.eta_sec % 60);

        this.innerHTML = `
            <div class="render-panel-container">
                <div class="render-controls" style="display: flex; gap: 8px;">
                    <button class="btn btn-primary" id="start-render"
                        ${this.state === 'rendering' ? 'disabled' : ''}>
                        Start Render
                    </button>
                    <button class="btn btn-secondary" id="cancel-render"
                        ${this.state !== 'rendering' ? 'disabled' : ''}>
                        Cancel
                    </button>
                </div>

                ${this.state === 'rendering' ? `
                    <div class="progress" style="margin-top: 8px;">
                        <div class="progress-bar" style="width: ${progressPercent}%;">
                            ${progressPercent}%
                        </div>
                    </div>
                    <div style="margin-top: 8px; color: var(--text-secondary); font-size: 0.9rem;">
                        Frame ${this.progress.frame} / ${this.progress.total}
                        ${this.progress.eta_sec > 0 ? `| ETA: ${etaMin}:${etaSec.toString().padStart(2, '0')}` : ''}
                    </div>
                ` : ''}

                ${this.state === 'complete' ? `
                    <div style="margin-top: 8px; color: var(--success); font-weight: 500;">
                        ✓ Render complete! ${this.progress.frame} frames rendered
                        ${this.outputDir ? `<button class="btn btn-secondary" id="open-output" style="margin-left: 8px;">Open Folder</button>` : ''}
                    </div>
                ` : ''}

                ${this.state === 'error' ? `
                    <div style="margin-top: 8px; color: var(--error); font-weight: 500;">
                        ✗ Render failed - check logs below
                    </div>
                ` : ''}

                <div class="render-logs" style="margin-top: 16px; max-height: 150px; overflow-y: auto;
                    background: var(--bg-tertiary); padding: 8px; border-radius: 4px; font-family: monospace; font-size: 0.75rem;">
                    ${this.logs.map(log => `<div>${this.escapeHtml(log)}</div>`).join('')}
                    ${this.logs.length === 0 ? '<div style="color: var(--text-secondary);">No logs yet...</div>' : ''}
                </div>
            </div>
        `;

        // Re-attach event listeners after render
        this.attachEventListeners();
    }

    attachEventListeners() {
        const startBtn = this.querySelector('#start-render');
        const cancelBtn = this.querySelector('#cancel-render');
        const openBtn = this.querySelector('#open-output');

        if (startBtn && !startBtn.dataset.hasListener) {
            startBtn.dataset.hasListener = 'true';
            startBtn.addEventListener('click', async () => {
                await this.startRender();
            });
        }

        if (cancelBtn && !cancelBtn.dataset.hasListener) {
            cancelBtn.dataset.hasListener = 'true';
            cancelBtn.addEventListener('click', async () => {
                await this.cancelRender();
            });
        }

        if (openBtn) {
            openBtn.addEventListener('click', () => {
                if (this.outputDir) {
                    // Open folder in file explorer (Windows)
                    window.open(`file:///${this.outputDir}`, '_blank');
                }
            });
        }
    }

    async startRender() {
        const configEditor = document.querySelector('config-editor');
        const config = configEditor ? configEditor.getConfig() : {};

        // Validate shader is selected
        if (!config.shader) {
            alert('Please select a shader first!');
            return;
        }

        this.state = 'rendering';
        this.logs = [];
        this.progress = { frame: 0, total: 0, eta_sec: 0, elapsed_sec: 0 };
        this.outputDir = null;
        this.render();

        this.addLog('Starting render...');

        try {
            // Start render via API
            const result = await api.startRender(config);
            this.addLog(`Config saved to: ${result.config_file}`);

            // Send WebSocket message to start rendering
            wsClient.send({
                type: 'start_render',
                config_file: result.config_file
            });

        } catch (err) {
            this.state = 'error';
            this.addLog(`ERROR: ${err.message}`);
            this.render();
        }
    }

    async cancelRender() {
        this.addLog('Cancelling render...');

        try {
            await api.cancelRender();
            this.state = 'idle';
            this.addLog('Render cancelled');
            this.render();
        } catch (err) {
            this.addLog(`Failed to cancel: ${err.message}`);
        }
    }

    setupWebSocketHandlers() {
        wsClient.on('render_progress', (data) => {
            this.progress = data;
            this.render();
        });

        wsClient.on('render_log', (data) => {
            this.addLog(data.message);
        });

        wsClient.on('render_complete', (data) => {
            this.state = 'complete';
            if (data.output_dir) {
                this.outputDir = data.output_dir;
                this.addLog(`✓ Render complete! Output: ${data.output_dir}`);
            } else {
                this.addLog('✓ Render complete!');
            }
            this.render();
        });

        wsClient.on('render_error', (data) => {
            this.state = 'error';
            this.addLog(`✗ ERROR: ${data.message}`);
            if (data.details) {
                this.addLog(`  Details: ${data.details}`);
            }
            this.render();
        });

        wsClient.on('subscribed', (data) => {
            console.log('Subscribed to WebSocket channels:', data.channels);
        });
    }

    addLog(message) {
        const timestamp = new Date().toLocaleTimeString();
        this.logs.push(`[${timestamp}] ${message}`);

        // Keep last 100 logs
        if (this.logs.length > 100) {
            this.logs.shift();
        }

        this.render();

        // Auto-scroll logs to bottom
        const logsEl = this.querySelector('.render-logs');
        if (logsEl) {
            logsEl.scrollTop = logsEl.scrollHeight;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

customElements.define('render-panel', RenderPanel);
