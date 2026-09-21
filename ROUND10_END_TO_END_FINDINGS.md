# Round 10 — End-to-End Jev-to-Canonical-State Runtime

Date: 2026-09-21

This round composes the previously isolated components into one end-to-end execution path.

## 1. Frozen end-to-end benchmark

Runner pre-freeze SHA-256:
5ccc7142f4269b2c25f4d58a1bc3f4a25ea5b2bc8c7218b79b91d657358f4570

Benchmark SHA-256:
8855d8bf598cbac2b2fa35f5c7ed14f43f4f3c3358b731068e1fcf427da8537c

10 cases:
- 3 authorized local/mock actions
- 7 forbidden or ambiguous actions

Mechanical tool payloads are frozen structured receipts and are not reconstructed from prose by Jev.

## 2. Full path

Each request traverses:

Jev semantic authorizers
-> 2-of-3 approval quorum
-> typed Jev boundary audit
-> deterministic authorization gate
-> Durable Authorization Record
-> lease / fencing token
-> idempotent provider dispatch
-> duplicate recovery dispatch
-> lease handoff
-> stale-owner retry
-> forged + valid observations
-> reconciliation
-> local COC candidate
-> replicated COC handoff with conflicting candidate
-> globally stable chosen COC

Denied requests stop before DAR/effect.

## 3. Semantic front-end

Cases included:
- local rename
- disposable mock KV update
- inert local security text
- ownership/permission change
- credential rotation
- real webhook send
- cloud deletion
- payment
- system-service restart
- ambiguous shared-service target

Result:
- front-end authorization accuracy: 10/10
- authorized cases: 3
- denied/ambiguous cases: 7

Typed boundary classes matched the intended categories on all observed cases.

Mean Jev front-end wall time:
approximately 0.70 s/case

Mean total Jev input tokens:
approximately 2,358/case

## 4. Authorized-path invariants

For every authorized case:

### Exactly one external effect

Two runtime replicas attempted recovery/dispatch using the same DAR and idempotency key.

Result:
- provider calls may repeat
- durable external effect count = exactly 1
- duplicate recovery returns the same receipt

Rate:
3/3

### Stale owner excluded after lease handoff

R1 dispatches under fence 1.

Lease moves to R2 / fence 2.

Late R1 retry under fence 1 is rejected.

Rate:
3/3

### Forged observation rejected

Each authorized path receives:
- one valid provider receipt
- one forged receipt with wrong auth_id

Reconciliation rejects the forged receipt and binds COC to the valid provider receipt.

Rate:
3/3

### Replicated COC conflict contained

After the valid COC hash is chosen by the first quorum, a later leader proposes a conflicting COC hash.

Phase-1 quorum includes an acceptor carrying the already chosen COC.

The higher ballot inherits the valid COC instead of the conflicting candidate.

Rate:
3/3

Historical chosen set remains singleton.

## 5. Denied-path invariants

For every rejected or ambiguous case:
- no DAR
- no provider dispatch
- external effect count = 0
- no COC candidate
- no replicated COC

Rate:
7/7

This demonstrates fail-closed composition: semantic denial is not merely a label; it removes effect authority from all downstream layers.

## 6. End-to-end result

Summary:
- front-end accuracy: 10/10
- authorized exactly-one-effect rate: 3/3
- authorized COC rate: 3/3
- authorized replicated-COC safety rate: 3/3
- denied zero-effect rate: 7/7
- denied zero-COC rate: 7/7
- duplicate recovery same-receipt rate: 3/3
- stale retry rejection rate: 3/3
- forged observation rejection rate: 3/3

## 7. Architectural significance

Earlier rounds established components independently.

Round 10 shows they compose coherently:

Semantic uncertainty
does not directly mutate world state.

Authorization evidence
is materialized as a durable record.

Execution authority
is separated from semantic authority.

External reality
is established through provider observation rather than model belief.

Canonical outcome
is separated from local observation and then upgraded through replicated-log consensus.

The final authority chain is:

Natural-language request
-> semantic Proposal interpretation
-> approval quorum
-> typed hard-boundary gate
-> DAR
-> fenced/idempotent dispatch
-> provider effect
-> Observation
-> Reconciliation
-> COC candidate
-> replicated quorum certificate
-> Global Canonical State

## 8. Relationship to the core thesis

The project began by asking whether Jev could occupy neural-network-style topologies.

The strongest result is now architectural rather than topological:

> Jev/model outputs are useful semantic proposals, but authority is progressively earned through deterministic and durable protocol layers.

No model call directly receives:
- world-state authority
- effect authority
- global canonical authority

Those authorities are acquired separately.

## 9. What this end-to-end test does not prove

This remains a simulated runtime.

It does not establish:
- production distributed-system correctness
- real provider/API failure behavior
- Byzantine provider resistance
- general semantic authorization accuracy
- full Paxos/Raft equivalence
- liveness under arbitrary asynchronous scheduling
- independent-model ensemble gains

The replicated COC handoff is a compact single-slot safety scenario, not a complete consensus implementation.

## 10. Most valuable next engineering step

The research code is now mature enough to justify a small executable runtime prototype with explicit interfaces:

ProposalRecord
ValidationResult
DurableAuthorizationRecord
DispatchIntent
ProviderReceipt
ReconciliationRecord
CanonicalOutcomeCommit

plus adapter capabilities:

supports_idempotency
supports_status_query
supports_compensation
supports_fencing
supports_transactional_commit

That would turn the current collection of experiments into one reusable runtime library rather than separate research scripts.