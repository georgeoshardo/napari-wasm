"""Serve the napari-wasm folder for local testing.

Usage: python web/serve.py [port] [--isolated]   (default port 8080)

--isolated sends the cross-origin isolation headers browsers require before
they allow shared memory, which WebAssembly threads need.

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

    isolated = False

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        if self.isolated:
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()


if __name__ == "__main__":
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    Handler.isolated = "--isolated" in sys.argv
    port = int(args[0]) if args else 8080
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Handler, directory=str(ROOT))
    )
    print(f"Serving {ROOT} at http://127.0.0.1:{port}/web/", flush=True)
    server.serve_forever()
