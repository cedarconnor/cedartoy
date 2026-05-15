class ProjectPanel extends HTMLElement {
    constructor() {
        super();
        this.project = null;
        this.loading = false;
        this.error = null;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
    }

    render() {
        const p = this.project;
        const banner = p && p.bundle_sha_matches_audio === false
            ? `<div class="project-warning">⚠ Bundle sha does not match audio — re-export from MusiCue, or proceed knowing the bundle was built against different audio.</div>`
            : '';

        let rows = '';
        if (p) {
            const audioName = p.audio_path
                ? p.audio_path.split(/[\\/]/).pop() : null;
            const bundleName = p.bundle_path
                ? p.bundle_path.split(/[\\/]/).pop() : null;
            const grammar = p.manifest ? p.manifest.grammar : 'unknown grammar';
            const stems = Object.keys(p.stems_paths || {});
            rows = `
                <div class="project-row">
                    ${audioName ? `✔ Audio: <code>${audioName}</code>` : '<span class="project-row-missing">No audio detected</span>'}
                </div>
                <div class="project-row">
                    ${bundleName ? `✔ Bundle: <code>${bundleName}</code> · ${grammar}` : '<span class="project-row-info">No bundle — raw FFT mode</span>'}
                </div>
                <div class="project-row">
                    ${stems.length ? `✔ Stems: ${stems.join(' / ')}` : '<span class="project-row-info">No stems</span>'}
                </div>
                <div class="project-row project-row-info">
                    Folder: <code>${p.folder}</code>
                </div>
            `;
            if (p.warnings && p.warnings.length) {
                rows += '<div class="project-row project-row-info">Warnings: ' +
                        p.warnings.map(w => `<div>• ${w}</div>`).join('') + '</div>';
            }
        }

        const errBlock = this.error
            ? `<div class="project-warning">${this.error}</div>` : '';

        this.innerHTML = `
            <div class="project-panel">
                <h3>Project</h3>
                <p style="color:#888;font-size:12px;margin-top:0;">
                    Paste a folder produced by MusiCue's "Send to CedarToy"
                    (or any audio / bundle path inside such a folder).
                </p>
                <input type="text" id="project-path-input"
                       placeholder="D:\\path\\to\\my_song\\"
                       value="${p ? this._escape(p.folder) : ''}">
                <button class="btn btn-primary" id="project-load-btn"
                        ${this.loading ? 'disabled' : ''}>
                    ${this.loading ? 'Loading…' : 'Load Project'}
                </button>
                ${errBlock}
                ${banner}
                ${rows}
            </div>
        `;
    }

    _escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }

    attachEventListeners() {
        this.querySelector('#project-load-btn')?.addEventListener('click', async () => {
            const input = this.querySelector('#project-path-input');
            const path = input?.value.trim();
            if (!path) return;
            this.loading = true;
            this.error = null;
            this.render();
            this.attachEventListeners();
            try {
                const resp = await fetch('/api/project/load', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path }),
                });
                if (!resp.ok) {
                    const detail = await resp.json().catch(() => ({}));
                    throw new Error(detail.detail || `HTTP ${resp.status}`);
                }
                this.project = await resp.json();
                this.dispatchEvent(new CustomEvent('project-loaded', {
                    detail: this.project, bubbles: true,
                }));
            } catch (e) {
                this.error = `Failed to load project: ${e.message}`;
            } finally {
                this.loading = false;
                this.render();
                this.attachEventListeners();
            }
        });
    }
}

customElements.define('project-panel', ProjectPanel);
