# Jev Architecture Research — Round 2 Results

Date: 2026-09-21
Model: `jev-latest`

This report extends the earlier architecture-zoo and FlyGraph experiments with:
1. an independently frozen non-safety benchmark v2;
2. a 24-type MaleCNS extraction and 16-node strongly-connected core;
3. large-graph pure fact transport;
4. lesion robustness analysis;
5. a Jev-router + deterministic-runtime counterfactual.

---

## 1. Independent non-safety benchmark v2

Runner was fixed before the benchmark was created.

Runner pre-freeze SHA-256:

`66fe2e4690615fff061e751fd4bc7a3bfbb56c393e2fd5f35f9a74ef7c4f65bd`

Benchmark v2 SHA-256:

`f568722107a79b9998756f704e2595cb7bbb89cba2427f8e4b1b243ec628dd13`

Fresh tasks include:
- majority aggregation
- modulo arithmetic
- exact key/value lookup
- ordered state update
- negative reachability
- negative logical entailment
- negative 3-cycle detection
- set-frequency aggregation

### v2 architecture results

| Architecture | Jev answer accuracy | Slot accuracy | Mean known slots | Mean input tokens |
|---|---:|---:|---:|---:|
| Direct | 6/8 | **100%** | 6.00/6 | 1.9k |
| MLP dense | 2/8 | 54.2% | 3.25/6 | 21.0k |
| RNN + raw residual | 4/8 | **100%** | 6.00/6 | 17.3k |
| Transformer-1 | **1/8** | 72.9% | 4.38/6 | 56.0k |
| MoE | **6/8** | **100%** | 6.00/6 | 7.5k |

### What replicated

From non-safety v1 to independently frozen v2:

- Direct preserves all source facts.
- MoE preserves all source facts.
- RNN + raw residual memory preserves all source facts.
- Dense MLP loses facts.
- Transformer-like all-to-all packet updates lose facts.

The exact accuracies changed, but the **state-retention ordering replicated**.

### What did not fully replicate

RNN-residual answer accuracy dropped from 6/8 on v1 to 4/8 on v2 despite retaining 6/6 facts.

Its additional failures were:
- negative graph reachability;
- negative logical entailment.

Thus:

> Raw residual memory fixes state loss, but it does not guarantee a reliable Jev computation/readout head.

---

## 2. Deterministic readout on v2

Direct, RNN-residual, and MoE all recovered every slot on every v2 task.

A deterministic executor operating on exactly those recovered slots gets:

- Direct packet: 8/8
- RNN-residual packet: 8/8
- MoE packet: 8/8

MoE's two model-answer errors are again:
- modulo arithmetic;
- ordered state update.

This exactly repeats v1.

The state representation is sufficient; the remaining failure is execution/readout.

---

## 3. MoE routing replicated across two frozen benchmarks

Across non-safety v1 + v2:

- 16 total tasks
- router top-1 expert choice: **16/16 correct**

Expected semantic routing:

| Task family | Expected expert |
|---|---|
| majority / set frequency | aggregation |
| modulo / ordered state update | arithmetic_sequence |
| key/value lookup | retrieval |
| reachability / entailment / motif | graph_logic |

The router selected the expected expert on every task in both frozen sets.

This result is stronger than the final MoE answer result:
- routing: 16/16
- full MoE answer: 12/16

The errors occur **after correct routing**.

---

## 4. Jev router + deterministic runtime

Offline counterfactual using the already-recorded router outputs:

1. Jev routes the task to a semantic computation family.
2. A deterministic executor performs exact aggregation/arithmetic/retrieval/graph logic.
3. No additional model reasoning is needed for the benchmark result.

### Result

| System | Accuracy over v1+v2 |
|---|---:|
| Full Jev MoE | 12/16 |
| **Jev router + deterministic executor** | **16/16** |

### Model-token comparison over 16 tasks

Full MoE:
- input: 120,677
- output: 25,331

Router only:
- input: 6,808
- output: 878

Reduction:
- input tokens: **94.36%**
- output tokens: **96.53%**

