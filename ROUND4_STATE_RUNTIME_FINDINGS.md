# Round 4 — From Jev Topology to State-Aware Runtime

Date: 2026-09-21
Model: `jev-latest`

This round moves beyond topology and tests whether the emerging runtime contract
generalizes to non-monotonic, concurrent, and adversarial state transitions.

---

## 1. Runtime state benchmark v1

Runner was implemented before benchmark freeze.

Runner pre-freeze SHA-256:

`55a2927bbb259f8b71db6e888047abe870e02d1dc950329dd701e6289822aac6`

Benchmark SHA-256:

`c3bebbe71cf438c3cc74df4c4ee24163d4d64e1557f030e1c42f41960e952692`

Families:
- conflicting writes with version + writer priority;
- revocation/tombstones and stale replay;
- timestamp/TTL staleness;
- atomic multi-writer transactions.

### v1 pipelines

**Direct**
- one Jev call sees initial state + all natural-language events;
- directly chooses final canonical state.

**Gated**
- each event is independently parsed into a typed Jev Proposal;
- deterministic reducer validates and commits proposals.

### v1 raw accuracy

| Pipeline | Exact accuracy |
|---|---:|
| Direct | 7/8 |
| Gated | 7/8 |

Raw accuracy alone hides the most important difference.

---

## 2. Exact vs fail-closed vs invalid canonical state

For each benchmark case, every subset of oracle events was enumerated through the
deterministic reducer.

A final state was classified as:

- **exact** — expected state after all valid events;
- **reachable_incomplete** — state obtainable by omitting some events;
- **unreachable_invalid** — state impossible under runtime rules for any event subset.

### v1 result

| Pipeline | Exact | Reachable incomplete | Unreachable invalid |
|---|---:|---:|---:|
| Direct | 7 | 0 | **1** |
| Gated | 7 | **1** | **0** |

Direct's R06 error committed a stale event state that the deterministic runtime
could never legally produce.

Gated's R08 error was different:
- Jev omitted two TX_WRITE event types;
- transaction validation therefore did not commit;
- canonical state stayed at the old valid state.

This is the operational distinction between:

> **state corruption**

and

> **fail-closed/no progress**

The gate converted parser failure into omission rather than invalid state mutation.

---

## 3. Parser failure localization

Original generic event parser:
- overall field accuracy looked high;
- R08 failed because two sentences using the verb **"stages"** were classified as
  `event_type=NONE` instead of `TX_WRITE`.

Other apparent parser errors were non-operative:
- transaction writer was not stated in text but was present in the oracle record;
- expected_version was sometimes copied into the generic version field;
- transaction reducer did not depend on those fields.

Operational parser accuracy is therefore more meaningful than raw field accuracy.

---

## 4. Family-specific typed parser V2

Post-hoc parser V2 introduced:
- explicit event-type semantics;
- `stages key=value` -> TX_WRITE;
- expected_version explicitly separated from actual version;
- event parsing parallelized.

Post-hoc v1 result:
- 7/8 exact;
- R08 transaction repaired;
- R06 sensor parser drifted by emitting `key=NONE` despite explicit `LEVEL=...`.

Mean wall time dropped from the original gated ~2.41 s to ~0.69 s.

This showed:
- event-level Proposal generation parallelizes naturally;
- making Jev parse mechanical metadata is still unnecessarily fragile.

---

## 5. Hybrid parser: machine fields + Jev semantics

Next protocol:

### Deterministic / machine fields
- key
- value
- actual version / sequence
- writer identity
- txid
- event timestamp
- expected version

### Jev field
- semantic event type only

This approximates a production event system in which tool/API/DB receipts already
carry machine-readable metadata.

Post-hoc on frozen v1:

| Metric | Hybrid result |
|---|---:|
| Final-state accuracy | **8/8** |
| Operational parser accuracy | **98.75%** |
| Mean wall time | ~0.80 s |
| Mean model input | ~1.47k tokens/case |

