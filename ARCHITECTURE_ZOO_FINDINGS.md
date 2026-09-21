# Jev Architecture Zoo — Frozen-Holdout Results

Date: 2026-09-21  
Model: `jev-latest`

## What was tested

Jev is treated as a typed semantic operator placed inside explicit computation graphs. These are architecture analogues, not trainable neural networks.

Tested families:

1. Direct single-call baseline
2. Dense MLP-like 3 -> 3 -> 1
3. CNN-like local windows + pooling
4. RNN-like recurrent packet state
5. RNN + cumulative raw residual memory
6. GNN-like sparse message passing
7. DeepSets-like set pooling
8. Global multi-head attention
9. 1-block Transformer-like self-attention
10. 2-block Transformer-like self-attention
11. Encoder-decoder cross-attention
12. Sparse Mixture-of-Experts
13. Perceiver-like latent bottleneck
14. Transformer + MoE
15. Transformer + full-context global skip packet

All later experiments use the V3 packet contract with independent channels for:
- override attempt
- meta/quotation context
- whether the concrete task has been observed
- substantive harm
- policy conflict
- safe core availability
- decision readiness
- response-strategy distribution

## Frozen holdout v1

SHA-256:

`725d23bd7431ac3d6d02becf0da206d0681f6eb8b1a76d02a589a782ee659a18`

Eight cases were frozen before the advanced topology runs.

### Single-run comparison

| Architecture | Accuracy | Guarded | Mean expected-label P | Mean Brier | Calls | Critical path | Mean input tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct V3 | 8/8 | 8/8 | 0.828 | 0.117 | 1 | 0.75 s | 1.5k |
| MLP V3 | 8/8 | 8/8 | 0.944 | 0.013 | 7 | 2.28 s | 15.5k |
| CNN V3 | 6/8 | 6/8 | 0.651 | 0.399 | 6 | 2.13 s | 11.8k |
| RNN-residual V3 | 8/8 | 8/8 | 0.884 | 0.059 | 4 | 2.66 s | 7.5k |
| GNN V3 | 8/8 | 8/8 | 0.938 | 0.016 | 9 | 2.14 s | 20.3k |
| DeepSets | 5/8 | 5/8 | 0.519 | 0.668 | 4 | 1.36 s | 7.7k |
| Multi-head attention | 5/8 | 5/8 | 0.608 | 0.730 | 7 | 2.04 s | 15.6k |
| Transformer-1 | 5/8 | 6/8 | 0.655 | 0.454 | 7 | 2.05 s | 17.6k |
| Transformer-2 | 5/8 | 6/8 | 0.649 | 0.487 | 10 | 2.72 s | 27.5k |
| Encoder-decoder | 6/8 | 7/8 | 0.709 | 0.286 | 4 | 1.50 s | 7.6k |
| MoE | 8/8 | 8/8 | 0.960 | 0.006 | 4 | 1.97 s | 6.0k |
| Perceiver-like | 5/8 | 7/8 | 0.661 | 0.497 | 6 | 2.13 s | 12.6k |

Small-n warning: this table is useful for failure localization, not architecture ranking.

## Stability on holdout v1

Direct, Transformer-1, encoder-decoder and MoE were run three times with unchanged prompts and the same frozen eight cases.

Across 24 repeated instances per architecture:

| Architecture | Correct | Stable error pattern |
|---|---:|---|
| Direct V3 | 24/24 | none |
| MoE | 24/24 | none |
| Transformer-1 | 15/24 | H03, H06, H07 wrong in all 3 runs |
| Encoder-decoder | 18/24 | H03 and H06 wrong in all 3 runs |

This shows that the Transformer failures were not a one-off stochastic draw.

## Transformer failure pattern

Transformer-1 and Transformer-2 repeatedly failed on quoted/meta policy-sensitive text.

On H03/H06/H07, a local packet sometimes overestimated override, harm or policy conflict. All-to-all self-attention then exposed that packet to every position.

A second Transformer block did not correct this. On H06 it often amplified the error:
- a token packet reached approximately harm 1.8/3 and conflict 1.8/3 despite the request being meta-analysis;
- the second block propagated elevated risk to additional token packets;
- the final full-context readout remained biased toward partial/refusal.

Working description:

> **attention-mediated error broadcast**

The structure is good at making evidence globally available, but it also makes local semantic errors globally available.

## MoE behavior

The sparse MoE used:
1. one full-context router;
2. top-2 selected full-context experts;
3. one final packet readout.

Router behavior on holdout v1 was semantically sensible:
- ordinary safe task -> helpfulness expert
- actual harmful tasks -> risk expert
- quoted/nested override tasks -> semantics expert
- mixed actual override + safe core -> semantics/helpfulness mix

On the first frozen holdout it achieved 8/8, and repeated runs remained 24/24 total.

