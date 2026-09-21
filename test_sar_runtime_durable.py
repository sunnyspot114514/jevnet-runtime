from sar_runtime import (
    AuthorizationVote,
    CapabilityManifest,
    CapabilityManifestEntry,
    DurableRuntime,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    ProviderCapabilities,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)


def manifest(version=1):
    return CapabilityManifest(
        version=version,
        entries=[
            CapabilityManifestEntry(
                tool_id="local.write_file",
                effect_class="local_content_write",
                scope="local",
                reversible=True,
            ),
            CapabilityManifestEntry(
                tool_id="filesystem.chmod",
                effect_class="permission_change",
                scope="machine",
                reversible=True,
            ),
        ],
        allowed_effects={"local_content_write"},
    )


def make_dar(m):
    p=build_proposal(
        "P1",
        [ToolCallProposal("local.write_file",{"path":"notes.md","target_scope":"local"})],
    )
    votes=[build_vote(a,p,True) for a in ("A1","A2")]
    dar=issue_dar(
        proposal=p,
        votes=votes,
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert dar is not None
    return dar


def test_recovery_from_durable_state_only_is_idempotent():
    m=manifest()
    runtime=DurableRuntime(m)
    store=InMemoryDurableStore()
    leases=InMemoryLeaseCoordinator()
    provider=InMemoryProvider(
        capabilities=ProviderCapabilities(
            supports_idempotency=True,
            supports_status_query=True,
            supports_fencing=True,
        )
    )
    dar=make_dar(m)
    runtime.persist_dar(store=store,stream_id="ACT-1",dar=dar)

    first=runtime.recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="resource-1",
        owner_id="R1",
    )
    assert first is not None
    assert len(provider.effects)==1

    # Simulate repeated process restarts. No volatile runtime object is reused.
    for owner in ("R2","R3","R4"):
        fresh_runtime=DurableRuntime(m)
        coc=fresh_runtime.recover_action(
            store=store,
            stream_id="ACT-1",
            provider=provider,
            leases=leases,
            resource_id="resource-1",
            owner_id=owner,
        )
        assert coc==first

    assert len(provider.effects)==1
    names=[type(x).__name__ for x in store.read("ACT-1")]
    assert names.count("DurableAuthorizationRecord")==1
    assert names.count("CanonicalOutcomeCommit")==1


def test_no_dar_means_no_effect():
    m=manifest()
    runtime=DurableRuntime(m)
    store=InMemoryDurableStore()
    leases=InMemoryLeaseCoordinator()
    provider=InMemoryProvider()

    coc=runtime.recover_action(
        store=store,
        stream_id="missing",
        provider=provider,
        leases=leases,
        resource_id="resource-1",
        owner_id="R1",
    )
    assert coc is None
    assert len(provider.effects)==0


def test_stale_manifest_blocks_recovery_before_effect():
    m1=manifest(version=1)
    store=InMemoryDurableStore()
    dar=make_dar(m1)
    DurableRuntime(m1).persist_dar(store=store,stream_id="ACT-1",dar=dar)

    m2=manifest(version=2)
    provider=InMemoryProvider()
    leases=InMemoryLeaseCoordinator()

    try:
        DurableRuntime(m2).recover_action(
            store=store,
            stream_id="ACT-1",
            provider=provider,
            leases=leases,
            resource_id="resource-1",
            owner_id="R2",
        )
    except ValueError as e:
        assert str(e)=="STALE_MANIFEST_VERSION"
    else:
        raise AssertionError("stale manifest should reject old DAR")

    assert len(provider.effects)==0


def test_lease_fence_monotonic_across_recovery_owners():
    leases=InMemoryLeaseCoordinator()
    a=leases.acquire("resource-1","R1")
    b=leases.acquire("resource-1","R2")
    assert b.fence>a.fence
    assert leases.current("resource-1")==b
    assert leases.release(a) is False
    assert leases.release(b) is True
