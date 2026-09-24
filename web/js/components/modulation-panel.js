/**
 * <modulation-panel>
 *
 * Stage 2 "Modulation" section (modulation matrix). One row per float
 * @param: base slider + its routes (source, depth, curve, attack/release in
 * beats, mode, enable, remove) + "+ route", and a live meter showing the
 * modulated value at the playhead.
 *
 * All shaping happens in Python: every change re-fetches
 * POST /api/modulation/series and re-broadcasts it as a 'modulation-series'
 * event (preview-panel binds the per-frame values at transport time).
 *
 * Routes persist as config.modulation_routes on <config-editor>, so they go
 * out with the Stage 4 render config. A missing key means "use the shader's
 * // @mod defaults"; once edited, the list (even empty) replaces them.
 */
import { modulatedValuesAt } from '../webgl/modulation-bind.js?v=1';
import { effectiveSettings } from '../webgl/cue-compose.js';

// Which shader config.modulation_routes was written for: routes edited on
// one shader must not leak onto the next one picked.
const OWNER_KEY = 'cedartoy_modulation_shader';

const NEW_ROUTE = {
    source: 'iKick', depth: 0.5, curve: 'linear',
    attack_beats: 0.0, release_beats: 0.5, mode: 'add', enabled: true,
};

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function fmt(v) {
    return (typeof v === 'number' && isFinite(v)) ? v.toFixed(3) : '—';
}

class ModulationPanel extends HTMLElement {
    constructor() {
        super();
        this._payload = null;        // last /api/modulation/series response
        this._params = [];           // float @params
        this._routes = [];           // effective routes (edited in place)
        this._routesFrom = 'shader';
        this._shader = null;
        this._solo = null;
        this._t = 0;
        this._timer = null;
        this._reqSeq = 0;
        this._lastBody = '';
        this._layoutKey = '';
        this._note = '';
    }

    connectedCallback() {
        this.innerHTML = '<div class="modulation-panel"></div>';
        document.addEventListener('config-change', (e) => this._onConfig(e.detail));
        document.addEventListener('track-settings-change', (e) => {
            this._solo = e.detail.soloIds || null;
            this._schedule();
        });
        document.addEventListener('project-loaded', () => {
            this._lastBody = '';
            this._schedule();
        });
        document.addEventListener('transport-frame', (e) => {
            this._t = e.detail.timeSec || 0;
            this._updateMeters();
        });
        const cfg = this._config();
        if (cfg.shader) this._onConfig(cfg);
    }

    // ---- config plumbing ----

    _ce() { return document.querySelector('config-editor'); }
    _config() { return (this._ce() && this._ce().config) || {}; }

    _save() {
        const ce = this._ce();
        if (ce && typeof ce.saveToLocalStorage === 'function') ce.saveToLocalStorage();
    }

    _onConfig(cfg) {
        if (!cfg) return;
        const shader = cfg.shader || null;
        if (shader !== this._shader) {
            this._shader = shader;
            let owner = null;
            try { owner = localStorage.getItem(OWNER_KEY); } catch (_) { /* no storage */ }
            if (cfg.modulation_routes !== undefined && owner !== shader) {
                delete cfg.modulation_routes;
                this._save();
            }
        }
        this._schedule();
    }

    _commitRoutes() {
        const cfg = this._config();
        cfg.modulation_routes = this._routes.map(r => ({ ...r }));
        try { localStorage.setItem(OWNER_KEY, cfg.shader || ''); } catch (_) { /* ignore */ }
        this._routesFrom = 'config';
        this._save();
        this._schedule();
    }

    _resetToDefaults() {
        const cfg = this._config();
        delete cfg.modulation_routes;
        this._save();
        this._layoutKey = '';
        this._schedule();
    }

    // ---- fetch ----

