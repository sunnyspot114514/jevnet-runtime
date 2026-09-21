# Round 6 — Cross-Agent Authority, Quorum, Leases, Fencing, and Revocation

Date: 2026-09-21

This round extends the runtime from single-process durability to distributed authority.

Tested:
- role-separated agents;
- threshold authorization;
- malicious/equivocating authorizers;
- duplicate votes;
- two recovery replicas;
- action idempotency;
- lease fencing;
- stale-owner execution;
- in-flight authorization revocation;
- provider-side authorization fencing.

---

## 1. Cross-agent role separation

Experiment:

`cross_agent_authorization.py`

Roles:

```
Proposer   -> PROPOSAL
Authorizer -> DAR
Dispatcher -> DISPATCH_INTENT
Reconciler -> OBSERVATION / COC
```

A role capability is necessary but not sufficient.

Records with side-effect authority must also bind to their durable predecessor.

Examples:

### Proposer attempts self-authorization
Rejected:

`ROLE_NOT_AUTHORIZED_FOR_RECORD_KIND`

### Authorizer attempts dispatch
Rejected.

### Dispatcher attempts COC
Rejected.

### Dispatcher creates intent without DAR
Originally this exposed a design bug: role permission alone allowed the record.

After adding prerequisite/binding validation:

Rejected:

`DISPATCH_WITHOUT_DAR`

This experiment directly demonstrated:

> **RBAC/capability checks alone are insufficient.**
>
> Durable execution records also need causal/binding validation.

---

## 2. Forged observation must not block the true receipt

A reconciler may receive an observation with:
- wrong auth_id;
- plausible action ID;
- plausible status.

The forged observation is retained as audit evidence.

However:
- it does not satisfy DAR reconciliation;
- it cannot become the source of COC;
- it does not occupy a single "observation slot";
- a later valid provider receipt can still be appended and selected.

Final COC binds to:

```
AUTH-X
IDEM-X
REC-X
```

not the forged receipt.

Thus audit retention and canonical authority are separate.

---

## 3. Delivery order for legitimate role records

Legitimate durable records:
- Proposal
- DAR
- Dispatch Intent

were delivered in every:

[
3! = 6
]

possible order.

After reconciliation, all six converge to:
- one external effect;
- one valid COC;
- identical auth ID;
- identical idempotency key.

So the durable chain does not require network arrival order to equal semantic order.

---

## 4. Threshold authorization

Experiment:

`quorum_authorization.py`

Authorizers:

```
A1, A2, A3
threshold = 2
```

DAR requires two distinct authorizers approving the same:
- action ID;
- authorization epoch;
- proposal hash.

### Duplicate vote

A1 submits the same approval three times.

Result:

```
1 distinct vote
no quorum
```

### Single malicious authorizer

A3 approves a mutated/unsafe proposal hash.

Result:

```
1 vote
no DAR
```

### One good + one malicious vote on different hashes

Result:

```
no hash reaches threshold
no DAR
```

### Two honest approvals + one malicious approval

Result:

DAR is issued for the honest proposal hash only.

---

## 5. Equivocation

A3 approves both:
- the legitimate proposal hash;
- a conflicting proposal hash.

The reducer classifies A3 as:

`EQUIVOCATION`

and excludes that authorizer from both quorums.

If A1 and A2 both approve the legitimate hash:
- legitimate DAR still forms.

If only A1 + equivocating A3 appear:
- no DAR forms.

Thus one identity cannot manufacture quorum by voting inconsistently.

All quorum scenarios were permutation-order invariant.

---

## 6. Dual recovery replicas: action idempotency

Experiment:

`dual_replica_fencing.py`

R1 and R2 independently recover the same DAR.

Both call provider with the same stable idempotency key.

Observed:

```
provider calls = 2
external effects = 1
receipt R1 = R-1
receipt R2 = R-1
```

Without provider idempotency:

```
external effects = 2
```

Therefore:

> **Idempotency deduplicates recovery of the same authorized action.**

---

## 7. Lease handoff: idempotency is not fencing

Different problem:

R1 owns lease generation/fence 1 and holds authorized command A.

R1 pauses.

Lease expires.

R2 acquires fence 2 and sends newer command B.

Then R1 resumes and sends old A.

A and B have different action/idempotency identities.

### Without provider fencing

Provider accepts:
1. B
2. stale A

Final value:

`VALUE-A`

The old owner overwrites the new owner.

Idempotency cannot prevent this because A and B are different actions.

### With provider fencing

Provider has seen fence 2.

Late command with fence 1 returns:

`REJECTED_STALE_FENCE`

Final value:

`VALUE-B`

---

## 8. Post-handoff interleavings

After lease generation 2 becomes current, commands:

- B from R2 / fence 2
- A1 from stale R1 / fence 1
- duplicate A2 from stale R1 / fence 1

were delivered in all:

[
3! = 6
]

orders.

### Without fencing

Final state depends on delivery order.

Both A and B may be externally applied.

### With fencing

All 6/6 orders produce:

```
accepted actions = [B]
stale A commands = rejected
final value = VALUE-B
```

Therefore:

> **Idempotency and fencing solve different classes of replay.**

- idempotency: same-action replay;
- fencing: stale-owner replay.

