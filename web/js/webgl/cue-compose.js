/**
 * Browser-side select-and-sum composition. Mirrors cedartoy/musicue.py:
 * apply_setting + band-fill + masked uniforms. Contains NO evaluator logic —
 * it consumes the per-frame scalars shipped by /api/reactivity/track-timeline.
 * Parity with Python is locked by tests/test_tracks.py::
 * test_frame_data_composes_to_synth_output.
 */

export const BAND_RANGES = {
    low: [0, 32], low_mid: [32, 96], mid_hi: [96, 256], high: [256, 512],
};

export const BAND_TRACKS = {
    "drums.kick": "low", "drums.snare": "low_mid", "drums.tom": "low_mid",
    "drums.hat": "mid_hi", "drums.cymbal": "mid_hi", "drums.other": "mid_hi",
    "stem.vocals": "high", "stem.other": "high", "stem.bass": "low",
};

// iTimeToNextSection when there is no upcoming section / sections muted.
// Mirrors cedartoy/musicue.py::NO_NEXT_SECTION.
export const NO_NEXT_SECTION = 1000.0;

// Musical uniforms: [uniform name, frame_data.uniforms key, mask track, how].
// how: "mute" = zero on mute only; "setting" = applySetting (threshold/gain/
// mute); null track = unmasked. Mirrors musicue.py::_MUSICAL_MASK exactly.
export const MUSICAL_UNIFORMS = [
    ["iBeatClock", "beatClock", "tempo", "mute"],
    ["iBarPhase", "barPhase", "tempo", "mute"],
    ["iPhrasePhase", "phrasePhase", "tempo", "mute"],
    ["iSectionProgress", "sectionProgress", "sections", "mute"],
    ["iTimeToNextSection", "timeToNextSection", "sections", "mute"],
    ["iBuild", "build", null, null],
    ["iKick", "kick", "drums.kick", "setting"],
    ["iSnare", "snare", "drums.snare", "setting"],
    ["iHat", "hat", "drums.hat", "setting"],
    ["iBass", "bass", "stem.bass", "setting"],
    ["iVocals", "vocals", "stem.vocals", "setting"],
    ["iDrums", "drums", null, null],
    ["iOther", "other", "stem.other", "setting"],
    ["iBrightness", "brightness", null, null],
    ["iEnergyFast", "energyFast", "energy", "setting"],
    ["iMusicTime", "musicTime", null, null],
];

// Hann window of given width (matches numpy.hanning: 0 at both ends).
function hann(width) {
    const w = new Float32Array(width);
    if (width === 1) { w[0] = 1; return w; }
    for (let i = 0; i < width; i++) {
        w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (width - 1));
    }
    return w;
}
const ENVELOPES = Object.fromEntries(
    Object.entries(BAND_RANGES).map(([n, [s, e]]) => [n, hann(e - s)]));

// threshold -> gain -> mute (stateless; smoothing is Phase 4).
export function applySetting(value, setting) {
    if (!setting) return value;
    if (setting.mute) return 0.0;
    const threshold = setting.threshold || 0.0;
    const gain = setting.gain == null ? 1.0 : setting.gain;
    return Math.max(0.0, value - threshold) * gain;
}

// Effective per-frame series for one track: threshold -> one-pole smooth ->
// gain -> mute. Mirrors cedartoy/musicue.py::apply_settings_series.
export function applySettingsSeries(raw, setting) {
    const n = raw.length;
    const out = new Float32Array(n);
    if (!setting) { for (let i = 0; i < n; i++) out[i] = raw[i]; return out; }
    if (setting.mute) return out;                 // all zeros
    const threshold = setting.threshold || 0.0;
    const gain = setting.gain == null ? 1.0 : setting.gain;
    const a = setting.smoothing || 0.0;
    let prev = 0.0;
    for (let i = 0; i < n; i++) {
        const x = Math.max(0.0, raw[i] - threshold);
        const sm = i === 0 ? x : (1 - a) * x + a * prev;
        prev = sm;
        out[i] = sm * gain;
    }
    return out;
}

