/**
 * <reactivity-scorecard> — Validate mode "Score reactivity": renders a fast
 * 512×256 proxy of the current config on the server, scores how well the
 * frames follow the music, and shows the summary lines plus a compact
 * per-source bar list (best |r| per source, colored by visual feature).
 */
const FEATURE_COLORS = { L: '#e9c46a', M: '#4cc9f0', H: '#f072b6' };
const FEATURE_NAMES = { L: 'brightness', M: 'motion', H: 'hue' };
const POLL_MS = 1000;

class ReactivityScorecard extends HTMLElement {
    constructor() {
        super();
        this._jobId = null;
        this._timer = null;
    }

    connectedCallback() {
        this.render();
        this.querySelector('#rs-run').addEventListener('click', () => this.start());
    }

    disconnectedCallback() { clearTimeout(this._timer); }

    render() {
        const legend = Object.keys(FEATURE_COLORS).map((k) =>
            `<span class="rs-key"><i style="background:${FEATURE_COLORS[k]}"></i>${FEATURE_NAMES[k]}</span>`
        ).join('');
        this.innerHTML = `<div class="reactivity-scorecard">
            <div class="rs-row">
                <button id="rs-run" class="btn btn-secondary rs-run">Score reactivity</button>
                <span id="rs-status" class="rs-status">Renders a 512×256 proxy and checks it against the music.</span>
                <span class="rs-legend">${legend}</span>
            </div>
            <ul id="rs-summary" class="rs-summary"></ul>
            <div id="rs-bars" class="rs-bars"></div>
        </div>`;
    }

    _status(msg) { this.querySelector('#rs-status').textContent = msg; }

    async start() {
        const ce = document.querySelector('config-editor');
        const config = ce ? (ce.getConfig ? ce.getConfig() : ce.config) : {};
        if (!config || !config.shader) { this._status('Pick a shader first.'); return; }
        clearTimeout(this._timer);
        this.querySelector('#rs-run').disabled = true;
        this.querySelector('#rs-summary').innerHTML = '';
        this.querySelector('#rs-bars').innerHTML = '';
        this._status('Starting proxy render…');
        try {
            const r = await fetch('/api/scorecard/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config }),
            });
            const data = await r.json();
            if (!r.ok) throw new Error(typeof data.detail === 'string'
                ? data.detail : JSON.stringify(data.detail || data));
            this._jobId = data.job_id;
            this._poll();
        } catch (err) {
            this._fail(err.message);
        }
    }

    async _poll() {
        try {
            const r = await fetch(`/api/scorecard/${encodeURIComponent(this._jobId)}`,
                { cache: 'no-store' });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'scorecard lookup failed');
            if (d.status === 'complete') { this._show(d.scorecard); return; }
            if (d.status === 'error') { this._fail((d.error && d.error.message) || 'failed'); return; }
            if (d.status === 'cancelled') { this._fail('cancelled'); return; }
            const p = d.progress || {};
            this._status(p.total ? `Rendering proxy… ${p.frame}/${p.total}` : 'Rendering proxy…');
            this._timer = setTimeout(() => this._poll(), POLL_MS);
        } catch (err) {
            this._fail(err.message);
        }
    }

    _fail(msg) {
        this.querySelector('#rs-run').disabled = false;
        this._status(`Scorecard failed: ${msg}`);
    }

    _show(sc) {
        this.querySelector('#rs-run').disabled = false;
        const m = sc.meta || {};
        this._status(`${m.frames || '?'} frames scored (${sc.mode} signals)`);
        const ul = this.querySelector('#rs-summary');
        ul.innerHTML = '';
        for (const line of sc.summary || []) {
            const li = document.createElement('li');
            li.textContent = line;
            ul.appendChild(li);
        }
        this.querySelector('#rs-bars').innerHTML = this._bars(sc);
    }

    _bars(sc) {
        const active = sc.source_active || {};
        const rows = [];
        for (const [name, per] of Object.entries(sc.sources || {})) {
            if (active[name] === false) continue;
            let best = null;
            for (const f of Object.keys(FEATURE_COLORS)) {
                const e = per[f];
                if (e && e.r != null && (!best || Math.abs(e.r) > Math.abs(best.r))) {
                    best = { ...e, feature: f };
                }
            }
            rows.push({ name, best, abs: best ? Math.abs(best.r) : 0 });
        }
        rows.sort((a, b) => b.abs - a.abs);
        return rows.map(({ name, best, abs }) => {
            const color = best ? FEATURE_COLORS[best.feature] : '#445';
            const title = best
                ? `${name} → ${FEATURE_NAMES[best.feature]} r=${best.r.toFixed(2)} lag ${best.lag}` +
                  (best.via === 'onset' ? ' (onsets)' : '')
                : `${name}: no correlation`;
            return `<div class="rs-bar" title="${title}">
                <span class="rs-name">${name}</span>
                <span class="rs-track"><span class="rs-fill"
                    style="width:${(abs * 100).toFixed(0)}%;background:${color}"></span></span>
                <span class="rs-val">${best ? abs.toFixed(2) : '—'}</span></div>`;
        }).join('');
    }
}

customElements.define('reactivity-scorecard', ReactivityScorecard);
