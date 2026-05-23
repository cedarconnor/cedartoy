/**
 * <track-timeline> — multi-lane MusiCue track graph for Validate mode.
 * One lane per track (native shapes), per-lane Mute/Solo, shared playhead,
 * click-to-seek. Emits 'track-settings-change' {trackSettings, soloIds}.
 */
import { BAND_TRACKS } from '../webgl/cue-compose.js';

const LANE_ORDER = [
    ...Object.keys(BAND_TRACKS), 'tempo', 'sections', 'energy',
];
const W = 1200, LANE_H = 22;

class TrackTimeline extends HTMLElement {
    constructor() {
        super();
        this.timeline = null;            // /api/reactivity/track-timeline payload
        this.trackSettings = {};         // persisted mutes/gains
        this.soloIds = new Set();        // transient solo
        this.durationSec = 1;
        this._audioPath = null;
    }

    connectedCallback() {
        this.render();
        document.addEventListener('project-loaded', (e) => this._onProject(e.detail));
        document.addEventListener('transport-frame', (e) =>
            this._updatePlayhead(e.detail.timeSec || 0));
    }

    async _onProject(detail) {
        this._audioPath = detail?.audio_path || detail?.path || null;
        if (!this._audioPath) return;
        try {
            const r = await fetch('/api/reactivity/track-timeline?audio='
                + encodeURIComponent(this._audioPath));
            if (!r.ok) { this._renderEmpty('No bundle for this audio'); return; }
            this.timeline = await r.json();
            this.durationSec = this.timeline.duration_sec || 1;
            this.draw();
        } catch (err) {
            this._renderEmpty('Timeline load failed');
        }
    }

    render() {
        this.innerHTML = `<div class="track-timeline" id="tt-root">
            <div class="tt-empty">Load a project to see tracks.</div></div>`;
    }
    _renderEmpty(msg) {
        this.querySelector('#tt-root').innerHTML = `<div class="tt-empty">${msg}</div>`;
    }

    _t2x(t) { return (t / this.durationSec) * W; }

    draw() {
        const tl = this.timeline;
        const lanes = LANE_ORDER.filter((id) => tl.tracks[id]);
        const health = tl.health || {};
        const rows = lanes.map((id, i) => this._laneSVG(id, i, health)).join('');
        const totalH = lanes.length * LANE_H;
        this.querySelector('#tt-root').innerHTML = `
            <div class="tt-grid">
              <div class="tt-gutters">
                ${lanes.map((id) => this._gutter(id)).join('')}
              </div>
              <svg class="tt-svg" viewBox="0 0 ${W} ${totalH}" preserveAspectRatio="none">
                ${rows}
                <line id="tt-playhead" x1="0" y1="0" x2="0" y2="${totalH}"
                      stroke="#e94560" stroke-width="2"/>
                <rect id="tt-hit" x="0" y="0" width="${W}" height="${totalH}"
                      fill="transparent" style="cursor:pointer"/>
              </svg>
            </div>`;
        this._attach(lanes);
    }

    _gutter(id) {
        const muted = this._isMuted(id);
        const soloed = this.soloIds.has(id);
        const cs = this.trackSettings[id] || {};
        const g = cs.gain == null ? 1 : cs.gain;
        const th = cs.threshold || 0;
        const sm = cs.smoothing || 0;
        return `<div class="tt-gutter${muted ? ' dim' : ''}" data-track="${id}">
            <span class="tt-name">${id}</span>
            <button data-action="mute" data-track="${id}"
                class="tt-btn${muted ? ' on' : ''}">M</button>
            <button data-action="solo" data-track="${id}"
                class="tt-btn${soloed ? ' on' : ''}">S</button>
            <div class="tt-cal">
              <label>g<input type="range" data-action="gain" data-track="${id}"
                 min="0" max="4" step="0.1" value="${g}"></label>
              <label>t<input type="range" data-action="threshold" data-track="${id}"
                 min="0" max="1" step="0.05" value="${th}"></label>
              <label>s<input type="range" data-action="smoothing" data-track="${id}"
                 min="0" max="1" step="0.05" value="${sm}"></label>
            </div></div>`;
    }

