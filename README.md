# JevNet Runtime: From Jev Topologies to a State-Aware Agent Runtime

[🇺🇸 English](README.md) | [🇨🇳 中文说明](README.zh-CN.md)

JevNet Runtime began with a narrow question: **can Jev/SystemOne act as a typed computation primitive inside MLP-, RNN-, GNN-, Transformer-, and connectome-shaped graphs?**

The experiments converged on a stronger systems result:

> **Model output should have Proposal Authority, not State Authority.**

The current project focuses on a model-agnostic **State-Aware Runtime (SAR)** for long-horizon agents: typed proposals, capability manifests, durable authorization, idempotent and fenced execution, observation reconciliation, canonical outcome commits, and replicated commit safety.

The reusable core lives in [`sar_runtime/`](sar_runtime/). Jev is now an optional semantic proposer / router / authorizer above the runtime rather than part of the trusted runtime core.

## Current Status

- **Reusable `sar_runtime` package is working locally.**
- Capability-manifest validation, quorum DAR, durable recovery, idempotency, fencing, receipt reconciliation, COC construction, and replicated commit certificates are implemented as model-agnostic interfaces.
- Fresh capability benchmark: **Planner + Capability Manifest = 24/24 authorization-correct**; direct semantic quorum is **22/24** and repeats a correlated `chmod` permission-change false authorization.
- Planner tool selection is imperfect (**67/72 tool votes correct**), yet capability gating still keeps all 24 authorization outcomes correct by failing closed.
- Reduced 5-replica / quorum-3 / 3-ballot COC checker exhaustively explores **442,524 states / 1,818,882 transitions** with **0 conflicting chosen COCs** in the stated reduced single-slot model.
- A broader crash/partition model remains explicitly **inconclusive** because it reaches the state cap.
- Real MaleCNS type-level and body-level connectome motifs were also tested as Jev message-passing graphs; these experiments exposed soft-probability provenance leakage and motivated canonical runtime gating.
- All committed regression tests pass locally.

## Core Idea

```text
Natural-language intent
        |
        v
Model / Jev proposal
        |
        v
ToolCallProposal
        |
        v
Capability Manifest
        |
        v
Deterministic validation
        |
        v
Authorization quorum
        |
        v
Durable Authorization Record
        |
        v
Dispatch Intent + lease/fence + idempotency
        |
        v
External provider effect
        |
        v
Provider Receipt
        |
        v
Reconciliation
        |
        v
Canonical Outcome Commit
        |
        v
Replicated Commit Certificate
        |
        v
Global canonical state
```

The model may be uncertain. The runtime decides when a model-generated interpretation acquires authority.

## Why This Exists

Long-horizon agents can fail before the final text surface:

1. uncertain model output becomes durable state too early;
2. the same action is retried after an ambiguous timeout;
3. a stale runtime replica keeps acting after lease handoff;
4. authorization is revoked while a command is in flight;
5. duplicate, forged, or conflicting observations arrive out of order;
6. a local COC is mistaken for global canonical truth;
7. multiple same-model authorizers share the same semantic blind spot.

JevNet Runtime turns these into explicit runtime contracts instead of treating them only as hidden model-behavior problems.

## Reusable Runtime Package

The [`sar_runtime`](sar_runtime/) package currently exposes typed records for proposals, capability validation, authorization, dispatch, receipts, reconciliation, COC, and replicated commit certificates.

Core interfaces / reference implementations:

```text
CapabilityManifest
DurableStore / InMemoryDurableStore
ProviderAdapter / InMemoryProvider
LeaseCoordinator / InMemoryLeaseCoordinator
RuntimeEngine
DurableRuntime
build_commit_certificate()
validate_commit_certificate()
```

The core package has no model dependency.

## Key Experimental Results

### Same-model quorum does not eliminate correlated semantic error

Three identical Jev authorizers unanimously approved an actual permission-changing command, with roughly `P(APPROVE) ≈ 0.93`. A fresh benchmark reproduced the issue with different wording.

This shows that 2-of-3 quorum handles one bad voter, but not a shared model misconception.

### Capability Manifest contains the correlated error

The planner+manifest path maps the fresh case to:

```text
filesystem.chmod
    -> permission_change
    -> forbidden
    -> no DAR
```

Fresh benchmark:

| Pipeline | Authorization accuracy |
|---|---:|
| Direct semantic quorum | 22/24 |
| **Planner + Capability Manifest** | **24/24** |

The planner itself is not perfect. Correctness comes from narrowing model authority, not from assuming a perfect planner.

### Durable recovery survives process amnesia

A 10,000-action stress run included 6,093 simulated crashes and 473 duplicate durable records.

Final audit:
- unauthorized effects: 0
- missing authorized effects: 0
- unauthorized COCs: 0
- missing authorized COCs: 0
- canonical digest drift after replay: 0

### Idempotency and fencing solve different races

- **Idempotency** prevents replay of the same authorized action.
- **Fencing** prevents an old execution owner from issuing a different stale action after lease handoff.

### Replicated COC safety

Reduced 5-replica / quorum-3 / 3-ballot checker:

```text
states       = 442,524
transitions  = 1,818,882
state cap    = not hit
conflicting COC states = 0
```

This is a finite single-slot safety result, not a full Paxos/Raft proof.

## Repository Structure

```text
sar_runtime/
  types.py
  manifest.py
  authorization.py
  adapters.py
  provider.py
  store.py
  lease.py
  durable_runtime.py
  runtime.py
  consensus.py
  builders.py
  README.md

ROUND*.md
ReplicatedCOC.tla
ReplicatedCOC_*.cfg

jev_authorizer_*.py
jev_capability_*.py
replicated_log_*.py
flygraph_*.py
runtime_state_*.py
test_*.py
```

Generated result directories and API secrets are intentionally ignored by Git.

## Quick Start

Python 3.12 is recommended.

```bash
git clone https://github.com/sunnyspot114514/jevnet-runtime.git
cd jevnet-runtime
python -m pip install -e .
python -m pip install -e ".[research]"
python -m pytest -q
```

Minimal crash-recoverable runtime:

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
votes = [build_vote("A1", proposal, True), build_vote("A2", proposal, True)]

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

## Running Jev Experiments

The reusable runtime does not require Jev. Research experiments use a local, git-ignored `.env`:

```text
TYPESAFE_API_KEY=...
```

Runner and benchmark hashes are recorded in the corresponding research reports.

## Research Archive

See [RESEARCH_INDEX.md](RESEARCH_INDEX.md) for the full experiment lineage from topology analogues and FlyGraph to crash recovery, distributed authorization, replicated COC, capability manifests, and the reusable runtime package.

## Reproduction Level

This repository currently provides:
- frozen Jev authorization benchmarks with runner/benchmark hashes;
- model-agnostic runtime interfaces and in-memory references;
- deterministic capability gating and quorum authorization;
- durable crash recovery;
- idempotent / fenced provider semantics;
- receipt reconciliation and COC construction;
- finite replicated-log safety checkers;
- a TLA+ single-slot COC specification;
- real MaleCNS-derived graph experiments;
- regression tests for runtime and research invariants.

It does **not** claim:
- production-grade consensus or storage correctness;
- a complete Paxos/Raft proof;
- liveness under arbitrary asynchronous scheduling;
- Byzantine provider tolerance;
- universal semantic authorization accuracy;
- that repeated calls to one model provide independent evidence;
- that biological connectome topology is generally superior to random topology.

## Core Principle

> **Probabilistic systems propose interpretations. Deterministic durable protocols decide when those interpretations acquire authority.**

## License

Apache License 2.0. See [LICENSE](LICENSE).
