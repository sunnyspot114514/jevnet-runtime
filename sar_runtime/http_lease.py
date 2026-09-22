from __future__ import annotations

import json
import socket
from urllib import error, parse, request

from .lease import LeaseToken


class LeaseCoordinatorUnavailable(RuntimeError):
    """The remote lease service could not provide a trustworthy response."""


class HTTPLeaseCoordinator:
    """REST-style LeaseCoordinator.

    Contract:

    POST /leases/{resource_id}/acquire
      body: {"owner_id": "..."}
      200: {"resource_id": "...", "owner_id": "...", "fence": N}

    GET /leases/{resource_id}
      200: lease token
      404: no current owner

    POST /leases/{resource_id}/release
      body: {"owner_id": "...", "fence": N}
      200: {"released": true|false}

    Any network failure or 5xx response fails closed by raising
    LeaseCoordinatorUnavailable. The runtime must not touch the provider when
    it cannot acquire trustworthy execution ownership.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.headers = dict(headers or {})

    def _url(self, resource_id: str, suffix: str = "") -> str:
        encoded = parse.quote(resource_id, safe="")
        return f"{self.base_url}/leases/{encoded}{suffix}"

    def _request(
        self,
        req: request.Request,
    ) -> tuple[int, dict]:
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                status = int(response.status)
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")
            if status >= 500:
                raise LeaseCoordinatorUnavailable(
                    f"LEASE_HTTP_{status}"
                ) from exc
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            return status, payload
        except (
            error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
        ) as exc:
            raise LeaseCoordinatorUnavailable(
                "LEASE_CONNECTION_OR_TIMEOUT"
            ) from exc

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise LeaseCoordinatorUnavailable(
                "LEASE_MALFORMED_RESPONSE"
            ) from exc

        return status, payload

    def _token(self, payload: dict) -> LeaseToken:
        required = {"resource_id", "owner_id", "fence"}
        missing = sorted(required - set(payload))
        if missing:
            raise LeaseCoordinatorUnavailable(
                f"LEASE_MALFORMED_TOKEN:{','.join(missing)}"
            )
        return LeaseToken(
            resource_id=str(payload["resource_id"]),
            owner_id=str(payload["owner_id"]),
            fence=int(payload["fence"]),
        )

    def acquire(self, resource_id: str, owner_id: str) -> LeaseToken:
        body = json.dumps(
            {"owner_id": owner_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        req = request.Request(
            self._url(resource_id, "/acquire"),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **self.headers,
            },
            method="POST",
        )
        status, payload = self._request(req)
        if not 200 <= status < 300:
            raise LeaseCoordinatorUnavailable(
                f"LEASE_ACQUIRE_REJECTED_HTTP_{status}"
            )
        return self._token(payload)

    def current(self, resource_id: str) -> LeaseToken | None:
        req = request.Request(
            self._url(resource_id),
            headers={
                "Accept": "application/json",
                **self.headers,
            },
            method="GET",
        )
        status, payload = self._request(req)
        if status == 404:
            return None
        if not 200 <= status < 300:
            raise LeaseCoordinatorUnavailable(
                f"LEASE_CURRENT_REJECTED_HTTP_{status}"
            )
        return self._token(payload)

    def release(self, token: LeaseToken) -> bool:
        body = json.dumps(
            {
                "owner_id": token.owner_id,
                "fence": token.fence,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        req = request.Request(
            self._url(token.resource_id, "/release"),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **self.headers,
            },
            method="POST",
        )
        status, payload = self._request(req)
        if not 200 <= status < 300:
            raise LeaseCoordinatorUnavailable(
                f"LEASE_RELEASE_REJECTED_HTTP_{status}"
            )
        return bool(payload.get("released", False))
