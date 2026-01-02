export class AudioTexture {
    constructor(gl) {
        this.gl = gl;
        this.texture = null;
        this.createTexture();
    }

    createTexture() {
        const gl = this.gl;

        this.texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this.texture);

        // Initialize with empty 512x2 texture
        const emptyData = new Uint8Array(512 * 2 * 4);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 512, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, emptyData);

        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }

    update(fftData, waveformData) {
        const gl = this.gl;

        // Create 512x2 texture: row 0 = FFT, row 1 = waveform
        const data = new Uint8Array(512 * 2 * 4);

        // FFT (row 0)
        for (let i = 0; i < 512; i++) {
            const value = Math.floor((fftData[i] || 0) * 255);
            const idx = i * 4;
            data[idx] = value;
            data[idx + 1] = value;
            data[idx + 2] = value;
            data[idx + 3] = 255;
        }

        // Waveform (row 1)
        for (let i = 0; i < 512; i++) {
            const value = Math.floor(((waveformData[i] || 0) + 1) / 2 * 255);
            const idx = (512 + i) * 4;
            data[idx] = value;
            data[idx + 1] = value;
            data[idx + 2] = value;
            data[idx + 3] = 255;
        }

        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 512, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    }

    bind(unit = 0) {
        const gl = this.gl;
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
    }
}
