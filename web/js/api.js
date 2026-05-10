/**
 * API client for CedarToy backend
 */

const API_BASE = '/api';

export const api = {
    // Shaders
    async listShaders() {
        const res = await fetch(`${API_BASE}/shaders/`);
        return await res.json();
    },

    async getShader(path) {
        const res = await fetch(`${API_BASE}/shaders/${encodeURIComponent(path)}`);
        return await res.json();
    },

    // Config
    async getSchema() {
        const res = await fetch(`${API_BASE}/config/schema`);
        return await res.json();
    },

    async getDefaults() {
        const res = await fetch(`${API_BASE}/config/defaults`);
        return await res.json();
    },

    async saveConfig(config, filepath = 'cedartoy.yaml') {
        const res = await fetch(`${API_BASE}/config/save?filepath=${encodeURIComponent(filepath)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        return await res.json();
    },

    async loadConfig(filepath) {
        const res = await fetch(`${API_BASE}/config/load?filepath=${encodeURIComponent(filepath)}`, {
            method: 'POST'
        });
        return await res.json();
    },

    async listPresets() {
        const res = await fetch(`${API_BASE}/config/presets`);
        return await res.json();
    },

    async savePreset(config, name) {
        const res = await fetch(`${API_BASE}/config/presets?name=${encodeURIComponent(name)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        return await res.json();
    },

    // Files (directory browser)
    async browseDirectory(path = '.') {
        const res = await fetch(`${API_BASE}/files/browse?path=${encodeURIComponent(path)}`);
        return await res.json();
    },

    async getDrives() {
        const res = await fetch(`${API_BASE}/files/drives`);
        return await res.json();
    },

    // Audio
    async uploadAudio(file) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/audio/upload`, {
            method: 'POST',
            body: formData
        });
        return await res.json();
    },

    async getAudioInfo() {
        const res = await fetch(`${API_BASE}/audio/info`);
        return await res.json();
    },

    async getWaveform(numSamples = 1000) {
        const res = await fetch(`${API_BASE}/audio/waveform?num_samples=${numSamples}`);
        return await res.json();
    },

    async getAudioFFT(frame) {
        const res = await fetch(`${API_BASE}/audio/fft/${frame}`);
        return await res.json();
    },

    // Render
    async startRender(config) {
        const res = await fetch(`${API_BASE}/render/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(JSON.stringify(data.detail || data));
        }
        return data;
    },

    async cancelRender(jobId) {
        const res = await fetch(`${API_BASE}/render/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
        return await res.json();
    },

    async getRenderStatus(jobId) {
        const res = await fetch(`${API_BASE}/render/${encodeURIComponent(jobId)}/status`);
        return await res.json();
    },

    async listRenderArtifacts(jobId) {
        const res = await fetch(`${API_BASE}/render/${encodeURIComponent(jobId)}/artifacts`);
        return await res.json();
    }
};
