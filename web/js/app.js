import { api } from './api.js';
import './components/shader-browser.js?v=2';
import './components/config-editor.js?v=2';
import './components/preview-panel.js?v=2';
import './components/audio-viz.js?v=2';
import './components/render-panel.js?v=2';
import './components/directory-browser.js?v=2';
import './components/shader-editor.js?v=2';

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
