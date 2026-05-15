class CueScrubber extends HTMLElement {
    constructor() {
        super();
        this.bundle = null;
        this.durationSec = 0;
        this._currentTime = 0;
    }

    connectedCallback() {
        document.addEventListener('project-loaded', (e) => {
            if (e.detail && e.detail.bundle_path) {
                this._loadBundle(e.detail.bundle_path);
            } else {
                this.bundle = null;
                this.durationSec = 0;
                this.render();
            }
        });
        document.addEventListener('preview-frame', (e) => {
            this._currentTime = e.detail.timeSec || 0;
            this._updateReadout();
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

    render() {
        if (!this.bundle || this.durationSec <= 0) {
            this.innerHTML = `<div class="cue-scrubber-empty">No bundle loaded.</div>`;
            return;
        }
        const W = 1200, H = 100;
        const t2x = (t) => (t / this.durationSec) * W;

        const sectionBlocks = (this.bundle.sections || []).map((s, i) => {
            const x = t2x(s.start), w = t2x(s.end) - x;
            const fill = i % 2 === 0 ? '#2a2a2a' : '#333';
            return `<rect x="${x}" y="0" width="${Math.max(0, w)}" height="20" fill="${fill}"/>
                    <text x="${x + 4}" y="14" fill="#aaa" font-size="10" pointer-events="none">${this._escape(s.label || '')}</text>`;
        }).join('');

        const beatTicks = (this.bundle.beats || []).map((b) => {
            const x = t2x(b.t);
            const tall = b.is_downbeat ? 18 : 10;
            return `<line x1="${x}" y1="20" x2="${x}" y2="${20 + tall}" stroke="#666" stroke-width="${b.is_downbeat ? 1.5 : 0.5}"/>`;
        }).join('');

        const kicks = ((this.bundle.drums || {}).kick || []).map((d) => {
            const x = t2x(d.t);
            return `<circle cx="${x}" cy="55" r="2" fill="#e88"/>`;
        }).join('');

        const energy = this.bundle.global_energy;
        let energyPath = '';
        if (energy && energy.values && energy.values.length > 1 && energy.hop_sec > 0) {
            const pts = energy.values.map((v, i) => {
                const t = i * energy.hop_sec;
                return `${t2x(t).toFixed(1)},${(92 - v * 30).toFixed(1)}`;
            }).join(' ');
            energyPath = `<polyline points="${pts}" stroke="#7ec97e" stroke-width="1" fill="none"/>`;
        }

        this.innerHTML = `
            <div class="cue-scrubber-host">
                <svg class="cue-scrubber-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
                    ${sectionBlocks}
                    ${beatTicks}
                    ${kicks}
                    ${energyPath}
                    <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" id="scrub-hit"/>
                </svg>
                <div class="cue-scrubber-readout" id="cue-readout">
                    iBpm — &nbsp; iBeat — &nbsp; iBar — &nbsp; iEnergy — &nbsp; iSectionEnergy —
                </div>
            </div>
        `;
        this._attachClickHandler();
    }

    _attachClickHandler() {
        const hit = this.querySelector('#scrub-hit');
        if (!hit) return;
        hit.addEventListener('click', (e) => {
            const rect = hit.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const t = (x / rect.width) * this.durationSec;
            this.dispatchEvent(new CustomEvent('scrubber-seek', {
                detail: { t }, bubbles: true,
            }));
        });
    }

    _updateReadout() {
        const out = this.querySelector('#cue-readout');
        if (!out || !this.bundle) return;
        const t = this._currentTime;
        const bpm = (this.bundle.tempo && this.bundle.tempo.bpm_global) || 0;
        const beats = this.bundle.beats || [];
        let beatPhase = 0, bar = 0;
        for (let i = 0; i < beats.length - 1; i++) {
            if (beats[i].t <= t && t < beats[i + 1].t) {
                const span = beats[i + 1].t - beats[i].t;
                beatPhase = span > 0 ? (t - beats[i].t) / span : 0;
                bar = beats[i].bar ?? 0;
                break;
            }
        }
        let energy = 0;
        const ge = this.bundle.global_energy;
        if (ge && ge.values && ge.hop_sec > 0) {
            const idx = Math.min(Math.floor(t / ge.hop_sec), ge.values.length - 1);
            if (idx >= 0) energy = ge.values[idx] ?? 0;
        }
        let sectionEnergy = 0;
        for (const s of (this.bundle.sections || [])) {
            if (s.start <= t && t < s.end) {
                sectionEnergy = s.energy_rank ?? 0;
                break;
            }
        }
        out.textContent =
            `iBpm ${bpm.toFixed(0)}  ` +
            `iBeat ${beatPhase.toFixed(2)}  ` +
            `iBar ${bar}  ` +
            `iEnergy ${energy.toFixed(2)}  ` +
            `iSectionEnergy ${sectionEnergy.toFixed(2)}`;
    }

    _escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }
}

customElements.define('cue-scrubber', CueScrubber);
