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

    // Audio (placeholder for Phase 4)
    async uploadAudio(file) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/audio/upload`, {
            method: 'POST',
            body: formData
        });
        return await res.json();
    },

    // Render (placeholder for Phase 2)
    async startRender(config) {
        const res = await fetch(`${API_BASE}/render/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config })
        });
        return await res.json();
    },

    async cancelRender() {
        const res = await fetch(`${API_BASE}/render/cancel`, { method: 'POST' });
        return await res.json();
    },

    async getRenderStatus() {
        const res = await fetch(`${API_BASE}/render/status`);
        return await res.json();
    }
};
