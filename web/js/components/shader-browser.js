import { api } from '../api.js';

class ShaderBrowser extends HTMLElement {
    constructor() {
        super();
        this.shaders = [];
    }

    async connectedCallback() {
        this.shaders = await api.listShaders();
        this.render();
        this.attachEventListeners();
    }

    render() {
        this.innerHTML = `
            <div class="shader-browser-container">
                <h3>Shaders</h3>
                <input type="text" class="form-input" id="shader-search" placeholder="Search..." style="margin-bottom: 16px;">
                <div class="shader-list" id="shader-list">
                    ${this.shaders.map(shader => `
                        <div class="shader-item" data-path="${shader.path}" data-name="${shader.name}">
                            <div class="shader-name">${shader.name}</div>
                            <div class="shader-desc">${shader.description || shader.path}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        // Search filter
        const searchInput = this.querySelector('#shader-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                const query = e.target.value.toLowerCase();
                this.querySelectorAll('.shader-item').forEach(item => {
                    const name = item.dataset.name.toLowerCase();
                    const path = item.dataset.path.toLowerCase();
                    item.style.display = (name.includes(query) || path.includes(query)) ? 'block' : 'none';
                });
            });
        }

        // Shader selection
        this.querySelectorAll('.shader-item').forEach(item => {
            item.addEventListener('click', () => {
                // Remove previous selection
                this.querySelectorAll('.shader-item').forEach(i => i.classList.remove('selected'));
                // Add selection to clicked item
                item.classList.add('selected');

                const path = item.dataset.path;
                this.dispatchEvent(new CustomEvent('shader-select', {
                    detail: { path: path },
                    bubbles: true,
                    composed: true
                }));
            });

            // Double-click to edit
            item.addEventListener('dblclick', () => {
                const path = item.dataset.path;
                document.dispatchEvent(new CustomEvent('shader-edit', {
                    detail: { path: path },
                    bubbles: true,
                    composed: true
                }));
            });
        });
    }
}

customElements.define('shader-browser', ShaderBrowser);
