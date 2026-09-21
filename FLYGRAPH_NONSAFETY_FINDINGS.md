# FlyGraph + Non-Safety Jev Topology Findings

Date: 2026-09-21  
Model: `jev-latest`

## 1. Real MaleCNS graph extraction

A real type-level motif was extracted from the official MaleCNS v1.0 static connectivity tables.

Source:
- MaleCNS v1.0
- official type-level connection tables at `https://male-cns.janelia.org/build/tables/<type>_connections.html`
- seed type: `pC1_12b`

The first extracted motif contains 12 cell types and 96 directed type-level edges.

A smaller six-node strong-connection graph was then frozen for Jev experiments. Only edges with MaleCNS weight >= 250 were retained.

Nodes:
- pC1_12b
- mAL_m8
- SIP103m
- FLA001m
- SIP122m
- SIP100m

Real FlyGraph:
- 6 nodes
- 13 directed edges
- density 0.433
- reciprocity 0.462
- strongly connected
- directed diameter 3
- every node can reach the fixed readout node `mAL_m8` within <= 2 hops

Frozen graph/control file:

`flygraph_controls_v1.json`

SHA-256:

`3ee9ef19e5ce68d333cea19fdd227328623b624e52c8627ef59ff81678f0dafb`

Controls:
1. **degree-preserving control** generated with directed Havel-Hakimi using the exact per-node in/out degrees;
2. **random control** with the same node count and edge count, constrained to be strongly connected and to retain <=2-hop readout coverage.

The biological edge-weight multiset is retained but shuffled on controls. In the first benchmark, weights are recorded as provenance only and do not alter fact truth or message priority.

Important limitation: this is a **real type-level MaleCNS motif**, not the full 166k-neuron body-level graph.

---

## 2. Frozen non-safety benchmark

File:

`non_safety_benchmark_v1.json`

SHA-256:

`f5532639f5e0a3b0e75ed9d6135e4bb593a12ce49adeb314fd117a56d0547571`

Eight tasks:
1. set majority
2. arithmetic modulo
3. long-range key/value lookup
4. ordered state update
5. graph reachability
6. distributed propositional logic
7. directed 3-cycle detection
8. set-frequency aggregation

Each task has exactly six source slots.

### Distributed packet protocol

Each physical graph node initially receives only one logical source slot.

Every Jev packet exposes:
- `slot_1 ... slot_6`
- `decision_ready`
- `answer`

Unknown slots have an explicit `UNKNOWN` state.

Two synchronous message-passing rounds are run.

The final answer is read **only from mAL_m8**. There is no raw-global-fact skip connection.

Thus topology genuinely participates in information transport.

---

## 3. First fixed-mapping result

| Variant | Jev answer accuracy | Mean correct slot recall | Mean known slots |
|---|---:|---:|---:|
| Direct full context | 6/8 | 100% | 6.00/6 |
| FlyGraph | 2/8 | 60.4% | 3.62/6 |
| Degree-preserving control | 2/8 | 64.6% | 3.88/6 |
| Random graph | 3/8 | 77.1% | 4.62/6 |

This single mapping is confounded by which logical slot happens to occupy which physical graph node, so it must not be used to rank the graph topologies.

### Direct readout failure

Direct sees all six source facts correctly on every task, but still answers two tasks incorrectly:

- modulo arithmetic: predicts M3 instead of M1;
- ordered state update: predicts 14 instead of 12.

An offline deterministic solver using the exact same recovered slots gets all 8/8.

Therefore:

> full state recovery does not imply correct Jev readout/computation.

---

## 4. Deterministic readout over graph packets

Using only final packet slots, without further model calls:

| Variant | Jev head | Deterministic solver |
|---|---:|---:|
| Direct | 6/8 | 8/8 |
| FlyGraph | 2/8 | 1/8 |
| Degree-preserving | 2/8 | 3/8 |
| Random | 3/8 | 4/8 |

For graph variants, deterministic reasoning cannot recover missing facts. The limiting factor is first information transport, then readout.

Notably, graph message passing produced essentially no wrong non-UNKNOWN slot values. Missing evidence was usually converted to `UNKNOWN`, which is a desirable failure mode.

