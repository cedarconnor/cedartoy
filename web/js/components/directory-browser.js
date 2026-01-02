class DirectoryBrowser extends HTMLElement {
    connectedCallback() {
        this.style.display = 'none';
        this.innerHTML = `
            <div class="modal-overlay">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>Directory Browser</h3>
                        <button class="btn-close">×</button>
                    </div>
                    <div>
                        Directory browser coming soon...
                    </div>
                </div>
            </div>
        `;
    }
}

customElements.define('directory-browser', DirectoryBrowser);