// Compose row 0 from already-effective per-track band scalars for one frame.
export function composeRow0FromValues(bandValues, sectionEnergy) {
    const row0 = new Float32Array(512);
    for (const [tid, band] of Object.entries(BAND_TRACKS)) {
        const v = bandValues[tid] || 0.0;
        if (v > 0) {
            const [s] = BAND_RANGES[band];
            const env = ENVELOPES[band];
            for (let i = 0; i < env.length; i++) row0[s + i] += env[i] * v;
        }
    }
    for (let i = 0; i < 512; i++) row0[i] = Math.min(1.0, row0[i] + 0.1 * (sectionEnergy || 0.0));
    return row0;
}

// Persisted track_settings + transient solo set -> effective per-track settings.
// If any track is soloed, every non-soloed track is muted for the live preview.
export function effectiveSettings(trackSettings, soloIds) {
    const solos = soloIds && soloIds.size ? soloIds : null;
    const out = {};
    const ids = new Set([...Object.keys(trackSettings || {}),
                         ...Object.keys(BAND_TRACKS),
                         ...(solos || [])]);
    for (const id of ids) {
        const base = (trackSettings && trackSettings[id]) || {};
        const muted = base.mute || (solos ? !solos.has(id) : false);
        out[id] = { ...base, mute: muted };
    }
    return out;
}

// Compose row 0 (512 bins) for frame f from per-frame track scalars + settings.
export function composeRow0(frameData, f, effSettings) {
    const row0 = new Float32Array(512);
    for (const [tid, band] of Object.entries(BAND_TRACKS)) {
        const arr = frameData.tracks[tid];
        const v = applySetting(arr ? arr[f] : 0.0, effSettings[tid]);
        if (v > 0) {
            const [s] = BAND_RANGES[band];
            const env = ENVELOPES[band];
            for (let i = 0; i < env.length; i++) row0[s + i] += env[i] * v;
        }
    }
    const secE = frameData.uniforms.sectionEnergy[f] || 0.0;
    for (let i = 0; i < 512; i++) row0[i] = Math.min(1.0, row0[i] + 0.1 * secE);
    return row0;
}

// Row 1 (heartbeat) — constant across bins, like the Python synth.
export function composeRow1(frameData, f) {
    const energy = frameData.uniforms.energy[f] || 0.0;
    const beat = frameData.uniforms.beat[f] || 0.0;
    const wave = Math.max(0, Math.min(1,
        0.5 + 0.5 * energy * Math.sin(2 * Math.PI * beat)));
    const row1 = new Float32Array(512);
    row1.fill(wave);
    return row1;
}

// Masked scalar uniforms for frame f. Keys: the Phase-1 six under their
// series names (bpm, beat, ...) plus every MUSICAL_UNIFORMS series key
// (beatClock, kick, musicTime, ...). Mirrors musicue.py::bundle_uniforms.
export function composeUniforms(frameData, f, effSettings) {
    const u = frameData.uniforms;
    const tempoOff = !!(effSettings["tempo"] && effSettings["tempo"].mute);
    const secOff = !!(effSettings["sections"] && effSettings["sections"].mute);
    const out = {
        bpm: tempoOff ? 0.0 : u.bpm[f],
        beat: tempoOff ? 0.0 : u.beat[f],
        bar: tempoOff ? 0 : u.bar[f],
        sectionEnergy: secOff ? 0.0
            : applySetting(u.sectionEnergy[f], effSettings["sections"]),
        sectionId: secOff ? 0 : u.sectionId[f],
        energy: applySetting(u.energy[f], effSettings["energy"]),
    };
    for (const [name, key, track, how] of MUSICAL_UNIFORMS) {
        const arr = u[key];
        // Older timelines (pre musical uniforms) lack the series: treat as
        // no-bundle values (0, "no next section", iMusicTime left unset so
        // the renderer falls back to iTime).
        if (!arr) {
            if (name === "iTimeToNextSection") out[key] = NO_NEXT_SECTION;
            else if (name !== "iMusicTime") out[key] = 0.0;
            continue;
        }
        let v = arr[f];
        if (track) {
            const s = effSettings[track];
            if (s && s.mute) v = name === "iTimeToNextSection" ? NO_NEXT_SECTION : 0.0;
            else if (how === "setting") v = applySetting(v, s);
        }
        out[key] = v;
    }
    return out;
}
