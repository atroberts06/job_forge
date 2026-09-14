#!/usr/bin/env python3
"""Serve the job-search dashboard; map /orchestrator/run.log to the sibling sandbox."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

DASHBOARD_DIR = Path(__file__).resolve().parent
JOB_SEARCH_ROOT = DASHBOARD_DIR.parent
ORCH_LOG = JOB_SEARCH_ROOT.parent / "orchestrator" / "run.log"


def _request_path(raw: str) -> str:
    return unquote(urlparse(raw).path)


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=str(JOB_SEARCH_ROOT), **kwargs)

    def _is_orch_log(self) -> bool:
        return _request_path(self.path).rstrip("/") == "/orchestrator/run.log"

    def _serve_orch_log(self, *, head_only: bool) -> None:
        if not ORCH_LOG.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        try:
            data = ORCH_LOG.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self) -> None:
        if self._is_orch_log():
            self._serve_orch_log(head_only=False)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._is_orch_log():
            self._serve_orch_log(head_only=True)
            return
        super().do_HEAD()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the local job-search dashboard")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.bind, args.port), DashboardHandler)
    print(f"Serving job-search dashboard from: {JOB_SEARCH_ROOT}", flush=True)
    print(f"Open http://{args.bind}:{args.port}/dashboard/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
