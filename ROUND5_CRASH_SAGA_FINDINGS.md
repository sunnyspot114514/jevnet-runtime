# Round 5 — Crash Recovery, Partial Side Effects, and Exactly-Once Boundaries

Date: 2026-09-21

This round tests whether the State-Aware Runtime chain remains valid under:
- process crash/restart;
- lost volatile memory;
- ambiguous external timeouts;
- partial side effects;
- compensation;
- duplicate durable records;
- large interleaved workloads.

---

## 1. Crash/restart recovery

Experiment:

`crash_recovery_runtime.py`

Workflow:

```
Proposal
→ Durable Authorization Record
→ Dispatch Intent
→ External Effect
→ Observation
→ Canonical Outcome Commit
```

Crash was injected after every cut point:

0. before Proposal
1. after Proposal
2. after DAR
3. after Dispatch Intent
4. after external provider effect
5. after Observation
6. after COC

After each crash:
- all volatile runtime state is assumed lost;
- recovery uses only durable records and provider query-by-idempotency-key;
- recovery is repeated five times to test fixed-point idempotence.

### Result

Cuts before DAR:
- external effects = 0
- canonical outcome = none

Cuts at or after DAR:
- exactly one external effect
- identical provider receipt
- identical final COC

Critical ambiguous cut:

```
DAR
→ Dispatch Intent
→ PROVIDER EFFECT
→ CRASH
(no Observation yet)
```

Recovery queries provider by idempotency key, discovers the existing effect,
writes Observation, reconciles, and commits COC without redispatch.

Repeated recovery never duplicates the effect.

Duplicate durable DAR / DispatchIntent / Observation records were also injected.
They did not change the final canonical outcome or external effect count.

---

## 2. Durable journal stress

Experiment:

`journal_recovery_stress.py`

Configuration:
- 200 independent workloads
- 50 actions/workload
- 10,000 total actions
- 78%-ish authorized, remainder unauthorized
- interleaved action micro-steps
- random crash injection
- random duplicate durable record injection
- final total loss of volatile state
- repeated journal replay/recovery

Observed fault load:
- 6,093 crashes
- 473 duplicate durable records
- 7,896 authorized actions
- 2,104 unauthorized actions

### Invariants after recovery

- unauthorized external effects: **0**
- missing authorized effects: **0**
- unauthorized COCs: **0**
- missing authorized COCs: **0**
- canonical digest fixed-point failures: **0**

Thus all 7,896 authorized actions produced exactly one durable provider effect and
one canonical outcome, while all 2,104 unauthorized actions remained effect-free.

---

## 3. Partial side-effect workflow

Experiment:

`partial_side_effect_saga.py`

Example order workflow:

```
DAR
→ reserve inventory
→ charge payment
→ COC_SUCCESS
```

If payment fails after inventory reservation:

```
CHARGE_FAILED
→ RELEASE_INTENT
→ inventory release
→ RELEASE_OBS
→ COC_FAILED_COMPENSATED
```

### Naive ambiguous timeout

Payment externally succeeds, but response is lost.

Naive runtime interprets timeout as failure and retries without idempotency:

```
charge #1 succeeds, response lost
charge #2 succeeds
```

Observed successful charge effects:

**2**

### Robust ambiguous timeout

Runtime:
1. persists CHARGE_INTENT;
2. dispatches with stable idempotency key;
3. timeout is treated as UNKNOWN, not FAILED;
4. queries provider by idempotency key;
5. reconciles existing success;
6. commits canonical success.

Observed charge effects:

**1**

---

## 4. Terminal failure and compensation

Naive payment hard-failure:
- inventory reserve succeeded;
- payment failed;
- no compensation.

Final leaked active reservations:

**1**

Robust payment hard-failure:
- payment failure becomes durable observation;
- RELEASE_INTENT is persisted;
- release is idempotent;
- release observation is reconciled;
- COC_FAILED is written only after compensation succeeds.

Final active reservations:

**0**

Release effects:

**1**

---

## 5. Compensation itself can have an ambiguous timeout

Experiment also injects:

```
inventory release succeeds
→ release response is lost
→ crash/recovery
```

Runtime does not blindly issue a new semantic compensation.

It queries by the compensation idempotency key, discovers the already-completed
release, records the release observation, and commits compensated failure.

Final:
- release effects = 1
- active reservations = 0
- COC_FAILED = present

Thus compensation requires the same durable-intent/reconciliation discipline as
the original side effect.

---

## 6. Exhaustive saga crash matrix

Experiment:

`saga_crash_matrix.py`

### Success path

Seven crash cuts were tested, including:
- before reserve;
- after reserve intent;
- after reserve effect but before observation;
- after reserve observation;
- after charge intent;
- **after charge effect but before observation**;
- after charge observation.

All 7/7 cuts converged to:
- COC_SUCCESS
- 1 inventory reservation effect
- 1 payment charge effect
- 0 release effects
- no duplicate payment call

### Failure / compensation path

Five crash cuts were tested, including:
- before terminal failure becomes durable;
- after CHARGE_FAILED;
- after RELEASE_INTENT;
- **after release effect but before release observation**;
- after release observation.

All 5/5 cuts converged to:
- COC_FAILED
- 1 reservation effect
- 0 successful charge effects
- 1 release effect
- 0 leaked active reservations