---

## 5. Balanced six-permutation transport test

The first mapping was arbitrary, so a second experiment isolated fact transport.

Six unique tokens were cyclically permuted so that every logical source slot occupied every physical graph node exactly once.

File:

`flygraph_transport.py`

SHA-256 at run time:

`b8260da9eb9e4cfd55a20035a936d4bae1fbe8ca337e93398eaa12c22097f427`

### Balanced transport result

| Topology | Mean slot recall | Mean recovered slots | Full 6/6 cases |
|---|---:|---:|---:|
| FlyGraph | **94.4%** | 5.67/6 | 4/6 |
| Degree-preserving control | 88.9% | 5.33/6 | 2/6 |
| Random graph | **97.2%** | 5.83/6 | 5/6 |

This is too small to establish a biological-topology advantage.

Current interpretation:
- real FlyGraph is better than this exact degree-preserving control;
- random is slightly better than FlyGraph;
- differences are only a few lost token transmissions and require much more data before statistical interpretation.

The important negative result is:

> A small real FlyGraph motif does not automatically outperform random topology on arbitrary synthetic information routing.

---

## 6. Physical-source transport

Balanced transport success by physical source:

### FlyGraph

- pC1_12b: 5/6, distance 2, two <=2-hop paths
- mAL_m8: 6/6, local readout
- SIP103m: 6/6, distance 1
- FLA001m: 6/6, distance 1, three <=2-hop paths
- SIP122m: 6/6, distance 1
- SIP100m: 5/6, distance 2, one path

### Degree-preserving control

- pC1_12b: 6/6
- mAL_m8: 6/6
- SIP103m: 4/6
- FLA001m: 6/6
- SIP122m: 6/6
- SIP100m: 4/6

### Random

- pC1_12b: 5/6
- all other sources: 6/6

This suggests that short path length and redundant paths matter for Jev packet transport, as expected.

---

## 7. Round-by-round transport audit

Across the balanced transport suite, compare Jev-recovered facts only against facts that are theoretically reachable at that round.

### FlyGraph
- round 0: 36/36 = **100.0%**
- round 1: 112/114 = **98.2%**
- round 2: 181/186 = **97.3%**

### Degree-preserving
- round 0: 36/36 = **100.0%**
- round 1: 112/114 = **98.2%**
- round 2: 173/180 = **96.1%**

### Random
- round 0: 36/36 = **100.0%**
- round 1: 112/114 = **98.2%**
- round 2: 181/186 = **97.3%**

There were no false-positive known facts in this audit.

This is best described as a **conservative lossy message channel**:
- high fact retention;
- errors mostly become UNKNOWN;
- no observed fact mutation/hallucination in the balanced token transport test.

---

## 8. Non-safety architecture zoo

The same frozen non-safety benchmark was also used exploratorily with several non-graph architectures.

This comparison is post-hoc relative to benchmark v1 and therefore requires a fresh benchmark for confirmation.

| Architecture | Jev accuracy | Slot accuracy | Known slots | Calls | Mean input tokens |
|---|---:|---:|---:|---:|---:|
| MLP dense | 3/8 | 56.3% | 3.50/6 | 7 | 21.0k |
| RNN + raw residual | **6/8** | **100%** | **6.00/6** | 7 | 17.3k |
| Transformer-1 | **1/8** | 62.5% | 3.88/6 | 13 | 56.1k |
| MoE | **6/8** | **100%** | **6.00/6** | 4 | 7.5k |

RNN-residual and MoE recover every source fact on all eight tasks.

Their only two Jev answer errors are exactly the same arithmetic/state-execution failures seen in Direct:
- N02 modulo arithmetic
- N04 ordered arithmetic state update

A deterministic solver over their recovered packets gets **8/8**.

### MoE routing on non-safety tasks

Router behavior was highly task-aligned:

- set majority -> aggregation
- modulo arithmetic -> arithmetic_sequence
- key/value -> retrieval
- sequence state -> arithmetic_sequence
- reachability -> graph_logic
- propositional logic -> graph_logic
- motif -> graph_logic
- set frequency -> aggregation

Thus the earlier MoE result is not specific to safety classification.