    _schedule() {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => this._fetch(), 200);
    }

    _requestBody(withMedia) {
        const cfg = this._config();
        const pp = document.querySelector('preview-panel');
        const body = {
            shader: cfg.shader,
            fps: (pp && pp._timelineFps) || 24.0,
            shader_parameters: cfg.shader_parameters || {},
            track_settings: effectiveSettings(cfg.track_settings || {}, this._solo),
            av_offset_ms: +cfg.av_offset_ms || 0,
        };
        if (cfg.modulation_routes !== undefined && cfg.modulation_routes !== null) {
            body.routes = cfg.modulation_routes;
        }
        if (withMedia) {
            if (cfg.bundle_path) body.bundle = cfg.bundle_path;
            else if (cfg.audio_path) body.audio = cfg.audio_path;
        }
        return body;
    }

    async _post(body) {
        const r = await fetch('/api/modulation/series', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!r.ok) {
            const detail = await r.json().catch(() => ({}));
            const err = new Error(typeof detail.detail === 'string'
                ? detail.detail : `HTTP ${r.status}`);
            err.status = r.status;
            throw err;
        }
        return r.json();
    }

    async _fetch() {
        const cfg = this._config();
        if (!cfg.shader) {
            this._payload = null;
            this._params = [];
            this._renderPanel();
            return;
        }
        const body = this._requestBody(true);
        const key = JSON.stringify(body);
        if (key === this._lastBody && this._payload) return;
        this._lastBody = key;
        const seq = ++this._reqSeq;
        let data = null;
        this._note = '';
        try {
            data = await this._post(body);
        } catch (e) {
            // Media not reachable (e.g. project not loaded this session):
            // still show params/routes without the series.
            if ((body.bundle || body.audio) && (e.status === 403 || e.status === 404)) {
                try {
                    data = await this._post(this._requestBody(false));
                    this._note = `Bundle unavailable (${e.message}); load the project to preview modulation.`;
                } catch (e2) { this._note = `Modulation failed: ${e2.message}`; }
            } else {
                this._note = `Modulation failed: ${e.message}`;
            }
        }
        if (seq !== this._reqSeq) return;          // superseded
        if (this._note) this._lastBody = '';      // retry next time (e.g. project loaded)
        this._payload = data;
        this._params = data ? data.params.filter(p => p.type === 'float') : [];
        this._routes = data ? data.routes.map(r => ({ ...r })) : [];
        this._routesFrom = data ? data.routes_from : 'shader';
        this._renderPanel();
        document.dispatchEvent(new CustomEvent('modulation-series', {
            detail: data && data.bundle_loaded ? data : null,
        }));
    }

    // ---- rendering ----

    _renderPanel() {
        const root = this.querySelector('.modulation-panel');
        if (!root) return;
        if (!this._params.length) {
            root.innerHTML = this._note
                ? `<p class="form-hint">${esc(this._note)}</p>` : '';
            this._layoutKey = '';
            return;
        }
        // Rebuild the DOM only when the structure changed so editing a field
        // doesn't lose focus on every re-fetch.
        const layoutKey = JSON.stringify([
            this._params.map(p => [p.name, p.min, p.max]),
            this._routes.map(r => [r.id, r.target]),
        ]);
        if (layoutKey !== this._layoutKey || !root.querySelector('.mod-section')) {
            this._layoutKey = layoutKey;
            root.innerHTML = this._html();
            this._attach(root);
        }
        this._syncBase();
        this._updateStatus();
        this._updateMeters();
    }

    /** Reflect base values edited elsewhere (config-editor inputs). */
    _syncBase() {
        const values = this._config().shader_parameters || {};
        for (const p of this._params) {
            const row = this.querySelector(`.mod-param[data-param="${CSS.escape(p.name)}"]`);
            if (!row) continue;
            const base = values[p.name] !== undefined ? values[p.name] : p.default;
            const slider = row.querySelector('.mod-base');
            if (slider && document.activeElement !== slider) slider.value = base;
            row.querySelector('.mod-base-val').textContent = fmt(+base);
        }
    }

    _sourceOptions(sel) {
        const sources = (this._payload && this._payload.mod_sources) || [];
        return sources.map(s =>
            `<option value="${esc(s)}"${s === sel ? ' selected' : ''}>${esc(s)}</option>`).join('');
    }

    _options(list, sel) {
        return list.map(s =>
            `<option value="${esc(s)}"${s === sel ? ' selected' : ''}>${esc(s)}</option>`).join('');
    }

    _routeHtml(r) {
        const curves = (this._payload && this._payload.curves) || ['linear'];
        const modes = (this._payload && this._payload.modes) || ['add', 'integrate'];
        return `
            <div class="mod-route${r.enabled ? '' : ' mod-route-off'}" data-route-id="${esc(r.id)}">
                <select class="form-select" data-k="source" title="Source">${this._sourceOptions(r.source)}</select>
                <input class="form-input" type="number" data-k="depth" step="0.05"
                       value="${r.depth}" title="Depth (param units; may be negative)">
                <select class="form-select" data-k="curve" title="Curve">${this._options(curves, r.curve)}</select>
                <label title="Attack, in beats (0 = instant)">A
                    <input class="form-input" type="number" data-k="attack_beats" min="0" step="0.125" value="${r.attack_beats}"></label>
                <label title="Release, in beats (0 = instant)">R
                    <input class="form-input" type="number" data-k="release_beats" min="0" step="0.125" value="${r.release_beats}"></label>
                <select class="form-select" data-k="mode"
                        title="add: base + depth·shaped, clamped to the param range. integrate: + depth·∫shaped dt (for phases; not clamped)">${this._options(modes, r.mode)}</select>
                <input type="checkbox" data-k="enabled" ${r.enabled ? 'checked' : ''} title="Enabled">
                <button class="btn btn-secondary mod-remove" title="Remove route">✕</button>
            </div>`;
    }

    _html() {
        const cfg = this._config();
        const values = cfg.shader_parameters || {};
        const rows = this._params.map(p => {
            const base = values[p.name] !== undefined ? values[p.name] : p.default;
            const step = Math.max((p.max - p.min) / 200, 0.0001);
            const routes = this._routes.filter(r => r.target === p.name);
            return `
                <div class="mod-param" data-param="${esc(p.name)}">
                    <div class="mod-param-head">
                        <span class="mod-param-label" title="${esc(p.name)}">${esc(p.label || p.name)}</span>
                        <input type="range" class="mod-base" min="${p.min}" max="${p.max}"
                               step="${step}" value="${base}" title="Base value">
                        <span class="mod-base-val">${fmt(+base)}</span>
                        <div class="mod-meter" title="Modulated value at the playhead">
                            <div class="mod-meter-fill"></div><div class="mod-meter-base"></div>
                        </div>
                        <span class="mod-live-val">—</span>
                    </div>
                    <div class="mod-routes">${routes.map(r => this._routeHtml(r)).join('')}</div>
                    <button class="btn btn-secondary mod-add">+ route</button>
                </div>`;
        }).join('');
        return `
            <details class="config-section mod-section" open>
                <summary>Modulation</summary>
                <div>
                    <div class="mod-status">
                        <span class="form-hint" id="mod-status-text"></span>
                        <button class="btn btn-secondary" id="mod-reset"
                            title="Discard edited routes and use the shader's // @mod defaults">Use shader defaults</button>
                    </div>
                    ${rows}
                </div>
            </details>`;
    }

    _updateStatus() {
        const el = this.querySelector('#mod-status-text');
        const reset = this.querySelector('#mod-reset');
        if (!el) return;
        const parts = [this._routesFrom === 'config'
            ? 'Routes: custom (saved with the render config).'
            : 'Routes: shader // @mod defaults (edit to override).'];
        if (this._payload && !this._payload.bundle_loaded && !this._note) {
            parts.push('No MusiCue bundle loaded: routes are kept but have nothing to follow.');
        }
        if (this._note) parts.push(this._note);
        el.textContent = parts.join(' ');
        if (reset) reset.disabled = this._routesFrom !== 'config';
    }

    _updateMeters() {
        if (!this._params.length) return;
        const cfg = this._config();
        const values = cfg.shader_parameters || {};
        const live = (this._payload && this._payload.bundle_loaded)
            ? modulatedValuesAt(this._payload, this._t) : {};
        for (const p of this._params) {
            const row = this.querySelector(`.mod-param[data-param="${CSS.escape(p.name)}"]`);
            if (!row) continue;
            const base = +(values[p.name] !== undefined ? values[p.name] : p.default);
            const v = live[p.name] !== undefined ? live[p.name] : base;
            const span = (p.max - p.min) || 1;
            const frac = x => Math.max(0, Math.min(1, (x - p.min) / span));
            row.querySelector('.mod-meter-fill').style.width = `${(frac(v) * 100).toFixed(1)}%`;
            row.querySelector('.mod-meter-base').style.left = `${(frac(base) * 100).toFixed(1)}%`;
            row.querySelector('.mod-live-val').textContent =
                live[p.name] !== undefined ? fmt(v) : '—';
        }
    }

    // ---- events ----

    _attach(root) {
        root.querySelector('#mod-reset')?.addEventListener('click', () => this._resetToDefaults());

        root.querySelectorAll('.mod-param').forEach(row => {
            const name = row.dataset.param;
            const slider = row.querySelector('.mod-base');
            slider.addEventListener('input', () => {
                const v = parseFloat(slider.value);
                row.querySelector('.mod-base-val').textContent = fmt(v);
                const cfg = this._config();
                if (!cfg.shader_parameters) cfg.shader_parameters = {};
                cfg.shader_parameters[name] = v;
                // Keep config-editor's numeric input in sync.
                const num = document.querySelector(
                    `.shader-param-input[data-param-name="${CSS.escape(name)}"]`);
                if (num) num.value = v;
                this._save();
                this._updateMeters();
                document.dispatchEvent(new CustomEvent('config-change', { detail: cfg }));
            });

            row.querySelector('.mod-add').addEventListener('click', () => {
                const id = `r${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
                this._routes.push({ ...NEW_ROUTE, id, target: name });
                this._layoutKey = '';
                this._commitRoutes();
                this._renderPanel();
            });

            row.querySelectorAll('.mod-route').forEach(rEl => {
                const route = this._routes.find(r => r.id === rEl.dataset.routeId);
                if (!route) return;
                rEl.querySelector('.mod-remove').addEventListener('click', () => {
                    this._routes = this._routes.filter(r => r !== route);
                    this._layoutKey = '';
                    this._commitRoutes();
                    this._renderPanel();
                });
                rEl.querySelectorAll('[data-k]').forEach(input => {
                    input.addEventListener('change', () => {
                        const k = input.dataset.k;
                        if (k === 'enabled') {
                            route.enabled = input.checked;
                            rEl.classList.toggle('mod-route-off', !input.checked);
                        } else if (k === 'depth' || k === 'attack_beats' || k === 'release_beats') {
                            let v = parseFloat(input.value);
                            if (!isFinite(v)) v = 0;
                            if (k !== 'depth') v = Math.max(0, v);
                            input.value = v;
                            route[k] = v;
                        } else {
                            route[k] = input.value;
                        }
                        this._commitRoutes();
                    });
                });
            });
        });
    }
}

customElements.define('modulation-panel', ModulationPanel);
