# Jev Graph Runtime — Round 3: Body-Level MaleCNS and Canonical State

Date: 2026-09-21
Model: `jev-latest`

## 1. Body-level MaleCNS is publicly queryable

The public neuPrint API exposes `male-cns:v1.0`.

The experiment queried:
- seed body: `13562`
- type: `pC1_12b`
- instance: `pC1_12b_L`

The seed's strongest body-level pre/post partners were queried directly through neuPrint, avoiding a full 1 GB flat-connectome scan.

---

## 2. Frozen body-level circuit

File:

`flygraph_body_pc1_v1.json`

SHA-256:

`2399a3977ac282e8bdf324e16d332d5317bab2106194ad117f02bbaf6c9be0d6`

Construction:
1. seed body 13562;
2. top 20 incoming + top 20 outgoing body-level partners;
3. 41-body candidate induced graph;
4. threshold body-level `ConnectsTo.weight >= 20`;
5. choose largest SCC;
6. reduce to 16 bodies while preserving strong connectivity.

Candidate graph:
- 41 bodies
- 508 directed body-level edges
- density 0.310
- strongly connected at weight>=1

At weight>=20:
- 90 edges across 41 candidates
- largest SCC = 20

Final 16-body biological core:
- 16 bodies
- 38 edges
- density 0.158
- reciprocity 0.263
- strongly connected
- directed diameter 9
- total retained synaptic weight 1,636

Readout chosen to minimize inbound eccentricity:
- body 13244
- type `SMP550`
- instance `SMP550_R`
- max source distance = 3
- mean source distance = 2.063

This is substantially sparser than the earlier type-level graph.

---

## 3. Frozen body-level controls

File:

`flygraph_body_controls_v1.json`

SHA-256:

`acedf9820fb7e51d927b024f40cdcdc4f86f43a80cbdd234b7a00e4f478cf861`

Controls:
- exact per-body in/out-degree control;
- same-N/E random strongly-connected control.

At the same biological readout body:

| Graph | Edges | Mean source distance | Max source distance |
|---|---:|---:|---:|
| Fly body graph | 38 | **2.063** | **3** |
| exact-degree control | 38 | 3.125 | 5 |
| random | 38 | 2.500 | 4 |

Thus the biological wiring arranges the same body-level degree budget into faster convergence toward this particular readout than the exact-degree control.

This does not imply globally optimal communication.

---

## 4. Ungated soft-NOUL transport failure

Runner:

`flygraph_body_transport.py`

SHA-256:

`7d5ac6e48651ca800c9920d374b5bba8b0f72356fd8ccb5bcc5d37b5c726ba5c`

Setup:
- every body starts with one unique source fact;
- packet = 16 NOUL fact-presence probabilities;
- up to five synchronous rounds;
- final readout is body 13244;
- soft packets are passed directly to downstream Jev nodes.

Superficially, all graphs reached 16/16 facts.

But this result was invalid as a topology measurement.

### Impossible one-hop propagation

For the biological graph:

At round 0:
- theoretically reachable facts at readout: 1
- model present facts: 1

At round 1:
- theoretically reachable facts: **3**
- model present facts: **16**

The 13 impossible facts had probabilities roughly 0.83–0.91.

The same occurred in controls.

### Source of leakage

At initialization, absent facts are not exactly probability zero:
- typical absent probabilities: ~0.04–0.09
- some as high as ~0.2

When several incoming soft packets are placed in downstream context, Jev interprets repeated weak nonzero probability as evidence/provenance.

This creates:

> **probabilistic provenance leakage**

or equivalently:

> **soft-evidence amplification under graph aggregation**

The issue is not topological reachability. It is a state-semantics error.

---

## 5. Proposal is not canonical state

This motivates a strict separation:

```
Jev probability
    |
  Proposal
    |
provenance / authorization validation
    |
Canonical state
```

A probability is evidence about a proposition. It is not itself proof that the proposition has entered the durable world state.

Graph edges must not transport every soft probability as if it were canonical provenance.

---

## 6. Runtime-gated transport

Runner:

`flygraph_body_transport_gated.py`

SHA-256:

`3609f7312f2c26a73e4372dad11ed762ff7d096101118a3c25b97ad134c22e92`

Runtime rule:

1. canonical state at each node is a discrete set of committed fact IDs;
2. only canonical self/incoming facts authorize a fact;
3. Jev proposes fact presence;
4. proposal must satisfy `p >= 0.5`;
5. proposal must also be in the authorized provenance set;
6. previous canonical facts are monotonic and cannot be forgotten;
7. validated proposals are committed.

Formally:

[
C_{t+1}
=
C_t
cup
left(
P_t^{\ge 0.5}
cap
A_t
ight)
]

where:
- (C_t): canonical committed facts;
- (P_t): Jev proposals;
- (A_t): facts authorized by canonical self/incoming provenance.

