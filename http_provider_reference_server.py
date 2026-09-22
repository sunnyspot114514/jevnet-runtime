#!/usr/bin/env python3
"""Reference HTTP provider server for SAR integration tests.

The server runs in a separate process and stores provider effects in
SQLiteProviderAdapter. It intentionally exposes only a thin HTTP shim.

Endpoints:
- POST /effects
- GET  /effects/{idempotency_key}
- GET  /metrics
- GET  /health

Test-only behavior:
- header X-Test-Drop-First-Response: 1
  commits the first effect, then closes the connection before writing a
  response. A retry/query observes the already committed effect.
"""

from __future__ import annotations

import argparse
import json
import socket
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from sar_runtime import (
    ProviderCapabilities,
    ProviderReceipt,
    SQLiteProviderAdapter,
)


def json_bytes(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_handler(provider: SQLiteProviderAdapter):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SARReferenceProvider/0.1"

        def log_message(self, format, *args):
            return

        def _write(self, status: int, payload) -> None:
            body = json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path == "/health":
                self._write(200, {"status": "ok"})
                return

            if parsed.path == "/metrics":
                self._write(
                    200,
                    {
                        "effect_count": provider.effect_count(),
                        "call_count": provider.call_count(),
                        "integrity": provider.integrity_check(),
                    },
                )
                return

            prefix = "/effects/"
            if parsed.path.startswith(prefix):
                if not provider.capabilities.supports_status_query:
                    self._write(405, {"status": "QUERY_UNSUPPORTED"})
                    return

                key = unquote(parsed.path[len(prefix):])
                receipt = provider.query(key)
                if receipt is None:
                    self._write(404, {"status": "NOT_FOUND"})
                else:
                    self._write(200, asdict(receipt))
                return

            self._write(404, {"status": "NOT_FOUND"})

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/effects":
                self._write(404, {"status": "NOT_FOUND"})
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._write(400, {"status": "INVALID_JSON"})
                return

            key = self.headers.get("Idempotency-Key")
            action_id = self.headers.get("X-SAR-Action-ID")
            auth_id = self.headers.get("X-SAR-Auth-ID")
            proposal_hash = self.headers.get("X-SAR-Proposal-Hash")
            fence_raw = self.headers.get("X-SAR-Fence")

            if not all((key, action_id, auth_id, proposal_hash, fence_raw)):
                self._write(400, {"status": "MISSING_SAR_HEADERS"})
                return

            try:
                fence = int(fence_raw)
            except ValueError:
                self._write(400, {"status": "INVALID_FENCE"})
                return

            before = (
                provider.query(key)
                if provider.capabilities.supports_status_query
                else None
            )

            result = provider.dispatch(
                action_id=action_id,
                auth_id=auth_id,
                proposal_hash=proposal_hash,
                idempotency_key=key,
                fence=fence,
                result=dict(body.get("result", {})),
            )

            if isinstance(result, dict):
                status = (
                    409
                    if result.get("status") == "REJECTED_STALE_FENCE"
                    else 400
                )
                self._write(status, result)
                return

            drop = (
                self.headers.get("X-Test-Drop-First-Response") == "1"
                and before is None
            )
            if drop:
                # Effect is durable in provider DB, but the client receives no
                # HTTP response. This intentionally creates an ambiguous
                # provider outcome.
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                self.close_connection = True
                return

            self._write(200, asdict(result))

    return Handler


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--idempotency", choices=["0", "1"], default="1")
    p.add_argument("--status-query", choices=["0", "1"], default="1")
    p.add_argument("--fencing", choices=["0", "1"], default="1")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    provider = SQLiteProviderAdapter(
        Path(args.db),
        capabilities=ProviderCapabilities(
            supports_idempotency=args.idempotency == "1",
            supports_status_query=args.status_query == "1",
            supports_compensation=False,
            supports_fencing=args.fencing == "1",
            supports_transactional_commit=False,
        ),
    )

    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(provider),
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
