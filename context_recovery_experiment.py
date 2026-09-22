#!/usr/bin/env python3
"""Coupled recovery experiment: runtime state + model context/memory view.

The experiment compares:
1. a normal execution followed by context projection;
2. a crash/restart execution where all volatile model memory is discarded and
   context is rebuilt solely from durable conversation/memory/runtime records.

A deliberately false volatile statement ("action succeeded") is injected before
crash but never committed. It must not appear in the recovered view.
"""

from __future__ import annotations

import json
from pathlib import Path

from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    ContextProjector,
    DurableRuntime,
    EventSourcedStore,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    SessionLog,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)

OUT = Path("context_recovery_experiment_analysis.json")


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


def setup_world():
    backing = InMemoryDurableStore()
    runtime_store = EventSourcedStore(backing)
    session = SessionLog(backing, "session:S1")
    leases = InMemoryLeaseCoordinator()
    provider = InMemoryProvider()
    m = manifest()

    session.append(
        "conversation/message",
        {"role": "user", "content": "Write hello to notes.md"},
    )
    session.append(
        "memory/committed",
        {"key": "workspace", "value": "local-only"},
    )

    proposal = build_proposal(
        "P1",
        [ToolCallProposal(
            "local.write_file",
            {"path": "notes.md", "content": "hello"},
        )],
    )
    dar = issue_dar(
        proposal=proposal,
        votes=[
            build_vote("A1", proposal, True),
            build_vote("A2", proposal, True),
        ],
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert dar is not None

    runtime = DurableRuntime(m)
    runtime.persist_dar(
        store=runtime_store,
        stream_id="ACT-1",
        dar=dar,
    )

    return {
        "backing": backing,
        "runtime_store": runtime_store,
        "session": session,
        "leases": leases,
        "provider": provider,
        "manifest": m,
    }


def project(world):
    return ContextProjector(
        session=SessionLog(world["backing"], "session:S1"),
        runtime_store=EventSourcedStore(world["backing"]),
    ).project(["ACT-1"])


def normal_path():
    world = setup_world()
    rt = DurableRuntime(world["manifest"])
    coc = rt.recover_action(
        store=world["runtime_store"],
        stream_id="ACT-1",
        provider=world["provider"],
        leases=world["leases"],
        resource_id="workspace",
        owner_id="R1",
    )
    assert coc is not None
    return world, project(world)


def crash_recovery_path():
    world = setup_world()

    # Volatile model memory may be wrong. It is intentionally not durable.
    volatile_memory = {
        "last_action": "ACT-1",
        "belief": "action succeeded",
        "source": "model guess before provider reconciliation",
    }

    # Simulate process loss: the volatile object disappears completely.
    del volatile_memory

    fresh_runtime = DurableRuntime(world["manifest"])
    coc = fresh_runtime.recover_action(
        store=EventSourcedStore(world["backing"]),
        stream_id="ACT-1",
        provider=world["provider"],
        leases=world["leases"],
        resource_id="workspace",
        owner_id="R2",
    )
    assert coc is not None

    # A fresh projector has no access to the old process or its memory.
    recovered = project(world)
    return world, recovered


def main():
    normal_world, normal_view = normal_path()
    recovered_world, recovered_view = crash_recovery_path()

    normal = normal_view.as_prompt_state()
    recovered = recovered_view.as_prompt_state()

    assert normal == recovered
    assert normal["conversation"] == [
        {"role": "user", "content": "Write hello to notes.md"}
    ]
    assert normal["memory_facts"] == [
        {"key": "workspace", "value": "local-only"}
    ]
    assert normal["actions"][0]["status"] == "CANONICAL_SUCCEEDED"

    serialized = json.dumps(recovered, sort_keys=True)
    assert "model guess before provider reconciliation" not in serialized
    assert "belief" not in serialized

    result = {
        "views_equal": normal == recovered,
        "normal_view": normal,
        "recovered_view": recovered,
        "volatile_false_belief_present_after_recovery": False,
        "provider_effects_normal": len(normal_world["provider"].effects),
        "provider_effects_recovered": len(recovered_world["provider"].effects),
    }

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print("Coupled runtime/context recovery PASS")


if __name__ == "__main__":
    main()