This is a counterfactual benchmark calculation, not a production latency/cost claim.

It strongly motivates a hybrid design:

```
request
   |
Jev semantic router
   |
typed deterministic executor / tool
   |
auditable result
```

---

## 5. Larger MaleCNS motif

A larger real type-level MaleCNS motif was extracted from official static type connectivity tables.

Source file:

`flygraph_pc1_large_v1.json`

SHA-256:

`e90e325e15397fbdbeb5ce0a84c00beed10445fbf59ea598085268063ec6dd3e`

Extraction:
- seed: `pC1_12b`
- 33 candidate types from strongest pre/post partners
- select seed + 23 types with highest internal weighted degree

Full 24-type induced graph:
- 24 nodes
- 297 directed edges
- density 0.538
- reciprocity 0.640
- largest SCC 23
- total type-level synaptic weight 42,176

At weight >= 100:
- 110 edges
- density 0.199
- largest SCC 19

This is substantially less clique-like than the original six-node motif.

---

## 6. Frozen 16-node strongly-connected MaleCNS core

From the weight>=100 largest SCC:
- greedily remove low internal-weight nodes while preserving strong connectivity;
- retain 16 nodes.

Control file:

`flygraph_large_controls_v1.json`

SHA-256:

`db39bb7941fd170a0c87cde3d410b1aa26350c0a630662c4e9e924183e2e9149`

### FlyGraph core

- 16 nodes
- 77 edges
- density 0.321
- reciprocity 0.338
- strongly connected
- diameter 5

Readout is selected automatically to minimize worst-case inbound distance:
- readout: `SIP122m`
- max source distance: 3
- mean source distance: 1.375

Controls:
1. exact per-node in/out-degree Havel-Hakimi graph;
2. same-N/E random strongly-connected graph.

---

## 7. Structural comparison of 16-node graphs

### Distance to fixed readout

| Topology | Mean distance | Max distance |
|---|---:|---:|
| FlyGraph | 1.375 | 3 |
| Degree control | **1.313** | 3 |
| Random | 1.813 | 3 |

FlyGraph is not simply shortest.

### Simple path redundancy to readout (<=3 hops)

Mean number of paths/source:

- FlyGraph: **15.75**
- degree control: 14.88
- random: **6.50**

### Mean edge connectivity to readout

- FlyGraph: 4.67
- degree control: 4.67
- random: 3.87

FlyGraph has many more redundant short routes than the random control, while also retaining a few one-path bottlenecks.

This produces a heterogeneous robustness profile.

---

## 8. Large-graph pure fact transport

Runner:

`flygraph_large_transport.py`

SHA-256:

`80cbe07e042342c6f816e22cc865453762994c43b99d1b2e1b7ab63e100aab67`

To isolate transport from semantic readout:
- 12 independent source facts;
- packet = 12 NOUL fact-presence channels;
- only nodes that are <=2 hops from readout in all three topologies are used as sources;
- 2 synchronous rounds;
- two cyclic source mappings;
- no task-answer head.

### Result

All graph variants recover all source facts:

| Topology | Recall | Strong P>=0.8 | Mean P(true) |
|---|---:|---:|---:|
| FlyGraph | 12/12 both mappings | 12/12 | 0.954 |
| Degree control | 12/12 both mappings | 12/12 | 0.953 |
| Random | 12/12 both mappings | 12/12 | 0.952 |

This is an important correction to the small-graph result.

When the edge message is reduced to a clean monotonic boolean channel, **topology is not the bottleneck** at this scale.

The previous fact loss came from richer choice/state packets, not from graph size itself.

---

## 9. Packet complexity is a primary variable

Across mechanism probes:

### Clean fan-in
Perfect partial packets with fan-in 1..6:
- every visible fact retained;
- no hidden fact hallucinated.

### Clean identity depth
A perfect 6/6 packet relayed through six Jev layers:
- 6/6 facts retained at every layer in every repeat.

### 16-node NOUL graph transport
- 12/12 facts retained after two graph rounds.

Therefore:

