"""A tiny local website for tests (served on 127.0.0.1, so tests use allow_private=True)."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGES: dict[str, tuple[int, str, dict]] = {}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, head_only: bool) -> None:
        status, body, headers = PAGES.get(self.path, (404, "<h1>Not found</h1>", {}))
        data = body.encode()
        self.send_response(status)
        if "Content-Type" not in headers:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._send(False)

    def do_HEAD(self):  # noqa: N802
        self._send(True)

    def log_message(self, *args):
        pass


class Site:
    def __init__(self, pages: dict[str, tuple[int, str, dict] | str]):
        PAGES.clear()
        for path, v in pages.items():
            PAGES[path] = v if isinstance(v, tuple) else (200, v, {})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