---

## 7. Exactly-once has an external-system requirement

Experiment:

`exactly_once_impossibility.py`

Suppose a provider supports neither:
- idempotency keys;
- nor queryable durable operation receipts.

A dispatch times out.

The runtime observes the same local state in two possible worlds:

### World A
The external effect happened; only the response was lost.

### World B
The external effect did not happen; the response was lost.

They are observationally identical:

```
TIMEOUT_NO_RECEIPT
```

A deterministic recovery policy has only two choices.

### RETRY
- World A -> duplicate effect
- World B -> exactly one effect

### DO NOT RETRY
- World A -> exactly one effect
- World B -> missing effect

No deterministic runtime decision succeeds in both worlds.

Therefore:

> **Exactly-once cannot be guaranteed by the agent runtime alone after an
> ambiguous outcome if the provider exposes neither idempotency nor a
> queryable/durable receipt.**

This is a capability boundary, not a prompt-engineering problem.

---

## 8. External primitives sufficient to escape ambiguity

The experiments identify several useful provider capabilities:

### Strongest
- provider-recognized idempotency key
- queryable operation / receipt ID

### Transactional alternatives
- transactional outbox / externally visible commit record
- two-phase or reservation-style protocol

### Semantic repair
- durable, idempotent compensation identity

Compensation gives eventual semantic repair, but is not identical to literal
exactly-once execution.

---

## 9. Runtime capability gate

A practical runtime should classify side-effect interfaces before allowing
autonomous retry semantics.

Example capability contract:

```text
supports_idempotency: true/false
supports_status_query: true/false
supports_compensation: true/false
supports_transactional_commit: true/false
```

Then:

### Idempotency or query available
Ambiguous timeout may be reconciled safely.

### Only compensation available
Effect may be retried/managed under explicit saga semantics, but "exactly once"
must not be claimed.

### None available
Ambiguous effect must enter a human/escalation/unknown state rather than blind
retry or silent success.

---

## 10. Recovery state should be reconstructible from durable facts

The stress experiment reinforces a strict design principle:

> Volatile process memory is a cache, not an authority.

After crash/restart, authoritative state is reconstructed from:

- Durable Authorization Record
- Dispatch Intent
- provider/queryable effect state
- Observation
- Reconciliation records
- Canonical Outcome Commit

The runtime does not need to remember what it "thought it was doing" before the
crash.

It only needs the durable execution facts.

---

## 11. Full runtime chain now experimentally motivated

Across Rounds 1–5, each component arose from a concrete failure mode:

```
Proposal
   ↓
Validation
   ↓
Durable Authorization Record
   ↓
Dispatch Intent
   ↓
External Effect
   ↓
Observation
   ↓
Reconciliation
   ↓
Canonical Outcome Commit
   ↓
Durable State
```

### Why each layer exists

**Proposal**
Model output is not state authority.

**Validation**
Prevents probabilistic/provenance leakage and invalid commits.

**Durable Authorization Record**
Removes delivery-order races and gives recovery authority.

**Dispatch Intent**
Makes "was this effect supposed to happen?" durable before the effect.

**Observation**
Separates claimed/attempted effects from provider-observed reality.

**Reconciliation**
Handles ambiguity, duplicates, conflicts and delayed receipts.

**Canonical Outcome Commit**
Defines the one durable result future reasoning is allowed to consume.

**Durable State**
Allows process memory to disappear without changing system truth.

---

## 12. Updated architecture claim

The strongest current claim is now:

> **Reliable long-horizon agent execution requires explicit separation between
> semantic proposals, authorization, external effects, observations and canonical
> state.**

Jev/LLMs are useful for:
- semantic interpretation;
- routing;
- proposal generation;
- uncertainty estimation.

They should not directly decide:
- whether an ambiguous external action already happened;
- transaction ordering;
- idempotent replay;
- exact arithmetic/state-machine updates;
- whether a side effect becomes canonical truth.

Those are runtime responsibilities.

---

## 13. Relationship to State-Aware Runtime / Agent BIOS

The experimental architecture now maps naturally to the existing terminology:

```
Proposal
→ Validation
→ Durable Authorization Record
→ Dispatch
→ Observation
→ Reconciliation
→ Canonical Outcome Commit
```

The new crash/saga results add two operational rules:

1. **Persist intent before external effect.**
2. **Never map timeout directly to failure.**

A timeout represents:

```
UNKNOWN external outcome
```

until provider state is reconciled.

This single distinction prevents both:
- duplicate effects;
- leaked partial side effects.

---

## 14. Next frontier

The next most informative problems are no longer basic crash safety.

They are:

1. **Cross-agent authorization**
   - proposer, authorizer, dispatcher and reconciler are different agents.

2. **Non-monotonic semantic correction**
   - later evidence legitimately invalidates an earlier canonical interpretation.

3. **Human override / revocation during in-flight dispatch**
   - authorization is revoked after intent but before or during external effect.

4. **Distributed durable logs**
   - two runtime replicas race to recover/dispatch the same authorized action.

5. **Real tool/API adapter contracts**
   - classify which APIs support idempotency, query, compensation or transactional semantics.

6. **Jev MoE + runtime execution**
   - semantic router chooses a tool/executor;
   - all side effects pass through this full durable chain.