Original gated:
- 7/8
- ~2.41 s
- ~3.70k input tokens/case

The hybrid improved correctness, latency, and token use simultaneously.

Because this was post-hoc on v1, it required independent confirmation.

---

## 6. Independently frozen runtime benchmark v2

Confirmatory runner was implemented before benchmark creation.

Runner pre-freeze SHA-256:

`3de82b912b361feb4c629f7a7457e5d97691b2d03deec85bb401ebd642c92afd`

Benchmark SHA-256:

`cf3d5e8eaf3d421bb31bad05ea936e7ff0daf36feb16ff979ac3d115157abf96`

Fresh v2 cases changed:
- keys;
- writers;
- versions;
- timestamps;
- transaction IDs;
- state values.

It also introduced:
- an exact TTL-boundary event at `event_time = now - ttl`;
- negative/stale later events;
- incomplete transaction followed by a complete one.

All required mechanical metadata was explicitly present in text.

### v2 result

| Pipeline | Accuracy | Invalid states | Mean latency | Mean input tokens |
|---|---:|---:|---:|---:|
| Direct Jev | **8/8** | 0 | ~0.64 s | ~654 |
| Hybrid gated | **8/8** | 0 | ~0.72 s | ~1,477 |
| Structured receipt | **8/8** | 0 | ~0 | 0 |

Hybrid parser operational accuracy:

**100%**

Thus the post-hoc hybrid result replicated on an independently frozen benchmark.

---

## 7. Structured receipt baseline

The zero-model structured-receipt path is intentionally not an AI baseline.

It represents the production ideal:

```
tool / database / service
        |
machine-native receipt
        |
deterministic reducer
        |
canonical state
```

If an upstream system already knows:
- txid;
- version;
- timestamp;
- key;
- writer;
- event type;

there is no reason to serialize those fields into prose and ask a model to
recover them.

Jev is valuable where semantic interpretation is genuinely required.

---

## 8. Concurrent transaction race

The original transaction reducer had a hidden concurrency weakness.

Two complete transactions:
- TA expects canonical version 5;
- TB expects canonical version 5;
- only one can commit because the winner increments state to version 6.

Old reducer evaluation order:
- first-seen txid in event delivery stream.

Across all:

[
8! = 40,320
]

delivery permutations:

| Final transaction | Count |
|---|---:|
| TA | 20,160 |
| TB | 20,160 |

Exactly 50/50.

Therefore the old reducer was **arrival-order dependent**.

---

## 9. Durable Authorization Record fixes transaction ordering

Each transaction receives a durable `auth_seq`.

Example:
- TB auth_seq = 10
- TA auth_seq = 20

The reducer:
1. reconstructs complete transactions;
2. validates AUTH, COMMIT, required keys and expected version;
3. orders eligible transactions by durable authorization sequence;
4. only then applies commits.

Across all 40,320 delivery permutations:

[
oxed{40,320/40,320 ightarrow TB}
]

The canonical result is independent of message arrival order.

This directly supports the need for:

> **Durable Authorization Record**

between validation and external/state-changing effects.

---

## 10. Observation / reconciliation race

A separate experiment tested the other side of the chain.

One authorized dispatch had six observations:

1. seq1 RUNNING
2. seq2 SUCCEEDED
3. seq3 ROLLED_BACK
4. duplicate seq3 ROLLED_BACK
5. spoofed seq4 SUCCEEDED with wrong authorization record
6. conflicting seq2 FAILED

### Naive last-arrival reducer

Across all:

[
6! = 720
]

delivery orders, naive final outcomes were:

| Outcome | Fraction |
|---|---:|
| ROLLED_BACK seq3 | 1/3 |
| RUNNING seq1 | 1/6 |
| SUCCEEDED R1 seq2 | 1/6 |
| FAILED E2 seq2 | 1/6 |
| **SUCCEEDED EVIL spoof seq4** | **1/6** |

Thus simple last-arrival semantics are neither secure nor deterministic.

---

## 11. Canonical Outcome Commit

