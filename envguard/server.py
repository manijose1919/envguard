"""Local dashboard: static frontend + tiny JSON API.

Endpoints:
  GET /                     dashboard HTML
  GET /api/scans            scan history with severity counts
  GET /api/scans/latest     latest scan's findings
  GET /api/scans/<id>       a specific scan's findings
  POST /api/rescan          run a fresh scan, persist it, return its id
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .analyzer import analyze
from .cli import DB_NAME
from .storage import Store

_STATIC_DIR = Path(__file__).parent / "static"
_SCAN_ID_RE = re.compile(r"^/api/scans/(\d+)$")


def _make_handler(root: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EnvGuard/1.0"

        def _send_json(self, payload, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_findings(self, store: Store, scan_id: int | None) -> None:
            if scan_id is None:
                self._send_json({"error": "no scans recorded yet"}, 404)
                return
            self._send_json({
                "scan_id": scan_id,
                "findings": store.get_findings(scan_id),
            })

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            if path == "/":
                page = (_STATIC_DIR / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if path == "/api/scans":
                with Store(root / DB_NAME) as store:
                    self._send_json({"scans": store.list_scans()})
                return
            if path == "/api/scans/latest":
                with Store(root / DB_NAME) as store:
                    self._send_findings(store, store.latest_scan_id())
                return
            m = _SCAN_ID_RE.match(path)
            if m:
                with Store(root / DB_NAME) as store:
                    self._send_findings(store, int(m.group(1)))
                return
            self._send_json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/api/rescan":
                self._send_json({"error": "not found"}, 404)
                return
            result = analyze(root)
            with Store(root / DB_NAME) as store:
                scan_id = store.save_scan(
                    result.project_dir, result.files_scanned,
                    result.refs_found, result.keys_declared, result.findings,
                )
            self._send_json({"scan_id": scan_id}, 201)

        def log_message(self, fmt: str, *args) -> None:
            print(f"[envguard] {self.address_string()} {fmt % args}",
                  file=sys.stderr)

    return Handler


def run_server(root: Path, port: int) -> int:
    handler = _make_handler(root)
    # Bind loopback only: env key names must never be exposed to the LAN.
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"EnvGuard dashboard: http://127.0.0.1:{port}/  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0