> Jev does not exhibit a simple hard message-capacity or depth limit in these experiments.

Information loss appears when messages contain richer, uncertain, interacting semantic state.

This makes **packet design** a first-class architectural parameter.

---

## 10. Offline lesion robustness of the 16-node graphs

2,000 Monte Carlo trials per random-lesion condition.

### Random edge deletion: mean original-source reachability

| Edge deletion | Fly | Degree control | Random |
|---:|---:|---:|---:|
| 10% | 0.979 | 0.971 | **1.000** |
| 20% | 0.955 | 0.944 | **0.999** |
| 30% | 0.924 | 0.913 | **0.987** |
| 40% | 0.882 | 0.867 | **0.954** |
| 50% | 0.828 | 0.813 | **0.869** |
| 60% | **0.725** | 0.713 | 0.668 |

Interpretation:

Random wiring is more uniformly robust at low-to-moderate damage. At extreme edge deletion, the dense recurrent redundancy of FlyGraph becomes relatively advantageous.

### Random node deletion

Random remains strongest for 1–5 removed non-readout nodes, with FlyGraph consistently above the exact-degree control.

### Weight is not structural criticality

Removing the highest synaptic-weight edges first:
- even 30 highest-weight edges can be removed without losing source reachability in these graphs.

The most damaging single FlyGraph edges are instead several lower/mid-weight bridge edges.

Thus:

> synaptic weight and graph-theoretic criticality are distinct.

This is directly relevant for later biological lesion experiments.

---

## 11. Current architecture conclusion

The experiments now point to a more specific architecture than the original "Jev network" idea.

### Jev is strong at
- semantic task routing;
- typed probabilistic state estimation;
- local interpretation;
- producing auditable intermediate state;
- monotonic fact transport when the packet contract is simple.

### Jev is weaker at
- exact arithmetic;
- exact ordered state execution;
- some negative graph/logical judgments;
- retaining rich uncertain packets under indiscriminate all-to-all communication;
- acting as both state representation and authoritative readout without checks.

### Strong current system pattern

```
durable/raw input
      |
Jev semantic router
      |
   +--+-------------------+
   |                      |
Jev semantic tool    deterministic exact tool
   |                      |
typed state / packet       |
   +-----------+----------+
               |
     optional sparse graph /
     external memory / runtime
               |
        consistency check
               |
             output
```

This is closer to a **typed probabilistic runtime** than to a replacement Transformer.

---

## 12. Scientific status

Supported by two frozen non-safety benchmarks:
- MoE routing generalizes across fresh instances.
- MoE preserves state better than the tested Transformer-like packet architecture.
- Transformer-like Jev all-to-all updates repeatedly lose structured facts.
- exact runtime computation can repair Jev readout errors when state is complete.

Supported by real MaleCNS experiments:
- real connectome topology can directly host Jev message passing;
- real topology does not automatically beat random topology;
- biological topology shows a distinct redundancy/bottleneck profile;
- clean Jev fact channels scale from 6 to 16 graph nodes without loss in the tested setting.

Not yet established:
- statistical superiority of FlyGraph over controls;
- generality beyond these task families;
- behavior on body-level instead of type-level connectomes;
- whether biological synaptic weights provide useful routing priors;
- scaling beyond tens of Jev nodes.

---

## 13. Highest-value next experiments

1. **Weighted transport / capacity**
   Use MaleCNS synaptic weights to allocate message budget or priority rather than treating weights as metadata.

2. **Lesion-aware Jev transport**
   Run a small number of Jev transport trials under bridge-edge vs high-weight-edge lesions.

3. **Fresh task families**
   Add sorting, constraint satisfaction, temporal lookup, path cost, symbolic rewrite, and multi-step planning.

4. **Body-level subgraph**
   Move from type-level connectivity to a small body-level circuit if the public query endpoint can be used efficiently.

5. **Router + tool runtime prototype**
   Convert the counterfactual 16/16 result into an executable runtime:
   Jev chooses executor and extracts typed arguments; deterministic code executes; Jev only interprets when needed.
