# Round 13 — Ambiguous Recovery, Coupled Context Replay, and SQLite Hard-Crash Matrix

Date: 2026-09-22

This round addresses three important recovery boundaries that remained after the
earlier in-memory and model-checking work.

1. Ambiguous external effects without provider reconciliation primitives must
   not be blindly retried.
2. Runtime execution recovery must be coupled to model-visible context/memory
   reconstruction.
3. Reference persistence should move beyond a single in-memory process.

The results below are deliberately separated by evidence class.

---

## 1. Ambiguous provider outcome is now first-class runtime state

Problem:

A provider exposes neither:
- idempotency;
- nor authoritative status query.

The first dispatch applies the external effect, but the response is lost.

Old behavior:

- recovery sees no receipt;
- dispatches again;
- external effect count goes from 1 to 2;
- runtime may still commit SUCCEEDED.

That is unsafe.

### New rule

If the runtime has evidence that a dispatch may already have crossed the provider
boundary and the provider exposes no safe reconciliation primitive, the action
becomes:

UnresolvedOutcome

with:

retry_safe = false

required_operator_action =
RECONCILE_EXTERNALLY_OR_ESCALATE; DO_NOT_BLINDLY_RETRY

No COC is created.

---

## 2. Regression tests for the ambiguous-outcome gap

New package tests cover:

### Effect happened, response lost, no query/idempotency

Observed:

- provider effects after first attempt: 1
- provider effects after recovery: 1
- provider calls after second recovery: still 1
- CanonicalOutcomeCommit: absent
- durable UnresolvedOutcome: present

### Idempotent provider, no query

The first response is lost after the provider commits the effect.

Recovery is allowed to retry because the provider deduplicates by idempotency
key.

Observed:

- provider calls: 2
- provider effects: 1
- COC: present

### Pre-existing DispatchIntent after process crash

A durable intent exists, but there is no receipt and no provider query/idempotency
primitive.

Recovery does not touch the provider again.

This closes the reproduced 1 -> 2 effect bug.

---

## 3. Model context is now projected from durable canonical truth

Artifact:

sar_runtime/context.py

New model-visible projection types:

- ActionContextState
- ModelContextView
- ContextProjector

ContextProjector consumes:
- durable conversation events;
- committed durable memory;
- durable runtime records.

Projection rules:

conversation/message
-> model conversation

memory/committed
-> durable memory fact

CanonicalOutcomeCommit
-> CANONICAL_SUCCEEDED

UnresolvedOutcome
-> UNRESOLVED

Proposal / Intent / uncommitted memory / volatile model belief
-> never projected as successful canonical truth

---

## 4. Coupled runtime + context recovery experiment

Artifact:

context_recovery_experiment.py

Two paths are compared.

### No-crash canonical path

- durable conversation written;
- committed memory written;
- action executes;
- COC written;
- model context projected.

### Crash/restart path

Before restart, volatile memory deliberately contains a false belief:

"action succeeded"

source:

"model guess before provider reconciliation"

That volatile object is destroyed.

A fresh runtime reconstructs execution state from durable records and then a
fresh ContextProjector rebuilds the model-visible context.

### Result

Normal and recovered model views:

exactly equal

The injected volatile false belief:

absent after recovery

The recovered action status:

CANONICAL_SUCCEEDED

This establishes logical coupling between durable execution truth and model
context projection in the reference implementation.

---

## 5. Important limitation of the coupled-recovery result

The first coupled experiment uses reference event storage.

It establishes:

- deterministic replay;
- projection semantics;
- exclusion of uncommitted volatile beliefs.

It does not establish:

- physical disk durability;
- power-loss correctness;
- filesystem ordering guarantees.

For that reason a file-backed reference backend was added next.

---

## 6. SQLiteDurableStore

Artifact:

sar_runtime/sqlite_store.py

Reference durability configuration:

- SQLite WAL
- synchronous=FULL
- append-only stream offsets
- explicit JSON typed-record codec
- per-record SHA-256 checked during replay

The codec uses an explicit allow-list of runtime dataclasses.

It does not use pickle or arbitrary class imports.

---

## 7. SQLite record integrity check

Each durable row stores:

- payload_json
- payload_sha256

Replay recalculates the payload hash.

If the stored JSON is mutated without a matching checksum:

DurableRecordCorruptionError

is raised.

The runtime therefore fails loudly instead of replaying silently corrupted
application-level records.

### Migration

Reference databases created by the earlier schema are upgraded by adding and
backfilling the checksum column.

This is corruption detection at the application-record layer, not a claim that
SQLite or the underlying filesystem cannot suffer corruption.

---

## 8. Cross-process SQLite context recovery

Artifact:

sqlite_context_process_probe.py

Process A:

- writes conversation;
- writes committed memory;
- writes an uncommitted false memory proposal;
- executes the action;
- writes COC;
- exits.

