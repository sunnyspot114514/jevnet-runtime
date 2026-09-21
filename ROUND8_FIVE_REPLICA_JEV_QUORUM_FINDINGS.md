# Round 8 — Five-Replica Recovery, Reconfiguration, Liveness, and Jev Authorization Quorum

Date: 2026-09-21

This round extends replicated COC safety from the 3-node model to a 5-replica quorum-3 system, adds crash/restart durability tests, membership reconfiguration, partition liveness analysis, and reintroduces real Jev calls as semantic authorizers.

## 1. Broad 5-replica / 3-ballot checker hit state explosion

Exploratory artifact: replicated_log_5node_modelcheck.py

Model dimensions:
- replicas: A,B,C,D,E
- quorum: 3
- ballots: 1,2,3
- leaders: A,C,E
- arbitrary partition/heal transitions
- arbitrary crash/restart transitions
- delayed accept messages
- optional volatile loss of acceptor history

At the 400,000-state cap, all three protocol variants reached the limit before the breadth-first search completed. Therefore absence of a counterexample in that run is INCONCLUSIVE and is not treated as evidence of safety.

The script was updated to emit explicit conclusions:
- COUNTEREXAMPLE_FOUND
- INCONCLUSIVE_STATE_LIMIT
- EXHAUSTIVE_NO_COUNTEREXAMPLE

rather than asserting unsupported proof claims.

## 2. Bounded exhaustive 5-replica checker

Confirmatory artifact: replicated_log_5node_phased_checker.py

To remove infinite crash/restart and partition/heal cycles, the confirmatory model keeps:
- 5 replicas
- quorum 3
- two leader ballots, sufficient for a conflicting-value safety violation
- partition choice at ballot boundaries
- optional crash/restart at ballot boundaries
- every prepared accept message deliverable at most once in arbitrary order
- stale-message rejection by promised ballot

This makes the state graph finite and fully explorable.

### Naive protocol

Results:
- states explored: 70,144
- transitions explored: 321,676
- state limit: not hit
- safety: VIOLATED

An automatically found trace commits X under ballot 1 and later commits Y under ballot 2.

### Safe + Durable accepted history

Results:
- states explored: 51,081
- transitions explored: 263,898
- state limit: not hit
- safety: HOLDS
- conflicting COC states: 0

Within this bounded fault model, Phase-1 inheritance plus durable promised/accepted history prevents a second conflicting value from becoming quorum-chosen.

### Safe protocol but volatile acceptor history

Results:
- states explored: 118,303
- transitions explored: 603,112
- state limit: not hit
- safety: VIOLATED

So the consensus logic can be correct while the implementation is still unsafe if crash loses accepted history.

## 3. One crashed intersection node is sufficient

Targeted trace:

Old quorum ABC chooses X.

New quorum CDE intersects the old quorum only at C.

### Durable implementation

C crashes and restarts, but preserves accepted X.

New leader C proposes candidate Y, Phase-1 quorum CDE observes C's accepted X, and ballot 2 is forced to select X.

Final chosen set remains {X}.

### Volatile implementation

C crashes and loses accepted history.

Quorum CDE now appears blank.

New leader selects Y, and Y reaches quorum.

Historical chosen set becomes {X,Y}.

This yields a strong implementation-level principle:

> Quorum intersection only carries safety if the intersection replica carries durable accepted history across crash.

Mathematical set intersection is not enough when persistent history disappears.

## 4. Membership reconfiguration

Artifact: membership_reconfiguration.py

Old configuration:
{A,B,C}, majority 2.

New configuration:
{C,D,E}, majority 2.

A direct configuration switch is unsafe because legal old and new majorities may be disjoint.

Examples:
- old quorum {A,B}
- new quorum {D,E}
- intersection = empty

The exhaustive enumeration found multiple disjoint old/new majority pairs.

### Joint consensus

Transition quorum must simultaneously contain:
- an old-configuration majority
- a new-configuration majority

There are 10 such joint quorums in this model.

Checks:
- every joint quorum intersects every old majority
- every joint quorum intersects every new majority
- 160 old -> joint -> new quorum combinations checked
- history-transfer violations: 0

Thus configuration change itself must be a consensus transition, not a local metadata flip.

## 5. Safety is not liveness

Artifact: partition_liveness.py

All 52 unique set partitions of five replicas were enumerated, together with all five possible current-leader placements: 260 leader/partition states.

Classification:
- NO_QUORUM_FAIL_STOP: 130
- CURRENT_LEADER_CAN_PROGRESS: 85
- ELECTION_NEEDED_IN_MAJORITY_COMPONENT: 45

