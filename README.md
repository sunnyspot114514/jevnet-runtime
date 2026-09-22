# JevNet Runtime

[![CI](https://github.com/sunnyspot114514/jevnet-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/sunnyspot114514/jevnet-runtime/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

[🇺🇸 English](README.md) | [🇨🇳 中文](README.zh-CN.md)

**A durable side-effect runtime for AI agents.**

JevNet Runtime sits between an agent and the outside world. The model may propose a tool call; the runtime decides whether that proposal is allowed to become a real, durable side effect.

> **Models propose. The runtime authorizes, executes, observes, and commits.**

The reusable runtime is model-agnostic. **Jev is the historical origin of the research, not a dependency of the runtime package.**

## 60-second demo

```bash
git clone https://github.com/sunnyspot114514/jevnet-runtime.git
cd jevnet-runtime
python -m pip install -e .
python -m sar_runtime demo
```

Expected shape of the output:

```text
1) Correlated model approval does not override capability policy
   semantic votes: APPROVE / APPROVE / APPROVE
   tool: filesystem.chmod -> permission_change
   DAR issued: False

2) Allowed local capability executes through durable runtime
   external effects: 1
   COC status: SUCCEEDED

3) Restart/replay does not duplicate the effect
   same COC: True
   external effects after restart: 1

4) Approval seam fails closed
   no answerer -> unavailable
   grants authority: False
```

No API key is required for this demo.

## What problem does it solve?

Agent tool calls become dangerous when model output is treated as execution authority.

JevNet Runtime adds explicit runtime boundaries:

| Failure mode | Runtime mechanism |
|---|---|
| Model says a risky tool is safe | Runtime-owned **Capability Manifest** |
| Same action is retried after timeout | **Idempotency** + provider query |
| Old worker wakes up after failover | **Lease fencing** |
| Approval is missing or broken | **Fail-closed approval** |
| Process crashes mid-action | **Event-sourced durable replay** |
| Forged / conflicting receipts arrive | **Reconciliation** |
| One replica claims a final result | **Replicated commit certificate** |

The runtime narrows what a model mistake is allowed to do.

## The mental model

You only need five boxes to understand the project:

```text
Agent / Model
     |
     v
  Proposal
     |
     v
Policy + Capability Gate
     |
     v
Durable Execution
     |
     v
Observed Outcome
     |
     v
Canonical Commit
```

Under the hood, those stages are represented by typed records such as:

```text
ToolCallProposal
DurableAuthorizationRecord
DispatchIntent
ProviderReceipt
CanonicalOutcomeCommit
```

The longer authority chain is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## A concrete example

Suppose an agent proposes:

```python
ToolCallProposal(
    tool_id="filesystem.chmod",
    args={"path": "deploy.sh", "mode": "755"},
)
```

Even if three semantic reviewers all say "APPROVE", the runtime looks up the tool in its own manifest:

```text
filesystem.chmod
-> effect_class = permission_change
-> policy = forbidden
-> no authorization record
-> no external effect
```

The model does not get to redefine what the tool means.

For an allowed tool such as `local.write_file`, the runtime can issue a durable authorization record, acquire an execution fence, dispatch idempotently, reconcile the provider receipt, and commit the outcome.

## Install

Python 3.12 is recommended.

```bash
python -m pip install -e .
```

For the research experiments:

```bash
python -m pip install -e ".[research]"
```

Run the full test suite:

```bash
python -m pytest -q
```

Or use the repository check scripts:

```bash
./scripts/check.sh
```

```powershell
.\scripts\check.ps1
```

## Minimal API

```python
from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    DurableRuntime,
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

votes = [
    build_vote("reviewer-1", proposal, True),
    build_vote("reviewer-2", proposal, True),
]

dar = issue_dar(
    proposal=proposal,
    votes=votes,
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
    owner_id="replica-1",
)
```

The in-memory implementations are references. Replace them with real storage, provider, and lease backends through the same seams.

## DSH-inspired harness design

The package borrows several architectural ideas from [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) without copying its implementation:

- **service/plugin seams** — runtime providers are replaceable rather than hard-coded;
- **event-sourced sessions** — durable records are replayed from an append-only log;
- **fail-closed approval** — missing or broken approval never becomes an implicit grant;
- **per-call policy resolution** — execution policy is resolved at the capability boundary, not stored as mutable provider-global state.

JevNet Runtime stays deliberately smaller. It does not try to reproduce DSH's full agent loop, UI, MCP stack, sandbox implementation, or plugin ecosystem.

See [docs/DSH_INSPIRATION.md](docs/DSH_INSPIRATION.md) for the design crosswalk.

## Plugin and service composition

The default harness is assembled from replaceable services:

```python
from sar_runtime import build_default_harness

harness = build_default_harness(manifest)
print(harness.topology())
```

Default services include:

```text
manifest
backing_store
event-sourced store
provider
lease coordinator
durable runtime
```

A plugin activates only after all declared dependencies exist. Missing dependencies and duplicate service providers fail loudly.

## Event-sourced state

`EventSourcedStore` records runtime transitions as append-only events:

```text
runtime/DurableAuthorizationRecord
runtime/DispatchIntent
runtime/ProviderReceipt
runtime/ReconciliationRecord
runtime/CanonicalOutcomeCommit
```

After a process restart, the runtime reconstructs execution from durable records and provider reality instead of trusting in-memory state.

## Approval is fail-closed

`ApprovalService` uses a closed outcome set:

```text
allowed-once
rejected
cancelled
unavailable
```

Only `allowed-once` grants authority. A missing or broken answerer resolves to `unavailable`.

## What is already implemented?

### Runtime core

- Capability Manifest
- distinct-voter authorization quorum
- Durable Authorization Record
- DurableStore interface
- event-sourced storage adapter
- ProviderAdapter interface
- LeaseCoordinator interface
- idempotency
- fencing
- durable crash recovery
- receipt reconciliation
- Canonical Outcome Commit
- replicated commit certificate helpers
- plugin/service registry
- fail-closed approval seam
- CLI demo

### Reference implementations

- `InMemoryDurableStore`
- `InMemoryProvider`
- `InMemoryLeaseCoordinator`
- `EventSourcedStore`

## Research evidence

You do **not** need the research history to use the package.

A few results that directly motivate the current design:

- Three identical Jev reviewers unanimously approved a real `chmod` permission change in two separate frozen benchmarks.
- Planner + Capability Manifest produced **24/24 authorization-correct outcomes** on a fresh benchmark, even though planner tool selection itself was imperfect.
- A 10,000-action crash/replay stress test produced **0 unauthorized effects**, **0 missing authorized effects**, and **0 replay digest drift**.
- A reduced 5-replica / quorum-3 / 3-ballot checker exhaustively explored **442,524 states / 1,818,882 transitions** with no conflicting chosen COC in that stated finite model.

These are research results, not production guarantees.

Full chronology: [RESEARCH_INDEX.md](RESEARCH_INDEX.md).

## Repository layout

```text
sar_runtime/              reusable runtime package
docs/                     architecture and design notes
scripts/                  repo checks
test_sar_runtime_*.py     package-level tests

RESEARCH_INDEX.md         research archive entry point
ROUND*.md                 detailed experiment reports
replicated_log_*.py       explicit-state consensus experiments
jev_authorizer_*.py       frozen Jev authorization experiments
flygraph_*.py             historical topology/connectome experiments
```

The root README intentionally does not explain the full research history.

## What this is not

JevNet Runtime is currently a **research prototype / developer preview**.

It is not yet:

- a production sandbox;
- a complete agent framework;
- a replacement for DSH, LangGraph, Claude Code, or an OS security boundary;
- a complete Paxos/Raft implementation;
- a proof that same-model voting gives independent evidence;
- a claim that LLM hallucinations are "solved."

## Roadmap

The next practical backends are:

- SQLite / Postgres `DurableStore`
- HTTP/API `ProviderAdapter`
- Redis/etcd-style `LeaseCoordinator`
- compensation / Saga interface
- provider capability attestation
- crash-safe replicated-log backend
- model adapters that emit `ToolCallProposal` and `AuthorizationVote`

## Research history

The project originally explored Jev in neural-network and connectome-shaped computation graphs. That work is preserved because it exposed failure modes such as state loss and soft-probability provenance leakage.

It is no longer the main entry point.

**Start with the runtime. Read the research archive only if you want the derivation.**

## License

Apache License 2.0. See [LICENSE](LICENSE).
