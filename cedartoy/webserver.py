import http.server
import socketserver
import threading
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from typing import Optional

PORT = 8000
WEB_ROOT = Path(__file__).parent.parent / "web"
SHADERS_ROOT = Path(__file__).parent.parent / "shaders"

class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _send_json(self, data, status: int = 200):
        payload = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, text: str, status: int = 200):
        payload = text.encode('utf-8')
        self.send_response(status)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.send_header("Content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _resolve_shader_path(self, rel_path: str) -> Path:
        root = SHADERS_ROOT.resolve()
        candidate = (SHADERS_ROOT / rel_path).resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("Invalid shader path.")
        if candidate.suffix.lower() != ".glsl":
            raise ValueError("Shader must be a .glsl file.")
        return candidate

    def do_GET(self):
        # Handle API calls
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json({"status": "ok", "version": "0.3.0"})
            return

        if parsed.path == "/api/shaders":
            files = []
            if SHADERS_ROOT.exists():
                for p in SHADERS_ROOT.rglob("*.glsl"):
                    if "common" in p.parts:
                        continue
                    files.append(str(p.relative_to(SHADERS_ROOT)).replace("\\", "/"))
            self._send_json({"shaders": sorted(files)})
            return

        if parsed.path == "/api/shader":
            qs = parse_qs(parsed.query)
            rel = qs.get("path", ["test.glsl"])[0]
            try:
                p = self._resolve_shader_path(rel)
                src = p.read_text(encoding="utf-8")
                self._send_text(src)
            except Exception as e:
                self._send_text(str(e), status=400)
            return
            
        # Serve static files
        super().do_GET()

def run_server(port: int = 8000, directory: Optional[Path] = None):
    # If directory is provided, we might want to serve that too, or symlink?
    # For now, we serve 'web' folder.
    
    print(f"Starting web server at http://localhost:{port}")
    with socketserver.TCPServer(("", port), PreviewHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server.")
            httpd.shutdown()

if __name__ == "__main__":
    run_server()