Process B:

- starts in a new Python interpreter;
- receives only the SQLite file;
- reconstructs ContextProjector;
- recomputes the model-visible view.

Result:

writer context hash =
afe17b505d12af868c2187585625ec08acde287185deda86d1625116b13eca1d

reader context hash =
afe17b505d12af868c2187585625ec08acde287185deda86d1625116b13eca1d

The uncommitted "guessed-success" memory is absent.

This is stronger than same-process in-memory replay, while still remaining a
process-restart experiment.

---

## 9. SQLiteProviderAdapter

Artifact:

sar_runtime/sqlite_provider.py

The provider effect ledger is intentionally stored in a separate SQLite database
from the runtime journal.

It supports the reference capabilities:

- idempotency
- status query
- fencing

This separation matters because the central recovery problem is precisely:

provider reality may commit
while runtime receipt persistence does not.

Idempotency and receipts survive process reopen.

---

## 10. SQLiteLeaseCoordinator

Artifact:

sar_runtime/sqlite_lease.py

Lease/fence generations are also persisted separately.

Properties:

- every acquire monotonically increments fence;
- process restart does not reset fence;
- stale token release cannot clear a newer owner;
- ownership can be superseded by a newer generation.

This removes the last in-memory component from the hard-crash reference matrix.

---

## 11. Recovery now reacquires execution authority

A further issue appeared once lease state became persistent.

Old recovery behavior:

- sees old DispatchIntent;
- silently reuses its fence.

That is not sufficient after process failover.

### New behavior

If recovery still needs to touch the provider:

1. acquire a fresh lease;
2. receive a higher fence;
3. append a superseding DispatchIntent;
4. query / dispatch under the new execution generation.

For example:

old worker:
fence 1
DispatchIntent persisted
crash

recovery worker:
fence 2
superseding DispatchIntent
provider interaction

The old execution authority is not reused.

---

## 12. Seven-cut cross-process hard-crash matrix

Artifact:

sqlite_hard_crash_matrix.py

Three independent SQLite databases are used:

1. runtime/session journal;
2. provider effect ledger;
3. lease/fence coordinator.

Child processes are terminated abruptly after:

1. DAR
2. DispatchIntent
3. provider effect
4. ProviderReceipt
5. ReconciliationRecord
6. CanonicalOutcomeCommit
7. model context projection

A completely new Python process then reopens all three databases and recovers.

---

## 13. Hard-crash matrix result

For all seven cut points:

external effect count after recovery:

1

CanonicalOutcomeCommit:

present

recovered context:

identical to no-crash baseline

second recovery:

fixed point

uncommitted guessed-success memory:

absent

### Ownership handoff

For the two cut points where recovery still needs to resolve provider reality:

after_intent

and

after_provider_effect

the journal contains:

- old DispatchIntent with fence 1;
- superseding recovery DispatchIntent with fence 2.

Provider effect count remains 1.

---

## 14. Evidence classification

The repository now distinguishes the following evidence classes.

### In-memory fault-injection simulation

Example:
10,000-action journal stress run.

This is simulation.

It is not a production reliability rate.

### Finite-model checking

Example:
442,524-state reduced 5-replica / quorum-3 / 3-ballot checker.

This is a result inside a stated finite model.

It is not a full Paxos/Raft proof.

### In-memory/event-log context replay

Shows deterministic logical projection from durable canonical truth.

It is not disk durability evidence.

### SQLite process-restart recovery

Shows typed records, COC, context, provider effects, and lease generations
survive independent Python process restart.

It is stronger than in-memory replay.

### Abrupt child-process crash matrix

Tests seven execution cut points using separate SQLite runtime/provider/lease
reference databases.

It is still not a physical power-loss experiment.

---

## 15. What remains unverified

This round does not establish correctness under:

- machine power loss;
- torn SQLite pages;
- filesystem reordering;
- disk/controller cache loss;
- SSD firmware faults;
- disk corruption;
- simultaneous host loss across runtime/provider stores;
- remote network partitions between actual services.

The next durability frontier should target fault injection below the Python
process boundary.

---

## 16. Public reproduction material

Sanitized summaries are committed under:

repro/

including:

- ambiguous_recovery_summary.json
- context_recovery_summary.json
- sqlite_context_process_summary.json
- sqlite_hard_crash_matrix_summary.json
- fault_simulation_summary.json
- finite_model_check_summary.json

Raw API responses, secrets, and local ignored result directories remain
uncommitted.

---

## 17. Updated runtime principle

The recovery rule is now more precise:

> Persist intent before effect, but never interpret missing receipt as permission
> to retry unless the external system exposes a primitive that makes retry or
> reconciliation safe.

And model memory follows a parallel rule:

> Only durable canonical state may be projected back into model-visible memory as
> fact.

The runtime and model-context views therefore share the same durable source of
truth.
