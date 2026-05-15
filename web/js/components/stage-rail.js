class StageRail extends HTMLElement {
    constructor() {
        super();
        this.activeStage = 'project';
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
        // Fire initial stage so panels can sync on load.
        this.dispatchEvent(new CustomEvent('stage-change', {
            detail: { stage: this.activeStage }, bubbles: true,
        }));
    }

    render() {
        const stages = [
            { id: 'project', label: '1. Project' },
            { id: 'shader',  label: '2. Shader' },
            { id: 'output',  label: '3. Output' },
            { id: 'render',  label: '4. Render' },
        ];
        const items = stages.map((s, i) => {
            const sep = i < stages.length - 1
                ? '<span class="stage-rail-sep">›</span>' : '';
            return `<button class="stage-rail-item ${s.id === this.activeStage ? 'active' : ''}"
                            data-stage="${s.id}">${s.label}</button>${sep}`;
        }).join('');
        this.innerHTML = `<nav class="stage-rail">${items}</nav>`;
    }

    attachEventListeners() {
        this.querySelectorAll('.stage-rail-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.activeStage = e.target.dataset.stage;
                this.render();
                this.attachEventListeners();
                this.dispatchEvent(new CustomEvent('stage-change', {
                    detail: { stage: this.activeStage }, bubbles: true,
                }));
            });
        });
    }
}

customElements.define('stage-rail', StageRail);
