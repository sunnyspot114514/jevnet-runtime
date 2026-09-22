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


class TemporarilyUnavailableIdempotentProvider:
    def __init__(self):
        self.capabilities=ProviderCapabilities(
            supports_idempotency=True,
            supports_status_query=True,
            supports_fencing=False,
        )
        self.available=False
        self.effects={}

    def advance_fence(self,fence):
        pass

    def query(self,idempotency_key):
        if not self.available:
            raise AmbiguousProviderOutcome("query outage")
        return self.effects.get(idempotency_key)

    def dispatch(self,**kwargs):
        if not self.available:
            raise AmbiguousProviderOutcome("post outage")
        key=kwargs["idempotency_key"]
        if key not in self.effects:
            self.effects[key]=ProviderReceipt(
                receipt_id="R1",
                action_id=kwargs["action_id"],
                auth_id=kwargs["auth_id"],
                proposal_hash=kwargs["proposal_hash"],
                idempotency_key=key,
                fence=kwargs["fence"],
                status="SUCCEEDED",
                result=kwargs["result"],
            )
        return self.effects[key]


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
    p=build_proposal("P1",[ToolCallProposal("local.write_file",{"path":"x"})])
    d=issue_dar(
        proposal=p,
        votes=[build_vote("A1",p,True),build_vote("A2",p,True)],
        threshold=2,
        manifest=m,
        action_id="A1",
        auth_id="AUTH1",
        idempotency_key="ID1",
        auth_generation=1,
    )
    assert d is not None
    return d


def test_retriable_unresolved_can_resume_when_idempotent_provider_recovers():
    m=manifest()
    store=InMemoryDurableStore()
    leases=InMemoryLeaseCoordinator()
    provider=TemporarilyUnavailableIdempotentProvider()
    rt=DurableRuntime(m)
    rt.persist_dar(store=store,stream_id="A1",dar=dar(m))

    first=rt.recover_action(
        store=store,
        stream_id="A1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R1",
    )
    assert isinstance(first,UnresolvedOutcome)
    assert first.retry_safe is True

    provider.available=True
    second=DurableRuntime(m).recover_action(
        store=store,
        stream_id="A1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R2",
    )
    assert second is not None
    assert not isinstance(second,UnresolvedOutcome)
    assert len(provider.effects)==1