---

## 7. Runtime gating restores exact graph semantics

### Biological body graph

Readout fact count:

[
1 ightarrow 3 ightarrow 11 ightarrow 16
]

It reaches all facts at round 3.

This exactly matches its shortest-path distribution to readout.

### Exact-degree control

[
1 ightarrow 3 ightarrow 5 ightarrow 8 ightarrow 13 ightarrow 16
]

All facts arrive at round 5.

### Random control

[
1 ightarrow 4 ightarrow 8 ightarrow 11 ightarrow 16
]

All facts arrive at round 4.

Again, this matches graph reachability.

### Validator statistics

Across all graph variants and all rounds:

- unauthorized false proposals committed: **0**
- authorized facts missed by Jev proposal: **0**
- canonical fact corruption: **0**

Under the tested monotonic-OR operation, the Jev node plus runtime validator behaves like an exact graph update.

---

## 8. Gating also reduces compute

Ungated vs gated body-level transport:

| Graph | Input tokens ungated | Gated | Reduction | Latency ungated | Gated | Reduction |
|---|---:|---:|---:|---:|---:|---:|
| Fly | 266,437 | 161,684 | **39.3%** | 6.70 s | 4.89 s | **27.0%** |
| exact-degree | 266,576 | 162,008 | **39.2%** | 5.61 s | 4.89 s | 12.9% |
| random | 266,428 | 162,338 | **39.1%** | 6.04 s | 5.10 s | 15.5% |

Reason:

The downstream Jev sees compact canonical fact-ID lists rather than full soft probability packets from every neighbor.

Thus runtime canonicalization improves:
- correctness;
- interpretability;
- token cost;
- latency.

---

## 9. Relationship to earlier mechanism probes

Earlier experiments established:

### Perfect fan-in
Jev can merge 1–6 perfect packets without losing visible facts.

### Perfect identity depth
A full 6/6 packet survives six repeated Jev relays.

### Type-level 16-node clean NOUL transport
12 clean facts survive two graph rounds.

The body-level leakage therefore does not contradict those results.

The critical difference is:

- **clean packet**: discrete/high-certainty state;
- **ungated body graph**: many soft nonzero probabilities repeatedly reintroduced as context.

The problem is not node capacity.

It is **the semantics of soft state under repeated aggregation**.

---

## 10. Architecture principle

This is currently the strongest general result from the entire Jev topology project:

> **Probabilistic model output should not be used directly as durable distributed state.**

Instead:

```
Model output
   ↓
Proposal
   ↓
Validation / authorization / provenance
   ↓
Canonical commit
   ↓
Next graph step
```

This applies beyond safety:
- memory facts;
- tool outcomes;
- graph messages;
- agent state;
- workflow state;
- distributed semantic packets.

It also explains several earlier failures:
- Transformer error broadcast;
- GNN representation drift;
- RNN stale/ambiguous state;
- packet/readout disagreement.

All are worsened when uncertain intermediate model output is treated as authoritative next-step state.

---

## 11. Connectome interpretation

The body-level experiment now allows a cleaner separation:

### Biological topology
determines:
- which messages may flow;
- route lengths;
- redundancy;
- bottlenecks.

### Jev
provides:
- semantic/probabilistic proposals at nodes.

### Runtime
determines:
- whether a proposal becomes state;
- provenance;
- monotonicity/invariants;
- exact transport semantics.

This is arguably a more natural NeuroAI analogy than replacing each biological neuron with one Jev call.

The connectome supplies the **wiring prior**.
Jev supplies the **semantic local operator**.
The runtime supplies the **state-transition law**.

---

## 12. Current best architecture

Across the project, a consistent design has emerged:

```
                   sparse topology / router
                    /        |        \
             Jev proposal  Jev proposal  Jev proposal
                    \        |        /
                     typed proposals
                           |
               authorization / validation
                           |
                    canonical commit
                           |
             durable / residual / graph state
                           |
             deterministic exact operations
                           |
                       readout
```

For general tasks:
- Jev is particularly strong as a semantic router.
- deterministic executors should handle exact arithmetic/graph/state-machine work.
- graph/recurrent topology can organize information flow.
- canonical runtime state must sit between model invocations.

---

## 13. Scientific caution

The runtime-gated monotonic OR task is intentionally simple.

It does not show that arbitrary semantic graph updates can be made exact with the same validator.

Rather, it demonstrates the principle that:
- the runtime can enforce invariants unavailable to a soft model;
- typed model proposals can coexist with exact graph-state evolution.

The next challenge is to design richer validators for:
- non-monotonic state updates;
- conflicting observations;
- weighted evidence;
- revocation;
- temporal staleness;
- multi-writer commits.

These are closer to real agent/runtime problems.
