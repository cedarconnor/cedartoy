class TransportStrip extends HTMLElement {
    constructor() {
        super();
        this.audio = null;
        this.duration = 0;
        this.bundle = null;
        this._rafId = null;
        this._fft = new Uint8Array(512);
        this._wave = new Uint8Array(512);
        this._analyser = null;
        this._audioCtx = null;
    }

    connectedCallback() {
        this.render();
        this._attachListeners();
        document.addEventListener('project-loaded', (e) => this._onProjectLoaded(e.detail));
        document.addEventListener('transport-seek', (e) => this._seek(e.detail.t));
        document.addEventListener('keydown', (e) => this._onKey(e));
    }

    _onKey(e) {
        // Only when focus is on body or transport-strip itself — never in inputs/textareas.
        const t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
            return;
        }
        if (e.code === 'Space') {
            e.preventDefault();
            this._togglePlay();
        } else if (e.code === 'ArrowLeft') {
            e.preventDefault();
            this._seek((this.audio?.currentTime || 0) - 1);
        } else if (e.code === 'ArrowRight') {
            e.preventDefault();
            this._seek((this.audio?.currentTime || 0) + 1);
        } else if (e.code === 'BracketLeft') {
            e.preventDefault();
            this._jumpSection(-1);
        } else if (e.code === 'BracketRight') {
            e.preventDefault();
            this._jumpSection(+1);
        }
    }

    _jumpSection(dir) {
        if (!this.audio || !this.bundle?.sections?.length) return;
        const t = this.audio.currentTime;
        const starts = this.bundle.sections.map(s => s.start);
        let target = null;
        if (dir < 0) {
            target = [...starts].reverse().find(s => s < t - 0.1) ?? 0;
        } else {
            target = starts.find(s => s > t + 0.1) ?? t;
        }
        this._seek(target);
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

    async _onProjectLoaded(detail) {
        if (this._rafId) cancelAnimationFrame(this._rafId);
        if (this.audio) { this.audio.pause(); this.audio = null; }
        if (this._audioCtx) { try { await this._audioCtx.close(); } catch {} this._audioCtx = null; this._analyser = null; }
        this.bundle = null;

        if (!detail || !detail.audio_url) {
            this.querySelector('#ts-play').disabled = true;
            this.querySelector('#ts-play').title = 'No audio in project';
            this._renderReadout();
            return;
        }

        this.audio = new Audio(detail.audio_url);
        this.audio.crossOrigin = 'anonymous';
        this.audio.preload = 'auto';
        this.audio.addEventListener('loadedmetadata', () => {
            this.duration = this.audio.duration;
            this._updateTime(0);
            const btn = this.querySelector('#ts-play');
            btn.disabled = false;
            btn.title = '';
        });
        this.audio.addEventListener('ended', () => this._pause());

        if (detail.bundle_path) {
            try {
                const r = await fetch(`/api/project/bundle?path=${encodeURIComponent(detail.bundle_path)}`);
                if (r.ok) this.bundle = await r.json();
            } catch {}
        }
        this._renderReadout();
    }

    async _togglePlay() {
        if (!this.audio) return;
        if (this.audio.paused) await this._play();
        else this._pause();
    }

    async _play() {
        if (!this.audio) return;
        // Lazily create AudioContext on first play (browsers require a user gesture).
        if (!this._audioCtx) {
            this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const src = this._audioCtx.createMediaElementSource(this.audio);
            this._analyser = this._audioCtx.createAnalyser();
            this._analyser.fftSize = 1024;
            src.connect(this._analyser);
            this._analyser.connect(this._audioCtx.destination);
        }
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
        this._emitAudioData();
        this._renderReadout(t);
        document.dispatchEvent(new CustomEvent('transport-frame', { detail: { timeSec: t } }));
    }

    _emitAudioData() {
        if (!this._analyser) return;
        this._analyser.getByteFrequencyData(this._fft);
        this._analyser.getByteTimeDomainData(this._wave);
        const fft = new Float32Array(512);
        const wave = new Float32Array(512);
        for (let i = 0; i < 512; i++) {
            fft[i] = (this._fft[i] || 0) / 255.0;
            wave[i] = ((this._wave[i] || 128) / 128.0) - 1.0;
        }
        document.dispatchEvent(new CustomEvent('audio-data', { detail: { fft, waveform: wave } }));
    }

    _updateTime(t) {
        const fmt = (s) => {
            const m = Math.floor(s / 60), ss = Math.floor(s % 60);
            return `${String(m).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
        };
        this.querySelector('#ts-time').textContent = `${fmt(t)} / ${fmt(this.duration || 0)}`;
    }

    _renderReadout(t = 0) {
        const out = this.querySelector('#ts-readout');
        if (!out) return;
        if (!this.bundle) {
            out.textContent = 'iBpm — iBeat — iBar — iEnergy — iSectionEnergy —';
            return;
        }
        const b = this.bundle;
        const bpm = (b.tempo && b.tempo.bpm_global) || 0;
        let beatPhase = 0, bar = 0;
        const beats = b.beats || [];
        for (let i = 0; i < beats.length - 1; i++) {
            if (beats[i].t <= t && t < beats[i + 1].t) {
                const span = beats[i + 1].t - beats[i].t;
                beatPhase = span > 0 ? (t - beats[i].t) / span : 0;
                bar = beats[i].bar ?? 0;
                break;
            }
        }
        let energy = 0;
        const ge = b.global_energy;
        if (ge && ge.values && ge.hop_sec > 0) {
            const idx = Math.min(Math.floor(t / ge.hop_sec), ge.values.length - 1);
            if (idx >= 0) energy = ge.values[idx] ?? 0;
        }
        let sectionEnergy = 0, sectionLabel = '—';
        for (const s of (b.sections || [])) {
            if (s.start <= t && t < s.end) {
                sectionEnergy = s.energy_rank ?? 0;
                sectionLabel = s.label || '—';
                break;
            }
        }
        out.textContent =
            `iBpm ${bpm.toFixed(0)} · iBeat ${beatPhase.toFixed(2)} · iBar ${bar} · ` +
            `iEnergy ${energy.toFixed(2)} · iSectionEnergy ${sectionEnergy.toFixed(2)} · ${sectionLabel}`;
    }
}

customElements.define('transport-strip', TransportStrip);
