from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .adapters import ProviderAdapter
from .types import ProviderCapabilities, ProviderReceipt


@dataclass
class InMemoryProvider:
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    min_fence: int = 0
    calls: int = 0
    effects: dict[str, ProviderReceipt] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)

    def advance_fence(self, fence: int) -> None:
        self.min_fence = max(self.min_fence, int(fence))

    def dispatch(
        self,
        *,
        action_id: str,
        auth_id: str,
        proposal_hash: str,
        idempotency_key: str,
        fence: int,
        result: dict,
    ) -> ProviderReceipt | dict:
        self.calls += 1

        if self.capabilities.supports_fencing and fence < self.min_fence:
            row = {
                "status": "REJECTED_STALE_FENCE",
                "fence": fence,
                "min_fence": self.min_fence,
            }
            self.rejected.append(copy.deepcopy(row))
            return row

        if self.capabilities.supports_fencing:
            self.advance_fence(fence)

        if self.capabilities.supports_idempotency and idempotency_key in self.effects:
            return copy.deepcopy(self.effects[idempotency_key])

        receipt = ProviderReceipt(
            receipt_id=f"REC-{action_id}-{len(self.effects)+1}",
            action_id=action_id,
            auth_id=auth_id,
            proposal_hash=proposal_hash,
            idempotency_key=idempotency_key,
            fence=fence,
            status="SUCCEEDED",
            result=copy.deepcopy(result),
        )

        key = (
            idempotency_key
            if self.capabilities.supports_idempotency
            else f"{idempotency_key}:{self.calls}"
        )
        self.effects[key] = copy.deepcopy(receipt)
        return receipt

    def query(self, idempotency_key: str) -> ProviderReceipt | None:
        if not self.capabilities.supports_status_query:
            return None
        row = self.effects.get(idempotency_key)
        return copy.deepcopy(row) if row else None
