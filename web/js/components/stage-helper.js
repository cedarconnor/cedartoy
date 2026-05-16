/**
 * <stage-helper title="…" subtitle="…">
 *
 * Compact top-of-stage bar telling the user what this stage is for.
 * Title is bold; subtitle is dimmer secondary text. Use the same shape
 * on every stage so the user has a stable place to look for guidance.
 */
class StageHelper extends HTMLElement {
    static get observedAttributes() {
        return ['title', 'subtitle'];
    }

    connectedCallback() {
        this.render();
    }

    attributeChangedCallback() {
        if (this.isConnected) this.render();
    }

    render() {
        const title = this.getAttribute('title') || '';
        const subtitle = this.getAttribute('subtitle') || '';
        this.innerHTML = `
            <div class="stage-helper">
                <strong>${this._escape(title)}</strong>
                <span>${this._escape(subtitle)}</span>
            </div>
        `;
    }

    _escape(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }[c]));
    }
}

customElements.define('stage-helper', StageHelper);