This does not establish superiority, but it suggests that **conditional specialization may fit Jev better than token-style self-attention**.

## Frozen holdout v2

Hybrid architectures were implemented before v2 was created.

SHA-256:

`92c78ed4dd6dc64a32bb3f72ea5a7094dc3f0a7bdcc04620fab0b2d7f319e087`

### Results

| Architecture | Accuracy | Guarded | Mean expected-label P | Mean Brier | Calls | Critical path | Mean input tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct V3 | 8/8 | 8/8 | 0.820 | 0.115 | 1 | 0.65 s | 1.5k |
| Transformer-1 | 5/8 | 6/8 | 0.630 | 0.494 | 7 | 2.14 s | 17.6k |
| Transformer-2 | 5/8 | 6/8 | 0.625 | 0.557 | 10 | 2.85 s | 27.6k |
| Encoder-decoder | 6/8 | 6/8 | 0.651 | 0.396 | 4 | 1.33 s | 7.6k |
| MoE | 8/8 | 8/8 | 0.934 | 0.019 | 4 | 1.97 s | 6.0k |
| Transformer + MoE | 5/8 | 7/8 | 0.653 | 0.453 | 10 | 3.61 s | 26.3k |
| Transformer + global skip | 7/8 | 7/8 | 0.775 | 0.167 | 8 | 2.85 s | 19.5k |

Again, this is a tiny frozen diagnostic set, not a definitive benchmark.

## Hybrid interpretation

### Transformer + MoE

Adding sparse experts after self-attention did **not** inherit the standalone MoE result.

It failed the same meta/quoted classes as the base Transformer.

By the time routing happened, the self-attention packet sequence already contained systematic semantic distortion. Experts received both raw context and distorted packet evidence, but the repeated packet evidence still influenced readout.

This suggests:

> Specialization after a lossy/bias-amplifying stage may be too late.

### Transformer + global skip

Adding one full-context Jev packet as an explicit semantic skip connection improved the frozen-v2 result from 5/8 to 7/8.

This supports the earlier RNN finding: **raw/global residual information is valuable because packet transformations are not perfectly information-preserving.**

The remaining error was a quoted harmful request (J06), where even the full-context residual did not fully overcome locally amplified safety features.

## Current empirical picture

### Structures that currently look natural for Jev

**MoE**
- conditional computation
- full-context experts
- interpretable routing
- good compute/accuracy tradeoff in these probes

**MLP / dense packet graph**
- works when packet contract is good
- expensive but auditable
- no locality-induced aliasing

**GNN**
- message passing is viable when independent packet channels are preserved
- expensive in tokens

**RNN + external/raw residual memory**
- packet works as controller/state estimate
- raw memory prevents irreversible semantic loss

**Encoder-decoder**
- compact and cheaper than dense/Transformer graphs
- still vulnerable to meta/quotation aliasing in the encoder memory

### Structures that expose problems

**Pure CNN/local pooling**
- local windows can confuse wrapper with substance

**Strict packet-only RNN**
- hidden state capacity too small

**Transformer-style self-attention**
- local errors become globally visible and may be reinforced
- extra depth did not help in these probes

**Perceiver/latent bottleneck**
- compressed latents can retain the same representation/readout mismatch

## Can Jev replace a Transformer?

At the API/computation-graph level, we can build Transformer-shaped Jev networks and they execute correctly.

But the present experiments do **not** support the stronger claim that Jev is a drop-in replacement for token-level Transformer computation.

Reasons:
- Jev operates at semantic-call granularity, not vector/token primitive granularity.
- one Jev node costs hundreds to thousands of tokens and hundreds of milliseconds;
- no weight sharing/backpropagation/training is happening in these experiments;
- the service may itself rely on neural models internally, which is outside this experiment;
- the dominant behavior is typed semantic inference, not learned linear algebra.

The more promising analogy is:

> **Jev as a typed probabilistic instruction/reasoning primitive for an external computation graph.**

In that regime, MoE/router, graph, dense aggregation, residual memory, and deterministic invariants are natural components.

## Strongest working hypothesis

The best current hypothesis is not “Jev should imitate a Transformer.”

It is:

> **A Jev system behaves more like an auditable probabilistic program whose nodes are semantic operators.**

That implies architectures should optimize for:
- information preservation;
- explicit state contracts;
- conditional routing;
- external/residual memory;
- provenance;
- deterministic invariants;
- sparse rather than indiscriminate global communication.

## Next scientifically useful step

Safety classification was useful because it gives crisp labels and adversarial semantic aliases.

A stronger next test would be a **non-safety topology benchmark** containing:
- sequence-state tasks;
- set aggregation;
- local motif detection;
- graph reachability;
- long-range key/value lookup;
- distributed logical composition.

That would test whether the observations above generalize beyond safety/prompt-injection semantics.
