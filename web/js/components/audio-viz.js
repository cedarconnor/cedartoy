import { api } from '../api.js';

class AudioViz extends HTMLElement {
    constructor() {
        super();
        this.audioContext = null;
        this.audioElement = null;
        this.analyser = null;
        this.waveform = [];
        this.currentTime = 0;
        this.duration = 0;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
    }

    render() {
        this.innerHTML = `
            <div class="audio-viz-container" style="margin-top: 16px;">
                <h4>Audio</h4>
                <input type="file" accept="audio/*" class="form-input" id="audio-upload">
                <div id="audio-filename" style="margin-top: 4px; color: var(--text-secondary); font-size: 0.85rem;"></div>

                <canvas id="waveform-canvas" width="600" height="80"
                    style="width: 100%; margin-top: 8px; background: var(--bg-tertiary); border-radius: 4px; cursor: pointer;"></canvas>

                <canvas id="fft-canvas" width="512" height="100"
                    style="width: 100%; margin-top: 8px; background: var(--bg-tertiary); border-radius: 4px;"></canvas>
            </div>
        `;
    }

    attachEventListeners() {
        const uploadInput = this.querySelector('#audio-upload');
        const waveformCanvas = this.querySelector('#waveform-canvas');

        uploadInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (file) {
                await this.loadAudio(file);
            }
        });

        // Click to seek
        waveformCanvas.addEventListener('click', (e) => {
            const rect = waveformCanvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const progress = x / rect.width;
            const time = progress * this.duration;

            if (this.audioElement) {
                this.audioElement.currentTime = time;
            }

            this.dispatchEvent(new CustomEvent('audio-seek', {
                detail: { time },
                bubbles: true,
                composed: true
            }));
        });

        // Update FFT in animation loop
        this.startFFTAnimation();
    }

    async loadAudio(file) {
        // Upload to server
        const result = await api.uploadAudio(file);
        this.duration = result.metadata.duration;

        // Display filename
        this.querySelector('#audio-filename').textContent = `🎵 ${file.name} (${this.formatDuration(this.duration)})`;

        // Load waveform
        const waveformData = await api.getWaveform();
        this.waveform = waveformData.waveform;
        this.drawWaveform();

        // Setup Web Audio API for playback and FFT
        this.setupWebAudio(file);
    }

    async setupWebAudio(file) {
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        this.audioElement = new Audio(URL.createObjectURL(file));

        const source = this.audioContext.createMediaElementSource(this.audioElement);
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 1024;

        source.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);

        // Sync with preview
        this.audioElement.addEventListener('timeupdate', () => {
            this.currentTime = this.audioElement.currentTime;
            this.drawWaveform(); // Update playhead
        });

        // Listen for preview play/pause
        document.addEventListener('preview-play', () => {
            this.audioElement.play();
        });

        document.addEventListener('preview-pause', () => {
            this.audioElement.pause();
        });

        document.addEventListener('preview-seek', (e) => {
            this.audioElement.currentTime = e.detail.time;
        });
    }

    drawWaveform() {
        const canvas = this.querySelector('#waveform-canvas');
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;

        ctx.clearRect(0, 0, width, height);

        // Draw waveform
        ctx.strokeStyle = '#4ecca3';
        ctx.lineWidth = 1;
        ctx.beginPath();

        for (let i = 0; i < this.waveform.length; i++) {
            const x = (i / this.waveform.length) * width;
            const y = ((this.waveform[i] + 1) / 2) * height; // Normalize -1 to 1 → 0 to height

            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }

        ctx.stroke();

        // Draw playhead
        if (this.duration > 0) {
            const playheadX = (this.currentTime / this.duration) * width;
            ctx.strokeStyle = '#e94560';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(playheadX, 0);
            ctx.lineTo(playheadX, height);
            ctx.stroke();
        }
    }

    startFFTAnimation() {
        const canvas = this.querySelector('#fft-canvas');
        const ctx = canvas.getContext('2d');

        const animate = () => {
            if (this.analyser) {
                const bufferLength = this.analyser.frequencyBinCount;
                const dataArray = new Uint8Array(bufferLength);
                this.analyser.getByteFrequencyData(dataArray);

                // Normalize FFT data to 0-1 range
                const normalizedFFT = new Float32Array(512);
                for (let i = 0; i < 512; i++) {
                    normalizedFFT[i] = (dataArray[i] || 0) / 255.0;
                }

                // Get waveform data
                const waveformArray = new Uint8Array(bufferLength);
                this.analyser.getByteTimeDomainData(waveformArray);
                const normalizedWaveform = new Float32Array(512);
                for (let i = 0; i < 512; i++) {
                    normalizedWaveform[i] = (waveformArray[i] / 128.0) - 1.0; // -1 to 1 range
                }

                // Emit audio data event for renderer
                document.dispatchEvent(new CustomEvent('audio-data', {
                    detail: {
                        fft: normalizedFFT,
                        waveform: normalizedWaveform
                    }
                }));

                // Draw FFT bars
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = '#533483';

                const barWidth = canvas.width / bufferLength;
                for (let i = 0; i < bufferLength; i++) {
                    const barHeight = (dataArray[i] / 255) * canvas.height;
                    const x = i * barWidth;
                    const y = canvas.height - barHeight;

                    ctx.fillRect(x, y, barWidth - 1, barHeight);
                }
            }

            requestAnimationFrame(animate);
        };

        animate();
    }

    formatDuration(seconds) {
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60);
        return `${min}:${sec.toString().padStart(2, '0')}`;
    }
}

customElements.define('audio-viz', AudioViz);
