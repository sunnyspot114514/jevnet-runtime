#!/usr/bin/env python3
"""Reference HTTP lease service for SAR integration tests."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from sar_runtime import LeaseToken, SQLiteLeaseCoordinator


def json_bytes(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_handler(leases: SQLiteLeaseCoordinator):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SARReferenceLease/0.1"

        def log_message(self, format, *args):
            return

        def _write(self, status: int, payload) -> None:
            body = json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _resource_and_suffix(self):
            parsed = urlparse(self.path)
            prefix = "/leases/"
            if not parsed.path.startswith(prefix):
                return None, None
            tail = parsed.path[len(prefix):]
            for suffix in ("/acquire", "/release"):
                if tail.endswith(suffix):
                    return unquote(tail[:-len(suffix)]), suffix
            return unquote(tail), ""

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._write(200, {"status": "ok"})
                return

            if parsed.path == "/metrics":
                self._write(
                    200,
                    {"integrity": leases.integrity_check()},
                )
                return

            resource_id, suffix = self._resource_and_suffix()
            if resource_id is None or suffix != "":
                self._write(404, {"status": "NOT_FOUND"})
                return

            token = leases.current(resource_id)
            if token is None:
                self._write(404, {"status": "NO_CURRENT_LEASE"})
            else:
                self._write(200, asdict(token))

        def do_POST(self):
            resource_id, suffix = self._resource_and_suffix()
            if resource_id is None:
                self._write(404, {"status": "NOT_FOUND"})
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._write(400, {"status": "INVALID_JSON"})
                return

            if suffix == "/acquire":
                owner_id = body.get("owner_id")
                if not owner_id:
                    self._write(400, {"status": "MISSING_OWNER"})
                    return
                token = leases.acquire(resource_id, str(owner_id))
                self._write(200, asdict(token))
                return

            if suffix == "/release":
                owner_id = body.get("owner_id")
                fence = body.get("fence")
                if owner_id is None or fence is None:
                    self._write(400, {"status": "MISSING_TOKEN"})
                    return
                token = LeaseToken(
                    resource_id=resource_id,
                    owner_id=str(owner_id),
                    fence=int(fence),
                )
                self._write(
                    200,
                    {"released": leases.release(token)},
                )
                return

            self._write(404, {"status": "NOT_FOUND"})

    return Handler


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    leases = SQLiteLeaseCoordinator(Path(args.db))

    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(leases),
    )

    print(
        json.dumps(
            {
                "host": args.host,
                "port": server.server_address[1],
                "db": str(Path(args.db)),
            }
        ),
        flush=True,
    )

    try:
        server.serve_forever(poll_interval=0.05)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
