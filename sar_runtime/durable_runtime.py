from __future__ import annotations

from .adapters import ProviderAdapter
from .journal import append_once
from .lease import LeaseCoordinator
from .manifest import CapabilityManifest
from .runtime import RuntimeEngine
from .store import DurableStore
from .types import (
    CanonicalOutcomeCommit,
    DurableAuthorizationRecord,
    ProviderReceipt,
)


class DurableRuntime:
    """Crash-recoverable execution coordinator.

    Volatile process memory is intentionally not authoritative. Recovery starts
    from the durable stream, reacquires an execution fence, reconciles provider
    reality, and appends the canonical outcome.
    """

    def __init__(self, manifest: CapabilityManifest) -> None:
        self.manifest = manifest
        self.engine = RuntimeEngine(manifest)

    def persist_dar(
        self,
        *,
        store: DurableStore,
        stream_id: str,
        dar: DurableAuthorizationRecord,
    ) -> int:
        ok, reason = self.manifest.revalidate_dar(dar)
        if not ok:
            raise ValueError(reason)
        return append_once(store, stream_id, dar)

    def recover_action(
        self,
        *,
        store: DurableStore,
        stream_id: str,
        provider: ProviderAdapter,
        leases: LeaseCoordinator,
        resource_id: str,
        owner_id: str,
    ) -> CanonicalOutcomeCommit | None:
        existing_coc = store.find_first(stream_id, "CanonicalOutcomeCommit")
        if existing_coc is not None:
            return existing_coc

        dar = store.find_first(stream_id, "DurableAuthorizationRecord")
        if dar is None:
            return None

        ok, reason = self.manifest.revalidate_dar(dar)
        if not ok:
            raise ValueError(reason)

        lease = leases.acquire(resource_id, owner_id)
        intent = self.engine.build_dispatch_intent(dar=dar, fence=lease.fence)
        append_once(store, stream_id, intent)

        receipt = None
        if provider.capabilities.supports_status_query:
            receipt = provider.query(dar.idempotency_key)

        if receipt is None:
            receipt = self.engine.dispatch(
                dar=dar,
                intent=intent,
                provider=provider,
            )

        if isinstance(receipt, ProviderReceipt):
            append_once(store, stream_id, receipt)
        else:
            # Rejected provider responses (for example stale fencing) are not
            # ProviderReceipt objects and cannot become canonical observations.
            return None

        receipts = [
            row
            for row in store.read(stream_id)
            if isinstance(row, ProviderReceipt)
        ]
        coc, reconciliation = self.engine.reconcile(
            dar=dar,
            receipts=receipts,
        )
        append_once(store, stream_id, reconciliation)
        if coc is not None:
            append_once(store, stream_id, coc)
        return coc