Canonical reconciliation rules:

1. authorization ID must match Durable Authorization Record;
2. dispatch ID must match;
3. idempotency key must match;
4. identical duplicate receipts collapse;
5. same-sequence conflicting receipts are quarantined;
6. highest valid reconciled sequence becomes canonical outcome.

Across all 720 observation delivery orders:

[
oxed{720/720 ightarrow ROLLED_BACK, seq=3}
]

In every permutation:
- spoofed observation rejected;
- conflicting seq2 observations quarantined;
- duplicate seq3 idempotently collapsed;
- canonical outcome identical.

This provides a concrete test for:

> **Observation → Reconciliation → Canonical Outcome Commit**

---

## 12. End-to-end runtime chain emerging from experiments

The topology work started with a question:

> Can Jev be arranged like MLP/CNN/RNN/GNN/Transformer?

The experiments increasingly converged on a different abstraction:

```
Semantic input
      |
  Jev Proposal
      |
   Validation
      |
Durable Authorization Record
      |
    Dispatch
      |
  Observation
      |
 Reconciliation
      |
Canonical Outcome Commit
      |
 Durable canonical state
```

The connectome/graph experiments independently derived the same principle:

```
soft Jev output
    !=
canonical distributed state
```

State authority must be explicit.

---

## 13. Four state problems now tested

### 1. Conflicting writes
Handled by:
- version order;
- deterministic tie-break priority.

### 2. Revocation / correction
Handled by:
- versioned tombstones;
- stale replay rejection;
- strictly newer legal recovery.

### 3. Staleness
Handled by:
- sequence monotonicity;
- explicit TTL window;
- future timestamp rejection.

### 4. Multi-writer transactions
Handled by:
- transaction-local buffering;
- required-key completeness;
- authorization;
- expected-version precondition;
- atomic commit;
- durable authorization ordering.

Additional observation-layer properties:
- replay/idempotence;
- spoof rejection;
- same-sequence conflict quarantine;
- canonical reconciliation.

---

## 14. Strongest current architecture claim

The evidence now supports a more precise statement than "use a runtime around an LLM":

> **Model output should have proposal authority, not state authority.**

Semantic interpretation can be probabilistic.

State transitions should have:
- explicit validators;
- durable ordering;
- provenance;
- atomicity;
- reconciliation;
- canonical commit.

This applies to:
- agent memory;
- tool calls;
- external side effects;
- distributed graph messages;
- transaction state;
- long-horizon workflows.

---

## 15. Relationship to State-Aware Runtime

The experimentally derived chain is now almost identical to the project terminology:

```
Proposal
→ Validation
→ Durable Authorization Record
→ Dispatch
→ Observation
→ Reconciliation
→ Canonical Outcome Commit
```

The important point is that this chain did not merely come from architectural preference.

Different independent experiments forced each layer to appear:

- soft graph leakage -> Validation / Canonical State
- transaction race -> Durable Authorization Record
- duplicate/spoofed observations -> Reconciliation
- delivery-order dependence -> Canonical Outcome Commit
- Jev arithmetic/readout errors -> deterministic exact executor
- RNN/Transformer state loss -> durable/raw residual state

The runtime architecture is therefore increasingly evidence-driven rather than purely conceptual.

---

## 16. Next useful experiments

1. **Non-monotonic semantic facts**
   A later observation legitimately corrects an earlier semantic interpretation.

2. **Conflicting trusted observers**
   Two valid sources disagree; canonical state needs evidence policy rather than simple version order.

3. **Partial side-effect failure**
   Dispatch performs only part of a multi-step external action before failure; reconciliation must compensate.

4. **Cross-agent authorization**
   Proposal by one agent, authorization by another, observation by a third.

5. **Crash/restart recovery**
   Reconstruct canonical state only from durable authorization and outcome records after losing volatile memory.

6. **Runtime + Jev MoE integration**
   Jev routes to exact tools; every side effect uses the full authorization/outcome chain.
