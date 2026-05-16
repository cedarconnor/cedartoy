import { api } from './api.js';
import './components/shader-browser.js?v=2';
import './components/config-editor.js?v=4';
import './components/preview-panel.js?v=3';
import './components/transport-strip.js?v=2';
import './components/render-panel.js?v=3';
import './components/directory-browser.js?v=2';
import './components/shader-editor.js?v=2';
import './components/stage-rail.js?v=1';
import './components/project-panel.js?v=2';
import './components/output-panel.js?v=2';
import './components/cue-scrubber.js?v=3';

// Global app state
window.cedartoy = {
    currentShader: null,
    config: {},
    audioFile: null
};

console.log('CedarToy UI initialized');

// Listen for shader selection
document.addEventListener('shader-select', async (e) => {
    const { path } = e.detail;
    console.log('Selected shader:', path);
    window.cedartoy.currentShader = path;

    // Ensure path has shaders/ prefix for config (render backend needs full path)
    const fullPath = path.startsWith('shaders/') ? path : `shaders/${path}`;

    // Update config with selected shader
    const configEditor = document.querySelector('config-editor');
    if (configEditor) {
        configEditor.config.shader = fullPath;
        configEditor.saveToLocalStorage();
        // Update the UI to show the selected shader
        const shaderInput = configEditor.querySelector('input[name="shader"]');
        if (shaderInput) {
            shaderInput.value = fullPath;
        }

        // Refresh shader parameters UI
        if (typeof configEditor.updateShaderParams === 'function') {
            configEditor.updateShaderParams();
        }
    }

    // Load shader source (API expects path without prefix)
    try {
        const shaderData = await api.getShader(path);
        console.log('Loaded shader:', shaderData);
    } catch (err) {
        console.error('Failed to load shader:', err);
    }
});

// Listen for config changes
document.addEventListener('config-change', (e) => {
    window.cedartoy.config = e.detail;
    console.log('Config updated:', window.cedartoy.config);
});

// Stage rail: toggle panel visibility based on active stage.
document.addEventListener('stage-change', (e) => {
    document.querySelectorAll('#stage-panels > div').forEach(d => {
        d.hidden = d.dataset.stage !== e.detail.stage;
    });
});

// Project loaded: feed audio/bundle paths into config-editor so renders pick them up.
document.addEventListener('project-loaded', (e) => {
    const ce = document.querySelector('config-editor');
    if (!ce) return;
    if (e.detail.audio_path) ce.config.audio_path = e.detail.audio_path;
    if (e.detail.bundle_path) ce.config.bundle_path = e.detail.bundle_path;
    if (typeof ce.saveToLocalStorage === 'function') ce.saveToLocalStorage();
    document.dispatchEvent(new CustomEvent('config-change', { detail: ce.config }));
});