    _laneSVG(id, i, health) {
        const y0 = i * LANE_H, mid = y0 + LANE_H / 2;
        const t = this.timeline.tracks[id];
        const dim = this._isMuted(id) ? ' opacity="0.3"' : '';
        let body = '';
        if (t.onsets) {
            body = t.onsets.map((o) =>
                `<line x1="${this._t2x(o.t)}" y1="${y0 + LANE_H - o.strength * (LANE_H - 4)}"
                   x2="${this._t2x(o.t)}" y2="${y0 + LANE_H - 2}" stroke="#8ad"/>`).join('');
        } else if (t.blocks) {
            body = t.blocks.map((b, k) =>
                `<rect x="${this._t2x(b.start)}" y="${y0 + 2}"
                   width="${this._t2x(b.end) - this._t2x(b.start)}" height="${LANE_H - 4}"
                   fill="${k % 2 ? '#334' : '#2a2a3a'}"/>
                 <text x="${this._t2x(b.start) + 3}" y="${mid + 3}" font-size="9"
                   fill="#9ab">${b.label}</text>`).join('');
        } else if (t.beats) {
            body = t.beats.map((b) =>
                `<line x1="${this._t2x(b.t)}" y1="${b.isDownbeat ? y0 + 2 : mid}"
                   x2="${this._t2x(b.t)}" y2="${y0 + LANE_H - 2}" stroke="#667"/>`).join('');
        } else if (t.curve && t.curve.values.length) {
            const hop = t.curve.hop_sec || 0;
            const pts = t.curve.values.map((v, k) =>
                `${this._t2x(k * hop)},${y0 + LANE_H - v * (LANE_H - 4)}`).join(' ');
            body = `<polyline points="${pts}" fill="none" stroke="#7ec97e"/>`;
        }
        const noData = (t.onsets && !t.onsets.length)
            || (t.curve && !t.curve.values.length);
        const flag = noData ? `<text x="4" y="${mid + 3}" font-size="9"
            fill="#a55">no data</text>` : '';
        return `<g${dim}>${body}${flag}
            <line x1="0" y1="${y0 + LANE_H}" x2="${W}" y2="${y0 + LANE_H}"
              stroke="#222"/></g>`;
    }

    _attach(lanes) {
        this.querySelectorAll('.tt-btn').forEach((btn) =>
            btn.addEventListener('click', () => this._toggle(
                btn.dataset.action, btn.dataset.track)));
        this.querySelectorAll('.tt-cal input').forEach((inp) =>
            inp.addEventListener('input', () => this._calibrate(
                inp.dataset.action, inp.dataset.track, parseFloat(inp.value))));
        const hit = this.querySelector('#tt-hit');
        hit.addEventListener('click', (e) => {
            const rect = hit.getBoundingClientRect();
            const t = ((e.clientX - rect.left) / rect.width) * this.durationSec;
            document.dispatchEvent(new CustomEvent('transport-seek', { detail: { t } }));
        });
    }

    _isMuted(id) {
        if (this.soloIds.size) return !this.soloIds.has(id);
        return !!(this.trackSettings[id] && this.trackSettings[id].mute);
    }

    _toggle(action, id) {
        if (action === 'mute') {
            const cur = this.trackSettings[id] || {};
            this.trackSettings[id] = { ...cur, mute: !cur.mute };
        } else {
            if (this.soloIds.has(id)) this.soloIds.delete(id);
            else this.soloIds.add(id);
        }
        this.draw();
        document.dispatchEvent(new CustomEvent('track-settings-change', {
            detail: { trackSettings: this.trackSettings, soloIds: this.soloIds },
        }));
    }

    _calibrate(field, id, value) {
        const cur = this.trackSettings[id] || {};
        this.trackSettings[id] = { ...cur, [field]: value };
        // Do NOT redraw here — re-rendering mid-drag drops slider focus, and
        // lane shapes don't depend on calibration values.
        document.dispatchEvent(new CustomEvent('track-settings-change', {
            detail: { trackSettings: this.trackSettings, soloIds: this.soloIds },
        }));
    }

    _updatePlayhead(t) {
        const ph = this.querySelector('#tt-playhead');
        if (ph) { const x = this._t2x(t); ph.setAttribute('x1', x); ph.setAttribute('x2', x); }
    }
}

customElements.define('track-timeline', TrackTimeline);
