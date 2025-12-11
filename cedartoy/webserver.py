import http.server
import socketserver
import threading
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from typing import Optional

PORT = 8000
WEB_ROOT = Path(__file__).parent.parent / "web"

class PreviewHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self):
        # Handle API calls
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            status = {"status": "ok", "version": "0.3.0"}
            self.wfile.write(json.dumps(status).encode('utf-8'))
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
