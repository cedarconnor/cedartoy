/**
 * <cue-inspector> — playhead debug stack for Validate mode. Pure view of the
 * preview's 'cue-frame' event (masked values actually driving the shader).
 * Hosts a section-loop toggle that delegates to transport-strip.
 */
class CueInspector extends HTMLElement {
    constructor() {
        super();
        this._looping = false;
    }

    connectedCallback() {
        this.render();
        document.addEventListener('cue-frame', (e) => this._onFrame(e.detail));
        document.addEventListener('loop-region-change', (e) =>
            this._setLoopState(!!e.detail));
        this.querySelector('#ci-loop').addEventListener('click', () =>
            document.dispatchEvent(new CustomEvent('loop-toggle')));
    }

    render() {
        this.innerHTML = `<div class="cue-inspector">
            <div class="ci-row ci-head">
                <span id="ci-section" class="ci-section">section —</span>
                <span id="ci-mode" class="ci-mode">—</span>
                <button id="ci-loop" class="btn btn-secondary ci-loop">🔁 Loop section</button>
            </div>
            <div id="ci-uniforms" class="ci-row ci-uniforms"></div>
            <div id="ci-musical" class="ci-row ci-uniforms"></div>
            <div id="ci-tracks" class="ci-row ci-tracks"></div>
        </div>`;
    }

    _onFrame(d) {
        const u = d.uniforms || {};
        this.querySelector('#ci-section').textContent =
            `section ${d.sectionLabel} · bar ${u.bar} · beat ${(u.beat || 0).toFixed(2)}`;
        this.querySelector('#ci-mode').textContent = `mode ${d.bundleMode}`;
        this.querySelector('#ci-uniforms').textContent =
            `iBpm ${(u.bpm || 0).toFixed(0)} · iBeat ${(u.beat || 0).toFixed(2)} · ` +
            `iBar ${u.bar} · iSectionId ${u.sectionId} · ` +
            `iSectionEnergy ${(u.sectionEnergy || 0).toFixed(2)} · iEnergy ${(u.energy || 0).toFixed(2)}`;
        const f2 = (v) => (+v || 0).toFixed(2);
        const ttn = +u.timeToNextSection;
        this.querySelector('#ci-musical').textContent =
            `iBeatClock ${f2(u.beatClock)} · iBarPhase ${f2(u.barPhase)} · ` +
            `iPhrasePhase ${f2(u.phrasePhase)} · iSectionProgress ${f2(u.sectionProgress)} · ` +
            `iTimeToNextSection ${ttn >= 1000 || !isFinite(ttn) ? '—' : ttn.toFixed(1) + 's'} · ` +
            `iBuild ${f2(u.build)} · iKick ${f2(u.kick)} · iSnare ${f2(u.snare)} · iHat ${f2(u.hat)} · ` +
            `iBass ${f2(u.bass)} · iVocals ${f2(u.vocals)} · iDrums ${f2(u.drums)} · iOther ${f2(u.other)} · ` +
            `iBrightness ${f2(u.brightness)} · iEnergyFast ${f2(u.energyFast)} · iMusicTime ${f2(u.musicTime)}`;
        const tv = d.trackValues || {};
        this.querySelector('#ci-tracks').innerHTML = Object.keys(tv).map((k) => {
            const v = tv[k];
            const on = v > 0.001 ? ' ci-on' : '';
            return `<span class="ci-track${on}">${k.split('.').pop()} ${v.toFixed(2)}</span>`;
        }).join('');
    }

    _setLoopState(on) {
        this._looping = on;
        const btn = this.querySelector('#ci-loop');
        btn.classList.toggle('btn-primary', on);
        btn.textContent = on ? '🔁 Looping (clear)' : '🔁 Loop section';
    }
}

customElements.define('cue-inspector', CueInspector);
