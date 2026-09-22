import tempfile
from pathlib import Path

from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    ContextProjector,
    DurableRuntime,
    EventSourcedStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    SessionLog,
    SQLiteDurableStore,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)


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


def make_dar(m):
    p=build_proposal(
        "P1",
        [ToolCallProposal("local.write_file",{"path":"notes.md","content":"hello"})],
    )
    d=issue_dar(
        proposal=p,
        votes=[build_vote("A1",p,True),build_vote("A2",p,True)],
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert d is not None
    return d


def test_sqlite_store_round_trips_typed_records_after_reopen(tmp_path):
    db=tmp_path/"runtime.db"
    m=manifest()
    d=make_dar(m)

    s1=SQLiteDurableStore(db)
    s1.append("ACT-1",d)

    s2=SQLiteDurableStore(db)
    restored=s2.find_first("ACT-1","DurableAuthorizationRecord")
    assert restored==d
    assert s2.read("ACT-1")== (d,)


def test_sqlite_runtime_reopen_preserves_coc_and_deduplicates_provider_effect(tmp_path):
    db=tmp_path/"runtime.db"
    m=manifest()
    provider=InMemoryProvider()
    leases=InMemoryLeaseCoordinator()

    s1=SQLiteDurableStore(db)
    rt1=DurableRuntime(m)
    d=make_dar(m)
    rt1.persist_dar(store=s1,stream_id="ACT-1",dar=d)
    coc1=rt1.recover_action(
        store=s1,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R1",
    )
    assert coc1 is not None
    assert len(provider.effects)==1

    # New runtime and new SQLite store object simulate process-state loss.
    s2=SQLiteDurableStore(db)
    rt2=DurableRuntime(m)
    coc2=rt2.recover_action(
        store=s2,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R2",
    )
    assert coc2==coc1
    assert len(provider.effects)==1


def test_sqlite_context_view_survives_store_reopen(tmp_path):
    db=tmp_path/"runtime.db"
    m=manifest()
    provider=InMemoryProvider()
    leases=InMemoryLeaseCoordinator()

    backing1=SQLiteDurableStore(db)
    session1=SessionLog(backing1,"session:S1")
    session1.append("conversation/message",{"role":"user","content":"write hello"})
    session1.append("memory/committed",{"key":"scope","value":"local"})

    runtime_store1=EventSourcedStore(backing1)
    d=make_dar(m)
    rt=DurableRuntime(m)
    rt.persist_dar(store=runtime_store1,stream_id="ACT-1",dar=d)
    rt.recover_action(
        store=runtime_store1,
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="R1",
    )

    before=ContextProjector(
        session=session1,
        runtime_store=runtime_store1,
    ).project(["ACT-1"]).as_prompt_state()

    backing2=SQLiteDurableStore(db)
    after=ContextProjector(
        session=SessionLog(backing2,"session:S1"),
        runtime_store=EventSourcedStore(backing2),
    ).project(["ACT-1"]).as_prompt_state()

    assert after==before
    assert after["actions"][0]["status"]=="CANONICAL_SUCCEEDED"
