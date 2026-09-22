# sar_runtime

Model-agnostic runtime primitives for turning AI-agent proposals into auditable, durable side effects.

This package is the reusable core of [JevNet Runtime](../README.md).

## Install

```bash
python -m pip install -e .
```

Run the zero-key demo:

```bash
python -m sar_runtime demo
```

## Core interfaces

```text
CapabilityManifest
DurableStore
ProviderAdapter
LeaseCoordinator
RuntimeEngine
DurableRuntime
ApprovalService
PluginManager
EventSourcedStore
```

Reference implementations:

```text
InMemoryDurableStore
SQLiteDurableStore
InMemoryProvider
SQLiteProviderAdapter
HTTPProviderAdapter
InMemoryLeaseCoordinator
SQLiteLeaseCoordinator
HTTPLeaseCoordinator
```

The SQLite references use WAL + `synchronous=FULL`. `SQLiteDurableStore` also verifies a per-record SHA-256 during replay. These backends are intended for local/process-restart testing and are not presented as validated power-loss backends.

## Minimal execution flow

```python
from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    DurableRuntime,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)

manifest = CapabilityManifest(
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

proposal = build_proposal(
    "P1",
    [ToolCallProposal("local.write_file", {"path": "notes.md"})],
)

dar = issue_dar(
    proposal=proposal,
    votes=[
        build_vote("A1", proposal, True),
        build_vote("A2", proposal, True),
    ],
    threshold=2,
    manifest=manifest,
    action_id="ACT-1",
    auth_id="AUTH-1",
    idempotency_key="IDEM-1",
    auth_generation=1,
)

store = InMemoryDurableStore()
leases = InMemoryLeaseCoordinator()
provider = InMemoryProvider()
runtime = DurableRuntime(manifest)

runtime.persist_dar(store=store, stream_id="ACT-1", dar=dar)

coc = runtime.recover_action(
    store=store,
    stream_id="ACT-1",
    provider=provider,
    leases=leases,
    resource_id="workspace",
    owner_id="worker-1",
)
```

## DSH-inspired composition

The optional `Harness` layer adds:

- dependency-aware plugins;
- named service seams;
- append-only event-sourced storage;
- fail-closed approval;
- replaceable provider/store/lease services.

```python
from sar_runtime import build_default_harness

h = build_default_harness(manifest)
print(h.topology())
```

The package does not implement a full agent loop, UI, MCP stack, or OS sandbox.

See [../docs/DSH_INSPIRATION.md](../docs/DSH_INSPIRATION.md) and [../docs/HTTP_CONTRACT.md](../docs/HTTP_CONTRACT.md).

## Ambiguous outcomes and model context

If a provider has neither idempotency nor status query, an ambiguous post-dispatch timeout is persisted as `UnresolvedOutcome` and is never blindly retried.

On process recovery, any execution that still needs to touch the provider acquires a fresh lease/fence and may append a superseding `DispatchIntent`. Old execution authority is not silently reused.

`ContextProjector` reconstructs model-visible conversation, committed memory, and action status from durable records. Uncommitted volatile beliefs do not become context after restart.

## Authority rule

A model-generated value does not become authoritative merely because it is high-confidence.

The package upgrades authority explicitly:

```text
proposal
-> validated capability
-> authorization
-> durable dispatch intent
-> observed receipt
-> canonical outcome
-> replicated commit evidence
```

## Status

Research prototype / developer preview.

The in-memory implementations are reference backends for testing protocol semantics. Production deployments should supply durable storage and real provider/lease adapters.