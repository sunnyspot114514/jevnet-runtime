from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import ProviderCapabilities, ProviderReceipt


@runtime_checkable
class ProviderAdapter(Protocol):
    """External side-effect adapter contract.

    Exactly-once / recovery semantics depend on these provider primitives. A
    runtime must not claim guarantees the adapter cannot support.
    """

    @property
    def capabilities(self) -> ProviderCapabilities:
        ...

    def advance_fence(self, fence: int) -> None:
        ...

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
        ...

    def query(self, idempotency_key: str) -> ProviderReceipt | None:
        ...
