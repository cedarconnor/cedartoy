class TransportStrip extends HTMLElement {
    constructor() {
        super();
        this.audio = null;        // HTMLAudioElement
        this.duration = 0;
        this._rafId = null;
        this._fft = new Float32Array(512);
        this._wave = new Float32Array(512);
        this._analyser = null;
        this._audioCtx = null;
    }

    connectedCallback() {
        this.render();
        this._attachListeners();
        document.addEventListener('project-loaded', (e) => this._onProjectLoaded(e.detail));
        document.addEventListener('transport-seek', (e) => this._seek(e.detail.t));
    }

    render() {
        this.innerHTML = `
            <div class="transport-strip">
                <button class="btn btn-primary" id="ts-play" disabled>▶</button>
                <span id="ts-time" style="font-family:monospace;font-size:12px;color:#aaa;width:90px;">--:-- / --:--</span>
                <span id="ts-readout" style="flex:1;color:#888;font-family:monospace;font-size:11px;text-align:right;">iBpm — iBeat — iBar — iEnergy — iSectionEnergy —</span>
            </div>
        `;
    }

    _attachListeners() {
        this.querySelector('#ts-play').addEventListener('click', () => this._togglePlay());
    }

    _onProjectLoaded(detail) {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        if (this.audio) { this.audio.pause(); this.audio = null; }
        if (this._audioCtx) { this._audioCtx.close(); this._audioCtx = null; this._analyser = null; }
        if (!detail || !detail.audio_url) {
            this.querySelector('#ts-play').disabled = true;
            this.querySelector('#ts-play').title = 'No audio in project';
            return;
        }
        this.audio = new Audio(detail.audio_url);
        this.audio.preload = 'auto';
        this.audio.addEventListener('loadedmetadata', () => {
            this.duration = this.audio.duration;
            this._updateTime(0);
            const btn = this.querySelector('#ts-play');
            btn.disabled = false;
            btn.title = '';
        });
        this.audio.addEventListener('ended', () => this._pause());
        this._updateBundleReadout(detail);
    }

    async _togglePlay() {
        if (!this.audio) return;
        if (this.audio.paused) await this._play();
        else this._pause();
    }

    async _play() {
        if (!this.audio) return;
        await this.audio.play();
        this.querySelector('#ts-play').textContent = '⏸';
        this._loop();
    }

    _pause() {
        if (!this.audio) return;
        this.audio.pause();
        this.querySelector('#ts-play').textContent = '▶';
        if (this._rafId) cancelAnimationFrame(this._rafId);
        this._rafId = null;
    }

    _seek(t) {
        if (!this.audio) return;
        const clamped = Math.max(0, Math.min(this.duration || t, t));
        this.audio.currentTime = clamped;
        this._tick();
    }

    _loop() {
        this._tick();
        this._rafId = requestAnimationFrame(() => this._loop());
    }

    _tick() {
        const t = this.audio ? this.audio.currentTime : 0;
        this._updateTime(t);
        document.dispatchEvent(new CustomEvent('transport-frame', { detail: { timeSec: t } }));
    }

    _updateTime(t) {
        const fmt = (s) => {
            const m = Math.floor(s / 60), ss = Math.floor(s % 60);
            return `${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
        };
        this.querySelector('#ts-time').textContent = `${fmt(t)} / ${fmt(this.duration || 0)}`;
    }

    _updateBundleReadout(detail) {
        // Placeholder; filled in by Task 7 when bundle is wired.
        this.querySelector('#ts-readout').textContent =
            'iBpm — iBeat — iBar — iEnergy — iSectionEnergy —';
    }
}

customElements.define('transport-strip', TransportStrip);
