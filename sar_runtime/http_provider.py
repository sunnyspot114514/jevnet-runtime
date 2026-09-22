from __future__ import annotations

import json
import socket
from dataclasses import asdict
from typing import Any
from urllib import error, parse, request

from .adapters import AmbiguousProviderOutcome
from .types import ProviderCapabilities, ProviderReceipt


class HTTPProviderAdapter:
    """HTTP ProviderAdapter with explicit SAR execution headers.

    Default wire contract:

    POST {base_url}/effects
      Headers:
        Idempotency-Key
        X-SAR-Action-ID
        X-SAR-Auth-ID
        X-SAR-Proposal-Hash
        X-SAR-Fence
        Content-Type: application/json

      Body:
        {"result": {...}}

      2xx response:
        ProviderReceipt JSON

      409 response:
        deterministic rejection JSON, e.g. REJECTED_STALE_FENCE

    GET {base_url}/effects/{urlencoded-idempotency-key}
      200 -> ProviderReceipt JSON
      404 -> no known effect

    Network failures and 5xx responses are treated as ambiguous provider
    outcomes because the runtime cannot infer whether the external effect
    committed before the failure.
    """

    def __init__(
        self,
        base_url: str,
        *,
        capabilities: ProviderCapabilities | None = None,
        timeout: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._capabilities = capabilities or ProviderCapabilities(
            supports_idempotency=True,
            supports_status_query=True,
            supports_compensation=False,
            supports_fencing=True,
            supports_transactional_commit=False,
        )
        self.timeout = float(timeout)
        self.headers = dict(headers or {})

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def advance_fence(self, fence: int) -> None:
        # Remote providers validate the per-request fence. There is no separate
        # mutation call in the generic HTTP contract.
        return None

    def _decode_receipt(self, payload: dict[str, Any]) -> ProviderReceipt:
        required = {
            "receipt_id",
            "action_id",
            "auth_id",
            "proposal_hash",
            "idempotency_key",
            "fence",
            "status",
            "result",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise RuntimeError(
                f"MALFORMED_PROVIDER_RECEIPT:missing={','.join(missing)}"
            )

        return ProviderReceipt(
            receipt_id=str(payload["receipt_id"]),
            action_id=str(payload["action_id"]),
            auth_id=str(payload["auth_id"]),
            proposal_hash=str(payload["proposal_hash"]),
            idempotency_key=str(payload["idempotency_key"]),
            fence=int(payload["fence"]),
            status=str(payload["status"]),
            result=dict(payload["result"]),
        )

    def _json_request(
        self,
        req: request.Request,
        *,
        effectful: bool,
    ) -> tuple[int, dict[str, Any]]:
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                status = int(response.status)
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read().decode("utf-8", errors="replace")

            if status >= 500:
                raise AmbiguousProviderOutcome(
                    f"HTTP_{status}_AMBIGUOUS_PROVIDER_OUTCOME"
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
            raise AmbiguousProviderOutcome(
                "HTTP_CONNECTION_OR_TIMEOUT_AMBIGUOUS_PROVIDER_OUTCOME"
            ) from exc

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            if effectful:
                raise AmbiguousProviderOutcome(
                    "HTTP_SUCCESS_WITH_MALFORMED_RECEIPT"
                ) from exc
            raise RuntimeError(
                "MALFORMED_PROVIDER_QUERY_RESPONSE"
            ) from exc

        return status, payload

    def dispatch(
        self,
        *,
        action_id: str,
        auth_id: str,
        proposal_hash: str,
        idempotency_key: str,
        fence: int,
        result: dict[str, Any],
    ) -> ProviderReceipt | dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-SAR-Action-ID": action_id,
            "X-SAR-Auth-ID": auth_id,
            "X-SAR-Proposal-Hash": proposal_hash,
            "X-SAR-Fence": str(int(fence)),
            **self.headers,
        }

        body = json.dumps(
            {"result": result},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        req = request.Request(
            f"{self.base_url}/effects",
            data=body,
            headers=headers,
            method="POST",
        )

        status, payload = self._json_request(req, effectful=True)

        if 200 <= status < 300:
            return self._decode_receipt(payload)

        if 400 <= status < 500:
            if not payload:
                payload = {
                    "status": f"REJECTED_HTTP_{status}",
                }
            return payload

        raise AmbiguousProviderOutcome(
            f"HTTP_{status}_AMBIGUOUS_PROVIDER_OUTCOME"
        )

    def query(self, idempotency_key: str) -> ProviderReceipt | None:
        encoded = parse.quote(idempotency_key, safe="")
        req = request.Request(
            f"{self.base_url}/effects/{encoded}",
            headers={
                "Accept": "application/json",
                **self.headers,
            },
            method="GET",
        )

        status, payload = self._json_request(req, effectful=False)

        if status == 404:
            return None

        if 200 <= status < 300:
            return self._decode_receipt(payload)

        if 400 <= status < 500:
            raise RuntimeError(
                f"PROVIDER_QUERY_REJECTED_HTTP_{status}"
            )

        raise AmbiguousProviderOutcome(
            f"HTTP_{status}_AMBIGUOUS_PROVIDER_QUERY"
        )