Reliable distributed recovery needs both when both races are possible.

---

## 9. In-flight authorization revocation

Experiment:

`inflight_revocation.py`

Authorization has a monotonically increasing generation.

The DAR carries the generation at which it was issued.

Provider maintains a minimum acceptable authorization generation.

### Revoke before local validation

Runtime sees authorization inactive.

No effect.

### TOCTOU race

Sequence:

```
dispatcher checks auth -> ACTIVE
revocation happens
command reaches provider
```

#### Local check only

Provider does not know revocation generation.

Stale command is applied.

Final value becomes:

`NEW`

This is an explicit authorization TOCTOU failure.

#### Provider-side authorization fence

Revocation advances provider minimum generation from 1 to 2.

Stale DAR carries generation 1.

Provider returns:

`REJECTED_REVOKED_AUTH`

No effect occurs.

Thus:

> **Authorization validation must survive the network boundary.**

A local pre-dispatch check cannot close a revoke/dispatch race by itself.

---

## 10. Revocation after the effect already happened

Different case:

1. authorization is valid;
2. provider applies effect;
3. revocation arrives later.

The effect is historical reality.

Runtime cannot retroactively reinterpret it as "never happened."

### Compensatable effect

Runtime:
- records effect;
- records revocation;
- dispatches compensation;
- reconciles compensation;
- commits:

`REVOKED_COMPENSATED`

Final external value is restored.

### Non-compensatable effect

Runtime cannot erase the effect.

Canonical outcome:

`REVOKED_AFTER_EFFECT_ESCALATE`

The external value remains changed.

This is a necessary distinction between:

- **preventing an in-flight effect**
- **repairing a completed effect**

---

## 11. Distributed authority now has three independent orderings

The experiments reveal three different monotonic order concepts.

### Authorization order

`auth_seq / auth_generation`

Determines which authorization is current.

### Execution-owner order

`lease fencing token`

Determines which runtime replica owns execution rights.

### Observation order

`observation_seq`

Determines how external receipts are reconciled.

These numbers must not be conflated.

A runtime may have:

```
auth_generation = 17
lease_fence      = 42
observation_seq  = 3
```

Each answers a different question.

---

## 12. Updated execution token

A side-effect dispatch can now be modeled as carrying at least:

```text
action_id
proposal_hash
auth_id
auth_generation
approver_set / quorum proof
idempotency_key
lease_fencing_token
authorized_payload_hash
```

Provider/runtime validation then checks:

1. correct action binding;
2. valid/current authorization generation;
3. quorum/DAR validity;
4. non-stale execution fence;
5. stable idempotency identity;
6. payload matches authorization.

This is substantially stronger than "the Agent decided to call a tool."

---

## 13. Fault containment principle

Cross-agent experiments reinforce the core thesis:

> **No single semantic/model component should have enough authority to both
> propose and canonically enact a side effect.**

Useful separation:

```
Proposer
   ↓
Authorizer quorum
   ↓
DAR
   ↓
Lease-owning dispatcher
   ↓
Provider-side fence/idempotency
   ↓
Observation
   ↓
Independent reconciliation
   ↓
COC
```

Compromise or hallucination in one role becomes a rejected or incomplete record,
not automatically a world-changing action.

---

## 14. Relationship to distributed systems primitives

The runtime is converging toward familiar distributed-system requirements:

- idempotency keys;
- fencing tokens;
- epochs/generations;
- threshold/quorum authorization;
- durable intent;
- append-only audit records;
- reconciliation;
- canonical commit;
- compensation.

The unusual part is where Jev/LLMs fit:

> They are semantic Proposal/interpretation components inside the protocol,
> not the protocol itself.

This sharply limits how much system correctness depends on model internals.

---

## 15. Current experimentally motivated architecture

```
           Jev / Agent Proposer
                    |
               Proposal hash
                    |
        +-----------+-----------+
        |           |           |
   Authorizer A Authorizer B Authorizer C
        +-----------+-----------+
                    |
                quorum DAR
                    |
             lease coordinator
                    |
      dispatcher + fencing token
                    |
        provider validation
      (auth generation + fence
       + idempotency + payload)
                    |
              external effect
                    |
               observation
                    |
              reconciler
                    |
        Canonical Outcome Commit
                    |
            durable state
```

---

## 16. Next research boundary

The next frontier is replica coordination itself.

Current experiments assume:
- a trustworthy monotonically increasing lease/fence source;
- durable records are readable after crash.

Next questions:

1. **Replicated durable log**
   - two journal replicas temporarily disagree;
   - which COC is canonical?

2. **Network partition**
   - old dispatcher cannot reach lease coordinator but can reach provider;
   - provider fencing must still protect the resource.

3. **Quorum membership changes**
   - authorizer set changes while votes are in flight.

4. **Cross-agent Jev roles**
   - use actual independent Jev calls as proposer/authorizers/reconciler;
   - measure whether protocol invariants contain disagreement/model error.

5. **Byzantine receipt / provider adapters**
   - provider itself returns contradictory observations.

6. **Formal model**
   - encode the runtime state machine in TLA+/PlusCal, Alloy, or a small model checker
     and exhaustively verify safety invariants.
