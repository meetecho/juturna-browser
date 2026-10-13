#!/usr/bin/env python3
"""Static file server for the examples and the browser tests.

It adds the COOP/COEP response headers that `SharedArrayBuffer` needs in the
browser, and disables caching so that a rebuilt `dist/` is always served.

Usage:
    python3 serve.py [port]

Then open http://localhost:<port>/examples/microphone.html (or a page in
test/) in a recent Chrome.
"""

import http.server
import socketserver
import sys


class COOPCOEPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer(
        ('127.0.0.1', port), COOPCOEPRequestHandler
    ) as httpd:
        print(f'serving on http://localhost:{port} (COOP/COEP enabled)')
        httpd.serve_forever()


if __name__ == '__main__':
    main()
