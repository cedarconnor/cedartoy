import { api } from '../api.js';

class ShaderEditor extends HTMLElement {
    constructor() {
        super();
        this.editor = null;
        this.currentPath = null;
    }

    connectedCallback() {
        this.innerHTML = `
            <div class="shader-editor-container" style="display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
                width: 80%; max-width: 1000px; height: 80%; background: var(--bg-secondary); border-radius: var(--radius-md);
                padding: var(--spacing-lg); box-shadow: 0 4px 20px rgba(0,0,0,0.5); z-index: 1000;">
                <div class="editor-header" style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <h4 id="shader-title">Shader Editor</h4>
                    <div>
                        <button class="btn btn-primary" id="save-shader">Save</button>
                        <button class="btn btn-secondary" id="close-editor">Close</button>
                    </div>
                </div>
                <textarea id="shader-code" style="width: 100%; height: calc(100% - 60px);"></textarea>
            </div>
        `;

        // Wait for CodeMirror to be available
        if (typeof CodeMirror !== 'undefined') {
            this.initializeEditor();
        } else {
            setTimeout(() => this.initializeEditor(), 100);
        }

        this.attachEventListeners();

        // Listen for shader double-click to edit
        document.addEventListener('shader-edit', async (e) => {
            await this.loadShader(e.detail.path);
        });
    }

    initializeEditor() {
        if (this.editor) return;

        const textarea = this.querySelector('#shader-code');
        this.editor = CodeMirror.fromTextArea(textarea, {
            mode: 'text/x-c',
            theme: 'monokai',
            lineNumbers: true,
            indentUnit: 4,
            tabSize: 4,
            indentWithTabs: false,
            lineWrapping: false
        });

        this.editor.setSize('100%', 'calc(100% - 60px)');
    }

    async loadShader(path) {
        this.currentPath = path;

        try {
            const data = await api.getShader(path);

            if (this.editor) {
                this.editor.setValue(data.source);
                this.querySelector('#shader-title').textContent = `Editing: ${path}`;
                this.querySelector('.shader-editor-container').style.display = 'block';
            }
        } catch (err) {
            console.error('Failed to load shader:', err);
            alert('Failed to load shader: ' + err.message);
        }
    }

    attachEventListeners() {
        const saveBtn = this.querySelector('#save-shader');
        const closeBtn = this.querySelector('#close-editor');

        if (saveBtn) {
            saveBtn.addEventListener('click', async () => {
                if (!this.currentPath || !this.editor) return;

                const source = this.editor.getValue();

                try {
                    await fetch(`/api/shaders/save`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: this.currentPath, source })
                    });

                    alert('Shader saved successfully!');

                    // Reload preview
                    document.dispatchEvent(new CustomEvent('shader-select', {
                        detail: { path: this.currentPath },
                        bubbles: true,
                        composed: true
                    }));
                } catch (err) {
                    console.error('Failed to save:', err);
                    alert('Failed to save shader: ' + err.message);
                }
            });
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this.querySelector('.shader-editor-container').style.display = 'none';
            });
        }
    }
}

customElements.define('shader-editor', ShaderEditor);