In a 3|2 partition:
- leader in the 3-node component can make progress
- leader in the 2-node minority must stop
- the 3-node majority may regain liveness through leader election

In 2|2|1 or smaller-component partitions, no component reaches quorum and every leader must fail-stop.

This clarifies an important runtime contract:

> No quorum means no global canonical authority.

Availability must not be recovered by silently weakening the quorum requirement.

## 6. Real Jev authorizers inside the quorum protocol

Runner was implemented before benchmark freeze.

Runner pre-freeze SHA-256:
a4098ea597930800d67b49c8485a561cb0e3b668284e612066ebfbea9e7cfa72

Frozen benchmark SHA-256:
1c4c12a591b55689a68cf950369fddc693611cc8877a2ff4ff4356d74b54b4ab

Protocol:
- A1, A2, A3 are independent Jev calls
- identical policy
- identical proposal
- decisions: APPROVE / REJECT / ESCALATE
- DAR threshold: 2-of-3 APPROVE

Benchmark cases cover:
- reversible local edits
- local preferences
- quoted external-action text stored locally
- unsent local email draft
- actual external email
- publishing
- persistent cloud deletion
- credential change
- financial purchase
- local edit bundled with form submission/upload

## 7. Jev authorizer result

12 frozen cases x 3 authorizers = 36 Jev votes.

Observed:
- A1 decision accuracy: 12/12
- A2 decision accuracy: 12/12
- A3 decision accuracy: 12/12
- quorum authorization accuracy: 12/12
- natural disagreement cases: 0/12
- unanimous wrong cases: 0

Three authorizers were called in parallel.

Mean case wall time: approximately 0.67 s.

Mean total input tokens across all three authorizers: approximately 2,041 per case.

The local quote and unsent-draft cases were APPROVE, while actual send/publish/upload actions were REJECT, indicating the authorizer was not merely keyword matching on the easy frozen set.

## 8. Single-Byzantine injection

For every benchmark case, each authorizer position was separately forced to cast the wrong authorization vote while the other two retained their actual Jev votes.

Trials:
12 cases x 3 faulty positions = 36.

Result:
- correct final DAR/no-DAR under one forced Byzantine vote: 36/36

This verifies the deterministic 2-of-3 fault-containment property given two correct votes.

## 9. What the Jev quorum result does not establish

The three Jev authorizers naturally agreed on every case.

Therefore this benchmark does not show that majority voting improves natural semantic accuracy over one Jev call.

Three calls to the same underlying model can have highly correlated errors.

If all three share the same systematic misclassification, quorum reproduces that error.

The v1 result supports:
- single-Byzantine protocol tolerance
- parallel authorizer latency feasibility
- semantic policy execution on these frozen cases

It does not establish:
- independent error reduction
- diversity between authorizers
- superiority over one Jev call on semantic accuracy

A harder future benchmark should explicitly target correlated semantic failure.

## 10. Distributed authority stack after Round 8

The runtime now has separate mechanisms for:

Semantic proposal:
Jev / Agent Proposal

Authorization:
multi-authorizer semantic votes -> proposal-hash quorum -> Durable Authorization Record

Execution:
lease owner -> fencing token -> idempotency -> provider-side validation

Observation:
receipt identity -> reconciliation -> local COC candidate

Global durability:
replicated log -> ballot/term -> Phase-1 inheritance -> quorum-chosen COC

Configuration:
joint old/new quorum during membership change

Crash recovery:
durable promised/accepted history and journal replay

## 11. Authority and durability are now coupled

Rounds 5-8 collectively show two independent requirements:

1. Authority must be earned through the protocol.
2. The evidence that granted authority must survive the failures the protocol claims to tolerate.

Examples:
- DAR without durable authorization evidence is unsafe after recovery.
- quorum intersection without durable accepted history is unsafe after crash.
- a lease without provider fencing is unsafe after owner failover.
- a COC without replicated-log agreement is only locally canonical.

## 12. Next experiments

Highest-value next steps:

1. Hard Jev-authorizer benchmark designed to elicit natural disagreement and correlated errors.
2. Five-replica model with a third ballot under partial-order/symmetry reduction instead of brute-force BFS.
3. Explicit leader-election model and liveness/fairness conditions.
4. Joint-consensus configuration entry inside the replicated log model, not only quorum-set analysis.
5. Crash/restart during membership transition.
6. Actual TLC execution of ReplicatedCOC.tla when Java/TLC is available.
7. Jev proposer + three Jev authorizers + deterministic dispatcher/reconciler in one end-to-end runtime simulation.