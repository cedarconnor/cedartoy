/**
 * Modulation-matrix binding for the preview. Contains NO shaping math: the
 * per-frame values are computed in Python (cedartoy/modulation.py) and
 * served by POST /api/modulation/series. This only picks the frame for a
 * transport time, using the same frame convention as the track timeline
 * (f = round(t * fps), clamped). Parity with ModulationEvaluator.evaluate_at
 * is locked by tests/test_modulation.py::test_js_modulated_values_match_python.
 */

export function modulationFrame(payload, t) {
    const n = (payload && payload.frames) | 0;
    if (!n) return -1;
    let f = Math.round((+t || 0) * payload.fps);
    if (f < 0) f = 0;
    if (f >= n) f = n - 1;
    return f;
}

/** {param: value} at transport time t; {} without a loaded series. */
export function modulatedValuesAt(payload, t) {
    const out = {};
    if (!payload || !payload.series) return out;
    const f = modulationFrame(payload, t);
    if (f < 0) return out;
    for (const [name, arr] of Object.entries(payload.series)) {
        if (arr && arr.length > f) out[name] = arr[f];
    }
    return out;
}
