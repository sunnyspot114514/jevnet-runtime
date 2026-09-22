from __future__ import annotations

from .adapters import AmbiguousProviderOutcome, ProviderAdapter
from .journal import append_once
from .lease import LeaseCoordinator
from .manifest import CapabilityManifest
from .runtime import RuntimeEngine
from .store import DurableStore
from .types import (
    CanonicalOutcomeCommit,
    DispatchIntent,
    DurableAuthorizationRecord,
    ProviderReceipt,
    UnresolvedOutcome,
)


class DurableRuntime:
    """Crash-recoverable execution coordinator.

    Volatile process memory is intentionally not authoritative. Recovery starts
    from the durable stream, reacquires an execution fence, reconciles provider
    reality, and appends the canonical outcome.

    Critical rule: a pre-existing DispatchIntent without a receipt is *not*
    automatically retried. If the provider exposes neither idempotency nor a
    trustworthy status query, recovery cannot distinguish "effect happened,
    response lost" from "effect never happened". The action is durably marked
    unresolved and must be escalated instead of being executed again.
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

    def _unresolved(
        self,
        *,
        store: DurableStore,
        stream_id: str,
        dar: DurableAuthorizationRecord,
        reason: str,
    ) -> UnresolvedOutcome:
        unresolved = UnresolvedOutcome(
            action_id=dar.action_id,
            auth_id=dar.auth_id,
            idempotency_key=dar.idempotency_key,
            reason=reason,
            retry_safe=False,
            required_operator_action=(
                "RECONCILE_EXTERNALLY_OR_ESCALATE; DO_NOT_BLINDLY_RETRY"
            ),
        )
        append_once(store, stream_id, unresolved)
        return unresolved

    def _can_resolve_ambiguity(self, provider: ProviderAdapter) -> bool:
        caps = provider.capabilities
        return bool(
            caps.supports_status_query
            or caps.supports_idempotency
        )

    def recover_action(
        self,
        *,
        store: DurableStore,
        stream_id: str,
        provider: ProviderAdapter,
        leases: LeaseCoordinator,
        resource_id: str,
        owner_id: str,
    ) -> CanonicalOutcomeCommit | UnresolvedOutcome | None:
        existing_coc = store.find_first(stream_id, "CanonicalOutcomeCommit")
        if existing_coc is not None:
            return existing_coc

        existing_unresolved = store.find_first(stream_id, "UnresolvedOutcome")
        if existing_unresolved is not None:
            return existing_unresolved

        dar = store.find_first(stream_id, "DurableAuthorizationRecord")
        if dar is None:
            return None

        ok, reason = self.manifest.revalidate_dar(dar)
        if not ok:
            raise ValueError(reason)

        records = store.read(stream_id)
        existing_intents = [
            row for row in records
            if isinstance(row, DispatchIntent)
        ]
        existing_intent = (
            existing_intents[-1]
            if existing_intents
            else None
        )
        existing_receipt = next(
            (
                row for row in reversed(records)
                if isinstance(row, ProviderReceipt)
            ),
            None,
        )

        # A previous process may have crossed the provider boundary after
        # persisting intent but before persisting a receipt. With neither
        # idempotency nor status query, the two external worlds are
        # observationally indistinguishable and retry is unsafe.
        if (
            existing_intent is not None
            and existing_receipt is None
            and not self._can_resolve_ambiguity(provider)
        ):
            return self._unresolved(
                store=store,
                stream_id=stream_id,
                dar=dar,
                reason="PREEXISTING_INTENT_WITHOUT_RECONCILIATION_PRIMITIVE",
            )

        receipt = existing_receipt

        if receipt is None:
            # Recovery that may touch the provider must acquire fresh execution
            # ownership. A new owner receives a higher fence and appends a
            # superseding intent rather than silently reusing stale authority.
            lease = leases.acquire(resource_id, owner_id)
            intent = self.engine.build_dispatch_intent(
                dar=dar,
                fence=lease.fence,
            )
            if existing_intent != intent:
                append_once(store, stream_id, intent)

            if provider.capabilities.supports_status_query:
                receipt = provider.query(dar.idempotency_key)
        else:
            intent = existing_intent
            if intent is None:
                # A durable receipt without an intent violates the execution
                # protocol and must not be silently canonicalized.
                return self._unresolved(
                    store=store,
                    stream_id=stream_id,
                    dar=dar,
                    reason="RECEIPT_WITHOUT_DISPATCH_INTENT",
                )

        if receipt is None:
            try:
                receipt = self.engine.dispatch(
                    dar=dar,
                    intent=intent,
                    provider=provider,
                )
            except AmbiguousProviderOutcome:
                # Timeout / lost response is UNKNOWN, not failure.
                if provider.capabilities.supports_status_query:
                    receipt = provider.query(dar.idempotency_key)
                    if receipt is not None:
                        pass
                    elif provider.capabilities.supports_idempotency:
                        receipt = self.engine.dispatch(
                            dar=dar,
                            intent=intent,
                            provider=provider,
                        )
                    else:
                        return self._unresolved(
                            store=store,
                            stream_id=stream_id,
                            dar=dar,
                            reason=(
                                "AMBIGUOUS_PROVIDER_OUTCOME_"
                                "WITHOUT_IDEMPOTENT_RETRY"
                            ),
                        )
                elif provider.capabilities.supports_idempotency:
                    receipt = self.engine.dispatch(
                        dar=dar,
                        intent=intent,
                        provider=provider,
                    )
                else:
                    return self._unresolved(
                        store=store,
                        stream_id=stream_id,
                        dar=dar,
                        reason=(
                            "AMBIGUOUS_PROVIDER_OUTCOME_"
                            "WITHOUT_RECONCILIATION_PRIMITIVE"
                        ),
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
