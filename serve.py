#!/usr/bin/env python3
"""
Static file server for the examples and the browser tests.

It adds the COOP/COEP response headers that `SharedArrayBuffer` needs in the
browser, and disables caching so that a rebuilt `dist/` is always served.

Usage:
    python3 serve.py [port]

Then open http://localhost:<port>/examples/microphone.html (or a page in
test/) in a recent Chrome.
"""

import http.server
import sys


class COOPCOEPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Static file handler that sends the COOP/COEP headers."""

    def end_headers(self):  # noqa: D102
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def main():
    """Serve the current folder on the port given as argument."""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    # a thread per connection: a browser keeps idle ones open, and one thread
    # would wait on them while the Workers ask for their files
    with http.server.ThreadingHTTPServer(
        ('127.0.0.1', port), COOPCOEPRequestHandler
    ) as httpd:
        print(f'serving on http://localhost:{port} (COOP/COEP enabled)')
        httpd.serve_forever()


if __name__ == '__main__':
    main()
