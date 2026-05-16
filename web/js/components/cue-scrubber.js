class CueScrubber extends HTMLElement {
    constructor() {
        super();
        this.bundle = null;
        this.peaks = null;          // array of 1000 floats from /api/project/waveform
        this.durationSec = 0;
        this._currentTime = 0;
    }

    connectedCallback() {
        document.addEventListener('project-loaded', (e) => {
            this.bundle = null;
            this.peaks = null;
            this.durationSec = 0;
            if (e.detail) {
                if (e.detail.bundle_path) this._loadBundle(e.detail.bundle_path);
                if (e.detail.audio_path)  this._loadPeaks(e.detail.audio_path);
            }
            this.render();
        });
        document.addEventListener('transport-frame', (e) => {
            this._currentTime = e.detail.timeSec || 0;
            this._updatePlayhead();
        });
        this.render();
    }

    async _loadBundle(path) {
        try {
            const r = await fetch(`/api/project/bundle?path=${encodeURIComponent(path)}`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            this.bundle = await r.json();
            this.durationSec = this.bundle.duration_sec || 0;
            this.render();
            this._attachClickHandler();
        } catch (e) {
            console.error('cue-scrubber bundle load failed', e);
            this.bundle = null;
            this.render();
        }
    }

    async _loadPeaks(audioPath) {
        try {
            const r = await fetch(`/api/project/waveform?path=${encodeURIComponent(audioPath)}&n=1000`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const body = await r.json();
            this.peaks = body.peaks;
            this.render();
            this._attachClickHandler();
        } catch (e) {
            console.error('cue-scrubber peaks load failed', e);
            this.peaks = null;
            this.render();
        }
    }

    render() {
        const haveData = (this.bundle && this.durationSec > 0) || (this.peaks && this.peaks.length);
        if (!haveData) {
            this.innerHTML = `<div class="cue-scrubber-empty">No project loaded.</div>`;
            return;
        }
        const W = 1200, H = 100;
        const dur = this.durationSec || 1;
        const t2x = (t) => (t / dur) * W;

        // Waveform underlay (peaks mirrored above and below the centerline).
        let wave = '';
        if (this.peaks && this.peaks.length) {
            const N = this.peaks.length;
            const pts = [];
            for (let i = 0; i < N; i++) {
                const x = (i / (N - 1)) * W;
                const v = Math.max(0, Math.min(1, this.peaks[i] || 0));
                pts.push(`${x.toFixed(1)},${(50 - v * 35).toFixed(1)}`);
            }
            for (let i = N - 1; i >= 0; i--) {
                const x = (i / (N - 1)) * W;
                const v = Math.max(0, Math.min(1, this.peaks[i] || 0));
                pts.push(`${x.toFixed(1)},${(50 + v * 35).toFixed(1)}`);
            }
            wave = `<polygon points="${pts.join(' ')}" fill="#2d4a3a" stroke="none"/>`;
        }

        const sectionBlocks = (this.bundle?.sections || []).map((s, i) => {
            const x = t2x(s.start), w = t2x(s.end) - x;
            const fill = i % 2 === 0 ? '#2a2a2a' : '#333';
            return `<rect x="${x}" y="0" width="${Math.max(0, w)}" height="20" fill="${fill}" opacity="0.85"/>
                    <text x="${x + 4}" y="14" fill="#aaa" font-size="10" pointer-events="none">${this._escape(s.label || '')}</text>`;
        }).join('');

        const beatTicks = (this.bundle?.beats || []).map((b) => {
            const x = t2x(b.t);
            const tall = b.is_downbeat ? 18 : 10;
            return `<line x1="${x}" y1="20" x2="${x}" y2="${20 + tall}" stroke="#666" stroke-width="${b.is_downbeat ? 1.5 : 0.5}"/>`;
        }).join('');

        const kicks = ((this.bundle?.drums || {}).kick || []).map((d) => {
            const x = t2x(d.t);
            return `<circle cx="${x}" cy="55" r="2" fill="#e88"/>`;
        }).join('');

        const energy = this.bundle?.global_energy;
        let energyPath = '';
        if (energy && energy.values && energy.values.length > 1 && energy.hop_sec > 0) {
            const pts = energy.values.map((v, i) => {
                const t = i * energy.hop_sec;
                return `${t2x(t).toFixed(1)},${(92 - v * 30).toFixed(1)}`;
            }).join(' ');
            energyPath = `<polyline points="${pts}" stroke="#7ec97e" stroke-width="1" fill="none"/>`;
        }

        const playheadX = t2x(this._currentTime);

        this.innerHTML = `
            <div class="cue-scrubber-host">
                <svg class="cue-scrubber-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
                    ${wave}
                    ${sectionBlocks}
                    ${beatTicks}
                    ${kicks}
                    ${energyPath}
                    <line id="cue-playhead" x1="${playheadX}" y1="0" x2="${playheadX}" y2="${H}" stroke="#e94560" stroke-width="2"/>
                    <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" id="scrub-hit"/>
                </svg>
            </div>
        `;
        this._attachClickHandler();
    }

    _updatePlayhead() {
        const line = this.querySelector('#cue-playhead');
        if (!line || !this.durationSec) return;
        const x = (this._currentTime / this.durationSec) * 1200;
        line.setAttribute('x1', x);
        line.setAttribute('x2', x);
    }

    _attachClickHandler() {
        const hit = this.querySelector('#scrub-hit');
        if (!hit) return;
        hit.onclick = (e) => {
            const rect = hit.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const t = (x / rect.width) * (this.durationSec || 1);
            document.dispatchEvent(new CustomEvent('transport-seek', { detail: { t } }));
        };
    }

    _escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }
}

customElements.define('cue-scrubber', CueScrubber);
