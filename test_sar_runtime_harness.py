from dataclasses import dataclass

import pytest

from sar_runtime import (
    ApprovalService,
    CapabilityManifest,
    CapabilityManifestEntry,
    EventSourcedStore,
    InMemoryDurableStore,
    SessionEvent,
    SessionLog,
    ToolCallProposal,
    build_default_harness,
    build_proposal,
    build_vote,
    issue_dar,
)
from sar_runtime.plugins import PluginContext, PluginManager, ValuePlugin


def manifest():
    return CapabilityManifest(
        version=1,
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


def test_default_harness_is_plugin_composed():
    h=build_default_harness(manifest())
    topo=h.topology()
    assert topo["services"]["manifest"]=="manifest"
    assert topo["services"]["backing_store"]=="backing-store"
    assert topo["services"]["store"]=="event-store"
    assert topo["services"]["durable_runtime"]=="runtime"


@dataclass
class NeedsMissing:
    name:str="broken"
    requires:tuple[str,...]=("missing-service",)
    def setup(self,ctx:PluginContext):
        raise AssertionError("must not activate")


def test_unresolved_plugin_dependency_fails_loudly():
    m=PluginManager()
    m.install(NeedsMissing())
    with pytest.raises(RuntimeError,match="UNRESOLVED_PLUGIN_DEPENDENCIES"):
        m.start()


def test_duplicate_service_provider_is_rejected_and_rolls_back():
    m=PluginManager()
    m.install(ValuePlugin("a","service",1))
    m.install(ValuePlugin("b","service",2))
    with pytest.raises(RuntimeError,match="SERVICE_ALREADY_PROVIDED"):
        m.start()
    assert m.services.snapshot()=={}


def test_event_sourced_store_keeps_append_only_session_events():
    backing=InMemoryDurableStore()
    store=EventSourcedStore(backing)
    store.append("ACT-1",{"a":1})
    store.append("ACT-1",{"b":2})

    physical=backing.read("runtime:ACT-1")
    assert len(physical)==2
    assert all(isinstance(x,SessionEvent) for x in physical)
    assert [x.sequence for x in physical]==[0,1]
    assert store.read("ACT-1")==({"a":1},{"b":2})


def test_session_fold_replays_from_log():
    backing=InMemoryDurableStore()
    log=SessionLog(backing,"S1")
    log.append("counter/add",{"value":2})
    log.append("counter/add",{"value":3})

    total=log.fold(
        0,
        lambda state,event: (
            state+event.payload["value"]
            if event.event_type=="counter/add"
            else state
        ),
    )
    assert total==5


def test_approval_without_answerer_is_unavailable_and_fail_closed():
    backing=InMemoryDurableStore()
    log=SessionLog(backing,"S1")
    approval=ApprovalService(session=log,default_policy="ask",answerers=[])
    result=approval.request(action_id="A1",summary="external action")
    assert result=="unavailable"
    assert approval.grants(result) is False
    assert [e.event_type for e in log.events()]==[
        "approval/asked","approval/decided"
    ]


def test_approval_never_policy_is_durable_and_replayable():
    backing=InMemoryDurableStore()
    log=SessionLog(backing,"S1")
    approval=ApprovalService(session=log)
    approval.set_policy("never")
    assert approval.request(action_id="A1",summary="x")=="rejected"

    recreated=ApprovalService(session=SessionLog(backing,"S1"))
    assert recreated.effective_policy()=="never"


def test_approval_allowed_once_grants_only_closed_outcome():
    backing=InMemoryDurableStore()
    log=SessionLog(backing,"S1")
    approval=ApprovalService(
        session=log,
        answerers=[lambda req:"allowed-once"],
    )
    outcome=approval.request(action_id="A1",summary="local edit")
    assert outcome=="allowed-once"
    assert approval.grants(outcome) is True


def test_approval_request_ids_continue_after_restart():
    backing=InMemoryDurableStore()
    first=ApprovalService(
        session=SessionLog(backing,"S1"),
        answerers=[lambda req:"rejected"],
    )
    first.request(action_id="A1",summary="one")

    second=ApprovalService(
        session=SessionLog(backing,"S1"),
        answerers=[lambda req:"rejected"],
    )
    second.request(action_id="A2",summary="two")

    asked=[
        e.payload.request_id
        for e in SessionLog(backing,"S1").events()
        if e.event_type=="approval/asked"
    ]
    assert asked==["approval-1","approval-2"]


def test_harness_runtime_records_are_event_sourced_and_recoverable():
    h=build_default_harness(manifest())
    p=build_proposal(
        "P1",
        [ToolCallProposal("local.write_file",{"path":"notes.md"})],
    )
    dar=issue_dar(
        proposal=p,
        votes=[build_vote("A1",p,True),build_vote("A2",p,True)],
        threshold=2,
        manifest=h.service("manifest"),
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert dar is not None

    rt=h.service("durable_runtime")
    rt.persist_dar(store=h.service("store"),stream_id="ACT-1",dar=dar)
    coc=rt.recover_action(
        store=h.service("store"),
        stream_id="ACT-1",
        provider=h.service("provider"),
        leases=h.service("leases"),
        resource_id="workspace",
        owner_id="R1",
    )
    assert coc is not None

    events=h.service("store").event_log("ACT-1").events()
    kinds=[e.event_type for e in events]
    assert "runtime/DurableAuthorizationRecord" in kinds
    assert "runtime/DispatchIntent" in kinds
    assert "runtime/ProviderReceipt" in kinds
    assert "runtime/ReconciliationRecord" in kinds
    assert "runtime/CanonicalOutcomeCommit" in kinds
