"""Serve the napari-wasm folder for local testing.

Usage: python web/serve.py [port]   (default 8080)

Pages are under /web/, the Pyodide build under /qt-build/build/sources/pyodide/dist/.
"""

import http.server
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".whl": "application/zip",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Handler, directory=str(ROOT))
    )
    print(f"Serving {ROOT} at http://127.0.0.1:{port}/web/", flush=True)
    server.serve_forever()