---

## 9. Jev channel-capacity mechanism probe

File:

`jev_channel_capacity.py`

SHA-256:

`0fd74ea5e590ad8e448c6f7f73bceaa114ce5e4c65f0c027ab9653844e2df806`

### Fan-in capacity

Perfect one-slot packets were merged with fan-in k = 1..6, five balanced repeats each.

Result:

- k=1: all visible slots preserved
- k=2: all visible slots preserved
- k=3: all visible slots preserved
- k=4: all visible slots preserved
- k=5: all visible slots preserved
- k=6: all six slots preserved

No hidden slot was hallucinated.

Therefore the architecture failures are **not explained by a hard Jev fan-in capacity limit at six packets**.

### Identity depth

A perfect 6/6 packet was relayed through six consecutive Jev identity-update layers.

Three independent chains:

- depth 1: 6/6
- depth 2: 6/6
- depth 3: 6/6
- depth 4: 6/6
- depth 5: 6/6
- depth 6: 6/6

All 18 relay states retained every slot and selected COMPLETE.

Therefore:

> depth alone does not destroy a clean packet.

Loss arises from realistic multi-node state updates, uncertain intermediate packets, semantic payload complexity, or interaction among repeated evidence.

---

## 10. A surprising readout inconsistency

In the balanced transport experiment, many final packets contained all six correct tokens, yet the Jev answer head still selected `INCOMPLETE`.

This is analogous to earlier safety experiments where:
- representation channels were correct;
- final response_strategy disagreed with the representation.

This strengthens a general architecture principle:

> **State estimation and action/readout should be separately audited.**

A deterministic runtime gate is not merely a safety feature; it can also serve as a computation/readout consistency layer.

---

## 11. What the FlyGraph experiment currently says

### Supported

1. A real MaleCNS connectivity motif can be used directly as a Jev message-passing architecture.
2. Its topology can be frozen and compared against exact-degree and random controls.
3. Jev packet transport along the graph is highly but not perfectly reliable.
4. Real FlyGraph beat one exact degree-preserving control in balanced transport.
5. Random topology slightly beat FlyGraph in this tiny synthetic test.
6. Multi-path redundancy and distance affect fact survival.
7. The main bottleneck is not raw fan-in capacity or depth.
8. Jev readout can fail even after state is correct.

### Not supported

Current experiments do **not** show that:
- fruit-fly topology is generally superior to random graphs;
- MaleCNS topology is a better general reasoning architecture;
- a six-node motif represents the full connectome's inductive bias;
- Jev can replace biological neuron dynamics;
- Jev can replace a Transformer as a token-level primitive.

---

## 12. Emerging architecture

Across safety and non-safety tasks, the same design keeps reappearing:

```
raw / durable state
        |
   sparse router
   /    |     \
Jev   Jev    Jev      <- typed semantic experts
   \    |     /
 structured packets
        |
 deterministic state transport / provenance
        |
 optional graph / recurrent topology
        |
    Jev readout
        |
 deterministic computation / consistency gate
```

The experiments increasingly favor:
- conditional routing over indiscriminate all-to-all attention;
- explicit provenance;
- raw/residual memory;
- structured packet state;
- deterministic operations for exact arithmetic/state updates;
- Jev for semantic uncertainty rather than exact bookkeeping.

---

## 13. Next clean experiments

1. **Fresh non-safety benchmark v2**
   - created after the exploratory architecture comparison;
   - verify whether MoE/RNN-residual > Transformer-style packet propagation repeats.

2. **Larger real FlyGraph**
   - 16–32 type nodes, or a body-level subgraph;
   - multiple seeds / brain regions;
   - average over readout positions and source mappings.

3. **Weighted FlyGraph**
   - use real synaptic weights as routing capacity or message priority;
   - compare against weight-shuffled controls.

4. **Deterministic transport + Jev semantic update**
   - move exact slot/provenance transport into runtime;
   - let Jev operate only on semantic interpretation;
   - test whether this removes conservative fact loss.

5. **Exact-computation head**
   - arithmetic / graph algorithms executed deterministically from recovered packet state;
   - keep Jev as state estimator/router rather than calculator.
