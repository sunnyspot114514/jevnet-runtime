from __future__ import annotations

from dataclasses import asdict

from .manifest import CapabilityManifest
from .adapters import ProviderAdapter
from .types import (
    CanonicalOutcomeCommit,
    DispatchIntent,
    DurableAuthorizationRecord,
    ProviderReceipt,
    ReconciliationRecord,
)
from .util import stable_hash


class RuntimeEngine:
    def __init__(self, manifest: CapabilityManifest) -> None:
        self.manifest = manifest

    def build_dispatch_intent(
        self,
        *,
        dar: DurableAuthorizationRecord,
        fence: int,
    ) -> DispatchIntent:
        ok, reason = self.manifest.revalidate_dar(dar)
        if not ok:
            raise ValueError(reason)

        payload_hash = stable_hash(dar.normalized_calls)
        return DispatchIntent(
            action_id=dar.action_id,
            auth_id=dar.auth_id,
            proposal_hash=dar.proposal_hash,
            idempotency_key=dar.idempotency_key,
            fence=int(fence),
            payload_hash=payload_hash,
        )

    def dispatch(
        self,
        *,
        dar: DurableAuthorizationRecord,
        intent: DispatchIntent,
        provider: ProviderAdapter,
    ):
        if intent.action_id != dar.action_id:
            raise ValueError("ACTION_BINDING_MISMATCH")
        if intent.auth_id != dar.auth_id:
            raise ValueError("AUTH_BINDING_MISMATCH")
        if intent.proposal_hash != dar.proposal_hash:
            raise ValueError("PROPOSAL_BINDING_MISMATCH")
        if intent.idempotency_key != dar.idempotency_key:
            raise ValueError("IDEMPOTENCY_BINDING_MISMATCH")
        if intent.payload_hash != stable_hash(dar.normalized_calls):
            raise ValueError("PAYLOAD_HASH_MISMATCH")

        result = {
            "normalized_calls": [dict(c) for c in dar.normalized_calls],
            "calls_hash": dar.calls_hash,
        }

        return provider.dispatch(
            action_id=dar.action_id,
            auth_id=dar.auth_id,
            proposal_hash=dar.proposal_hash,
            idempotency_key=dar.idempotency_key,
            fence=int(intent.fence),
            result=result,
        )

    def reconcile(
        self,
        *,
        dar: DurableAuthorizationRecord,
        receipts: list[ProviderReceipt],
    ) -> tuple[CanonicalOutcomeCommit | None, ReconciliationRecord]:
        valid: list[ProviderReceipt] = []
        rejected: list[tuple[str, str]] = []

        expected_result = {
            "normalized_calls": [dict(c) for c in dar.normalized_calls],
            "calls_hash": dar.calls_hash,
        }

        for receipt in receipts:
            if receipt.auth_id != dar.auth_id:
                rejected.append((receipt.receipt_id, "AUTH_MISMATCH"))
                continue
            if receipt.proposal_hash != dar.proposal_hash:
                rejected.append((receipt.receipt_id, "PROPOSAL_HASH_MISMATCH"))
                continue
            if receipt.idempotency_key != dar.idempotency_key:
                rejected.append((receipt.receipt_id, "IDEMPOTENCY_MISMATCH"))
                continue
            if receipt.status != "SUCCEEDED":
                rejected.append((receipt.receipt_id, "NON_SUCCESS"))
                continue
            if receipt.result != expected_result:
                rejected.append((receipt.receipt_id, "RESULT_MISMATCH"))
                continue
            valid.append(receipt)

        if not valid:
            return None, ReconciliationRecord(
                action_id=dar.action_id,
                accepted_receipt_id=None,
                rejected=tuple(sorted(rejected)),
            )

        chosen = sorted(valid, key=lambda r: r.receipt_id)[0]
        coc_base = {
            "action_id": dar.action_id,
            "auth_id": dar.auth_id,
            "proposal_hash": dar.proposal_hash,
            "idempotency_key": dar.idempotency_key,
            "status": "SUCCEEDED",
            "result": chosen.result,
            "receipt_id": chosen.receipt_id,
        }
        coc = CanonicalOutcomeCommit(
            **coc_base,
            coc_hash=stable_hash(coc_base),
        )
        return coc, ReconciliationRecord(
            action_id=dar.action_id,
            accepted_receipt_id=chosen.receipt_id,
            rejected=tuple(sorted(rejected)),
        )
