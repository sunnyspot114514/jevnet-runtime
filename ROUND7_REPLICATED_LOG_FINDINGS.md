# Round 7 — Replicated Durable Log, Network Partition, and Formal Safety

Date: 2026-09-21

This round removes the last implicit single-node assumption from the runtime:

> What if the durable journal itself is replicated and temporarily inconsistent?

The central safety question is whether two different Canonical Outcome Commits can become durable for the same action/log slot during leader change and network partition.

## 1. Finite replicated-log model

Executable checker: replicated_log_modelcheck.py

System:
- replicas: A, B, C
- quorum: 2-of-3
- one replicated log slot
- candidate COCs: X and Y
- ballot 1 leader: A
- ballot 2 leader: C
- arbitrary network transitions among FULL, AB|C, AC|B, BC|A

Replica state contains promised_term, accepted_ballot, and accepted_value.

Safety property: at most one distinct value may ever become quorum-chosen for this log slot.

## 2. Naive quorum is not enough

Naive protocol allows a higher-term leader to obtain a Phase-1 quorum but ignore previously accepted values reported by that quorum.

Exhaustive result:
- reachable states explored: 1,442
- transitions explored: 5,504
- safety: VIOLATED
- reachable states with both X and Y chosen: 30

Thus 2-of-3 quorum by itself does not guarantee a single canonical outcome.

## 3. Automatically discovered shortest counterexample

The checker found a six-step counterexample even without requiring a network partition:

1. A prepares ballot 1 with candidate X on quorum AB.
2. A accepts X.
3. C prepares higher ballot 2 with candidate Y on quorum AC.
4. A stale ballot-1 message reaches B; X reaches quorum and becomes chosen.
5. A accepts Y at ballot 2.
6. B accepts Y at ballot 2; Y also reaches quorum.

Final historical chosen set: {X, Y}.

The problem is deeper than simple split brain: a higher-term leader cannot safely treat a quorum as a blank slate.

## 4. Safe Phase-1 inheritance

Safe protocol:
1. collect accepted ballot/value from Phase-1 quorum;
2. find the highest accepted ballot;
3. if an accepted value exists, inherit it;
4. only if the quorum reports no accepted value may the leader use its own candidate;
5. acceptors reject any Phase-2 message below their promised term.

Exhaustive result:
- reachable states explored: 1,028
- transitions explored: 4,860
- stale-leader rejection opportunities observed: 1,180
- safety: HOLDS
- states with both X and Y chosen: 0

Chosen states were only NONE, X, or Y; never X,Y.

## 5. Forced network-partition split-brain scenario

Experiment: replicated_log_partition_scenario.py

Forced schedule:
FULL -> AB|C -> A ballot 1 -> X chosen by AB -> BC|A -> C ballot 2 candidate Y.

Naive trace:
1. network -> AB_C
2. A PREPARE b1 candidate=X quorum=AB selected=X
3. A -> A ACCEPT X
4. A -> B ACCEPT X; X chosen
5. network -> BC_A
6. C PREPARE b2 candidate=Y quorum=BC selected=Y
7. C -> B ACCEPT Y
8. C -> C ACCEPT Y; X and Y chosen

Final chosen set: {X, Y}.

## 6. Safe protocol under the same partition schedule

B belongs to both the old quorum AB and the new quorum BC. B reports accepted ballot 1 = X.

Therefore the new leader's candidate Y is overridden by inherited X:

candidate = Y
selected = X

Ballot 2 then commits X again. Final chosen set remains {X}.

## 7. Why quorum intersection matters

For N=3, quorum=2, any two quorums intersect. But intersection only provides safety if the shared replica carries accepted history forward.

Without history inheritance, quorum intersection exists but its information is discarded, so safety still fails.

The relevant invariant is: new quorum decisions must preserve the highest accepted history visible through quorum intersection.

## 8. Stale leader fencing inside the replicated log

Once a replica promises ballot 2, ballot-1 accept messages are stale and rejected.

The safe model counted 1,180 reachable stale-leader rejection opportunities.

This is the replicated-log analogue of the provider fencing token from Round 6:
- log promise/ballot fencing stops stale consensus leaders from modifying replicated durable state;
- provider fencing stops stale execution owners from modifying external resources.

Both require monotonic generations, but protect different layers.

## 9. Two independent durable safety layers

Durable journal layer asks which COC is durably chosen and which leader/term may append it. It requires quorum, term/ballot, quorum intersection, Phase-1 history inheritance, and stale-leader rejection.

External effect layer asks which runtime replica may execute and whether an action already executed. It requires lease fencing, provider-side fencing, idempotency, and receipt reconciliation.

A safe replicated journal does not eliminate provider fencing. Provider fencing does not make the journal consistent.

## 10. Canonical Outcome Commit in a replicated system

A local runtime writing COC(X) does not make X globally canonical.

The chain is now:

Observation -> Reconciliation -> COC Candidate -> Replicated-log consensus -> Quorum-chosen COC -> Durable Canonical State.

## 11. Formal-model artifact

A matching TLA+ specification is included:
- ReplicatedCOC.tla
- ReplicatedCOC_Naive.cfg
- ReplicatedCOC_Safe.cfg

The current Devspace environment does not contain Java/TLC, so the TLA+ model was not executed here.

The executable Python state-space checker explores the same finite abstraction and is covered by regression tests.

Expected TLC behavior:
- Naive config: Safety invariant violation.
- Safe config: no Safety violation for this finite model.

See REPLICATED_COC_FORMAL.md.

## 12. Important limitation

This is not a full Raft/Paxos implementation or proof. The finite model omits arbitrary log length, snapshots, membership reconfiguration, explicit message queues, disk corruption, Byzantine replicas, and liveness/fairness.

It tests one narrow but central property: a single replicated canonical-outcome slot must never choose two distinct values.

## 13. Architecture after Round 7

The authority path is now:

Jev/Agent Proposal
-> validation / authorization quorum
-> Durable Authorization Record
-> lease + execution fencing
-> dispatch
-> external provider
-> observation
-> reconciliation
-> COC candidate
-> replicated durable log with quorum + term + inheritance
-> quorum-chosen COC
-> durable canonical state

There are three distinct protection mechanisms:
1. Authorization quorum: who permits the action?
2. Execution fencing + idempotency: who may execute and how many times?
3. Replicated-log consensus: which observed outcome becomes globally canonical?

## 14. Updated core principle

Earlier rounds established: model output has Proposal Authority, not State Authority.

Round 7 extends this:

> A single runtime replica also does not have Global Canonical Authority.

Global state authority requires a durable agreement protocol whose safety survives partition, leader change, stale messages, and recovery.

Authority ladder:

Model proposal < validated proposal < authorized action < observed effect < local COC candidate < quorum-chosen COC < global canonical state.

## 15. Next formal/distributed experiments

1. Combine replicated log with crash/restart recovery.
2. Explicitly model leader election and term handoff.
3. Add membership reconfiguration and verify quorum intersection.
4. Add liveness/fairness checks.
5. Let multiple real Jev authorizers disagree while the deterministic protocol contains disagreement.
6. Execute the included TLA+ model once Java/TLC is available.
7. Scale the explicit state checker to 5 replicas, quorum 3, more ballots, crashes, duplicated and delayed messages.