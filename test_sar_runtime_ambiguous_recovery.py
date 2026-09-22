from dataclasses import dataclass, field

from sar_runtime import (
    AmbiguousProviderOutcome,
    CapabilityManifest,
    CapabilityManifestEntry,
    DurableRuntime,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    ProviderCapabilities,
    ProviderReceipt,
    ToolCallProposal,
    UnresolvedOutcome,
    build_proposal,
    build_vote,
    issue_dar,
)


class NonReconcilableProvider:
    """Effect may happen, but provider exposes no idempotency or status query."""

    def __init__(self):
        self.capabilities = ProviderCapabilities(
            supports_idempotency=False,
            supports_status_query=False,
            supports_compensation=False,
            supports_fencing=False,
        )
        self.effects = 0
        self.calls = 0

    def advance_fence(self, fence: int) -> None:
        pass

    def dispatch(
        self,
        *,
        action_id,
        auth_id,
        proposal_hash,
        idempotency_key,
        fence,
        result,
    ):
        self.calls += 1
        self.effects += 1
        raise AmbiguousProviderOutcome(
            "effect applied, response lost"
        )

    def query(self, idempotency_key):
        return None


class NoQueryIdempotentProvider:
    """Ambiguous first response is safe to retry because provider deduplicates."""

    def __init__(self):
        self.capabilities = ProviderCapabilities(
            supports_idempotency=True,
            supports_status_query=False,
            supports_fencing=False,
        )
        self.effects = {}
        self.calls = 0
        self.first = True

    def advance_fence(self, fence: int) -> None:
        pass

    def dispatch(
        self,
        *,
        action_id,
        auth_id,
        proposal_hash,
        idempotency_key,
        fence,
        result,
    ):
        self.calls += 1
        if idempotency_key not in self.effects:
            self.effects[idempotency_key] = ProviderReceipt(
                receipt_id="REC-1",
                action_id=action_id,
                auth_id=auth_id,
                proposal_hash=proposal_hash,
                idempotency_key=idempotency_key,
                fence=fence,
                status="SUCCEEDED",
                result=result,
            )
            if self.first:
                self.first = False
                raise AmbiguousProviderOutcome(
                    "effect applied, response lost"
                )
        return self.effects[idempotency_key]

    def query(self, idempotency_key):
        return None


def manifest():
    return CapabilityManifest(
        version=1,
        entries=[
            CapabilityManifestEntry(
                tool_id="local.write_file",
                effect_class="local_content_write",
                scope="local",
                reversible=True,
            )
        ],
        allowed_effects={"local_content_write"},
    )


def dar(m):
    p = build_proposal(
        "P1",
        [ToolCallProposal("local.write_file", {"path":"notes.md"})],
    )
    out = issue_dar(
        proposal=p,
        votes=[
            build_vote("A1",p,True),
            build_vote("A2",p,True),
        ],
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert out is not None
    return out


def test_ambiguous_nonreconcilable_provider_never_blindly_retries():
    m=manifest()
    runtime=DurableRuntime(m)
    store=InMemoryDurableStore()
    leases=InMemoryLeaseCoordinator()
    provider=NonReconcilableProvider()
    runtime.persist_dar(store=store,stream_id="ACT-1",dar=dar(m))

    first=runtime.recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R1",
    )

    assert isinstance(first,UnresolvedOutcome)
    assert first.retry_safe is False
    assert provider.effects==1
    assert store.find_first("ACT-1","CanonicalOutcomeCommit") is None

    # New process / recovery attempt sees the durable unresolved state and
    # refuses to touch the provider again.
    second=DurableRuntime(m).recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R2",
    )

    assert second==first
    assert provider.effects==1
    assert provider.calls==1


def test_idempotent_provider_may_retry_ambiguous_response_safely():
    m=manifest()
    runtime=DurableRuntime(m)
    store=InMemoryDurableStore()
    leases=InMemoryLeaseCoordinator()
    provider=NoQueryIdempotentProvider()
    runtime.persist_dar(store=store,stream_id="ACT-1",dar=dar(m))

    result=runtime.recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R1",
    )

    assert result is not None
    assert not isinstance(result,UnresolvedOutcome)
    assert len(provider.effects)==1
    assert provider.calls==2


def test_preexisting_intent_without_receipt_and_without_reconciliation_stays_unknown():
    m=manifest()
    runtime=DurableRuntime(m)
    store=InMemoryDurableStore()
    leases=InMemoryLeaseCoordinator()
    d=dar(m)
    runtime.persist_dar(store=store,stream_id="ACT-1",dar=d)

    # Simulate crash after durable intent and after an unobservable effect,
    # before a receipt could be written.
    lease=leases.acquire("workspace","R1")
    intent=runtime.engine.build_dispatch_intent(dar=d,fence=lease.fence)
    store.append("ACT-1",intent)

    provider=NonReconcilableProvider()
    provider.effects=1  # real world already changed; runtime cannot query it

    out=DurableRuntime(m).recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R2",
    )

    assert isinstance(out,UnresolvedOutcome)
    assert provider.effects==1
    assert provider.calls==0
