/**
 * <shader-reactivity-drawer>
 *
 * Stage 2 paste-back surface for the Claude round-trip. Lives next to
 * the existing config-editor reactivity button. Three states:
 *   - idle           — empty textarea, ready for a paste.
 *   - compiled-ok    — last Apply succeeded; banner shows ✔ Compiled.
 *   - compile-failed — last Apply produced a GL error; shows the log
 *                      and offers a "Copy fix-it prompt" button.
 *
 * Subscribes to:
 *   - shader-compile-result {ok, log, path}: from preview-panel after
 *     every WebGL compile attempt.
 */
class ShaderReactivityDrawer extends HTMLElement {
    constructor() {
        super();
        this._state = 'idle';           // 'idle' | 'compiled-ok' | 'compile-failed'
        this._lastGlLog = '';
        this._lastAppliedPath = '';     // the _reactive.glsl path we just wrote
        this._lastBrokenGlsl = '';      // the GLSL we extracted from the paste
    }

    connectedCallback() {
        this.render();
        this._attach();
        document.addEventListener('shader-compile-result', (e) => this._onCompile(e.detail));
    }

    render() {
        this.innerHTML = `
            <div class="reactivity-drawer">
                <div class="reactivity-drawer-status" id="rd-status"></div>
                <textarea id="rd-input" rows="6"
                    placeholder="Paste Claude's reply here (including the &#96;&#96;&#96;glsl fence)..."></textarea>
                <div class="reactivity-drawer-actions">
                    <button class="btn btn-primary" id="rd-apply">Apply</button>
                    <button class="btn btn-secondary" id="rd-overwrite"
                        title="Replaces the original shader file. This can't be undone.">Apply over original</button>
                    <button class="btn btn-secondary" id="rd-fixit" disabled
                        title="Copy a prompt to Claude that bundles the broken GLSL + compile error.">📋 Copy fix-it prompt ▸</button>
                </div>
                <div class="reactivity-drawer-log" id="rd-log" hidden></div>
            </div>
        `;
    }

    _attach() {
        this.querySelector('#rd-apply').addEventListener('click', () => this._apply('sibling'));
        this.querySelector('#rd-overwrite').addEventListener('click', () => {
            if (confirm('Overwrite the original shader? This cannot be undone.')) {
                this._apply('overwrite');
            }
        });
        this.querySelector('#rd-fixit').addEventListener('click', () => this._copyFixitPrompt());
    }

    _extractGlsl(text) {
        if (!text) return null;
        const fence = text.match(/```(?:glsl)?\s*\n([\s\S]*?)```/i);
        if (fence) return fence[1].trim();
        const trimmed = text.trim();
        if (/^#version|^precision\b|^void\s+main\b/m.test(trimmed)) {
            return trimmed;
        }
        return null;
    }

    async _apply(mode) {
        const base = window.cedartoy?.currentShader;
        if (!base) {
            this._setStatus('error', 'Pick a shader before applying.');
            return;
        }
        const text = this.querySelector('#rd-input').value;
        const glsl = this._extractGlsl(text);
        if (!glsl) {
            this._setStatus('error',
                'Couldn’t find a ```glsl block in that paste. Paste the full reply (including the fence), or paste only the GLSL.');
            return;
        }
        this._lastBrokenGlsl = glsl;
        try {
            const r = await fetch('/api/shader/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ base, glsl, mode }),
            });
            if (!r.ok) {
                const detail = await r.json().catch(() => ({}));
                throw new Error(detail.detail || `HTTP ${r.status}`);
            }
            const { path } = await r.json();
            this._lastAppliedPath = path;
            // Trigger compile by selecting the new shader.
            // (shader-browser strips the shaders/ prefix; do the same here.)
            const display = path.startsWith('shaders/') ? path.slice('shaders/'.length) : path;
            document.dispatchEvent(new CustomEvent('shader-select', {
                detail: { path: display },
            }));
            this._setStatus('pending', `Compiling ${this._basename(path)}…`);
        } catch (e) {
            this._setStatus('error', `Apply failed: ${e.message}`);
        }
    }

    _onCompile(detail) {
        // Only react to the compile that matches what we just applied.
        if (!this._lastAppliedPath) return;
        const justApplied = this._lastAppliedPath.endsWith(detail.path)
            || (detail.path && detail.path.endsWith(this._basename(this._lastAppliedPath)));
        if (!justApplied) return;

        if (detail.ok) {
            this._state = 'compiled-ok';
            this._lastGlLog = '';
            this._setStatus('ok', `✔ Compiled · running ${this._basename(this._lastAppliedPath)}`);
            this.querySelector('#rd-log').hidden = true;
            this.querySelector('#rd-fixit').disabled = true;
        } else {
            this._state = 'compile-failed';
            this._lastGlLog = detail.log || '';
            this._setStatus('error', `✗ Compile failed · ${this._basename(this._lastAppliedPath)}`);
            const logEl = this.querySelector('#rd-log');
            logEl.textContent = this._lastGlLog;
            logEl.hidden = false;
            this.querySelector('#rd-fixit').disabled = false;
        }
    }

    async _copyFixitPrompt() {
        const base = window.cedartoy?.currentShader;
        if (!base || !this._lastBrokenGlsl || !this._lastGlLog) {
            this._setStatus('error', 'Apply a shader first.');
            return;
        }
        // Resolve the *original* base (strip _reactive suffix if user re-applied
        // over the sibling — we want the pristine original).
        const baseClean = base.replace(/_reactive\.glsl$/i, '.glsl');
        try {
            const r = await fetch('/api/reactivity/fixit-prompt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base: baseClean,
                    broken_glsl: this._lastBrokenGlsl,
                    gl_log: this._lastGlLog,
                }),
            });
            if (!r.ok) {
                const detail = await r.json().catch(() => ({}));
                throw new Error(detail.detail || `HTTP ${r.status}`);
            }
            const { prompt } = await r.json();
            try {
                await navigator.clipboard.writeText(prompt);
                this._setStatus('ok', '✔ Fix-it prompt copied — paste into Claude');
            } catch (e) {
                const blob = new Blob([prompt], { type: 'text/markdown' });
                window.open(URL.createObjectURL(blob), '_blank');
            }
        } catch (e) {
            this._setStatus('error', `Fix-it prompt failed: ${e.message}`);
        }
    }

    _setStatus(kind, msg) {
        const el = this.querySelector('#rd-status');
        if (!el) return;
        el.dataset.kind = kind;
        el.textContent = msg;
    }

    _basename(p) {
        return (p || '').split(/[\\/]/).pop();
    }
}

customElements.define('shader-reactivity-drawer', ShaderReactivityDrawer);
