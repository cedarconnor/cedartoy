const canvas = document.getElementById('glcanvas');
const gl = canvas.getContext('webgl2');

if (!gl) {
    alert('WebGL2 not supported');
}

// Placeholder for now. 
// Real implementation would fetch shaders from an API endpoint 
// and compile them here, mimicking the python renderer pipeline.

function render() {
    gl.clearColor(0.1, 0.1, 0.1, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
}

document.getElementById('reload').addEventListener('click', () => {
    document.getElementById('status').innerText = "Reloading...";
    setTimeout(() => {
        document.getElementById('status').innerText = "Ready";
    }, 500);
});

render();
