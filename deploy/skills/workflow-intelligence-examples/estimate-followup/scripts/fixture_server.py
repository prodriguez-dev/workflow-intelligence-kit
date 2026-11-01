#!/usr/bin/env python3
"""Serve the estimates fixture over HTTP with the two-call shape.

For demos and for forks wiring a CRM adapter: point [source] base_url at this
server and the skill exercises its real HTTP client against fake data.

    python3 fixture_server.py --port 8765 [--token-env ESTIMATES_API_TOKEN]

    GET /estimates?status=open  -> {"results": [{"id": ...}], "next": null}
    GET /estimates/{id}         -> the record, or 404

Binds to 127.0.0.1 only. Answers GET only; any other method gets 405.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from source import FixtureSource  # noqa: E402

DEFAULT_FIXTURE = os.path.join(os.path.dirname(SCRIPT_DIR), "fixtures", "estimates.json")


def make_handler(records, token=None):
    by_id = {r["id"]: r for r in records}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet by default
            pass

        def _send(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 (http.server naming)
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                return self._send(401, {"error": "unauthorized"})
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == "/estimates":
                status = query.get("status", [None])[0]
                hits = [r for r in records if status is None or r.get("status") == status]
                return self._send(200, {"results": [{"id": r["id"]} for r in hits], "next": None})
            prefix = "/estimates/"
            if url.path.startswith(prefix):
                record = by_id.get(urllib.parse.unquote(url.path[len(prefix):]))
                if record is not None:
                    return self._send(200, record)
            return self._send(404, {"error": "not found"})

        def _refuse(self):
            self._send(405, {"error": "read-only fixture"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

    return Handler


def start(fixture=DEFAULT_FIXTURE, port=0, today=None, shift_dates=False, token=None):
    """Start in a background thread. Returns (server, base_url)."""
    records = FixtureSource(fixture, today=today, shift_dates=shift_dates).all_records()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(records, token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main():
    p = argparse.ArgumentParser(description="Serve the estimates fixture on 127.0.0.1.")
    p.add_argument("--fixture", default=DEFAULT_FIXTURE)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--today", help="with --shift-dates, the date to shift the fixture to (default: today)")
    p.add_argument("--shift-dates", action="store_true", help="move fixture dates so its as_of lands on --today")
    p.add_argument("--token-env", help="require 'Authorization: Bearer $VAR' using this env var")
    args = p.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    token = os.environ.get(args.token_env, "") if args.token_env else None
    if args.token_env and not token:
        p.error(f"{args.token_env} is empty")
    server, url = start(args.fixture, args.port, today, args.shift_dates, token)
    print(f"serving {args.fixture} at {url} (Ctrl-C to stop)", file=sys.stderr)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
