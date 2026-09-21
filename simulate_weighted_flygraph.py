#!/usr/bin/env python3
"""Monte Carlo weighted transport on the frozen 16-node MaleCNS core.

No Jev/API calls.

Each non-readout source starts with a unique fact. The readout starts with its own
fact. For 3 synchronous rounds, each directed edge independently opens with

    p = 1 - exp(-weight / tau)

and, if open, transmits all currently-known facts at its source.

Compare:
- Fly topology + real MaleCNS weights
- Fly topology + shuffled biological weights
- degree-preserving control
- random control

The Fly-weight-shuffled condition is averaged over multiple fixed weight shuffles.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from pathlib import Path

import networkx as nx

PATH = Path("flygraph_large_controls_v1.json")
OUT = Path("flygraph_weighted_transport_sim.json")
SEED = 20260921
ROUNDS = 3
TRIALS = 5000
N_WEIGHT_SHUFFLES = 40
TAUS = (100, 200, 400, 800, 1200, 1600, 2400)

x = json.loads(PATH.read_text(encoding="utf-8"))
readout = x["readout_node"]
nodes = x["fly"]["nodes"]


def build_graph(name):
    g = nx.DiGraph()
    g.add_nodes_from(x[name]["nodes"])
    for e in x[name]["edges"]:
        g.add_edge(e["source"], e["target"], weight=float(e["weight"]))
    return g


def simulate(g, tau, trials, rng):
    sources = list(g.nodes())
    # fact identity == source node
    edge_list = [(u, v, float(d["weight"])) for u, v, d in g.edges(data=True)]
    fractions = []
    full = 0

    for _ in range(trials):
        known = {n: {n} for n in sources}
        for _round in range(ROUNDS):
            prev = {n: set(vals) for n, vals in known.items()}
            updated = {n: set(vals) for n, vals in prev.items()}
            for u, v, w in edge_list:
                p = 1.0 - math.exp(-w / tau)
                if rng.random() < p:
                    updated[v].update(prev[u])
            known = updated
        frac = len(known[readout]) / len(sources)
        fractions.append(frac)
        full += len(known[readout]) == len(sources)

    vals = sorted(fractions)
    return {
        "mean_fact_recall": statistics.mean(vals),
        "median_fact_recall": statistics.median(vals),
        "p10": vals[int(0.10 * (len(vals) - 1))],
        "p01": vals[int(0.01 * (len(vals) - 1))],
        "full_recall_rate": full / trials,
    }


fly = build_graph("fly")
rewired = build_graph("rewired")
random_graph = build_graph("random")
bio_weights = [d["weight"] for _, _, d in fly.edges(data=True)]

result = {
    "rounds": ROUNDS,
    "trials_per_condition": TRIALS,
    "weight_shuffles": N_WEIGHT_SHUFFLES,
    "taus": list(TAUS),
    "readout": readout,
    "conditions": {},
}

for tau in TAUS:
    print("\ntau", tau)
    tau_result = {}

    for name, g in (("fly_real", fly), ("rewired", rewired), ("random", random_graph)):
        rng = random.Random(SEED + tau * 100 + {"fly_real": 1, "rewired": 2, "random": 3}[name])
        stats = simulate(g, tau, TRIALS, rng)
        tau_result[name] = stats
        print(name, stats)

    # Same Fly topology; only reassign the biological weight multiset.
    shuffle_means = []
    shuffle_full = []
    shuffle_records = []
    edges_sorted = sorted(fly.edges())
    for s in range(N_WEIGHT_SHUFFLES):
        rr = random.Random(SEED * 1000 + tau * 10 + s)
        weights = bio_weights.copy()
        rr.shuffle(weights)
        sg = nx.DiGraph()
        sg.add_nodes_from(nodes)
        for (u, v), w in zip(edges_sorted, weights):
            sg.add_edge(u, v, weight=w)
        stats = simulate(
            sg,
            tau,
            max(500, TRIALS // 5),
            random.Random(SEED * 100000 + tau * 100 + s),
        )
        shuffle_records.append(stats)
        shuffle_means.append(stats["mean_fact_recall"])
        shuffle_full.append(stats["full_recall_rate"])

    tau_result["fly_weight_shuffled"] = {
        "mean_fact_recall_over_shuffles": statistics.mean(shuffle_means),
        "std_fact_recall_over_shuffles": statistics.pstdev(shuffle_means),
        "min_shuffle_mean": min(shuffle_means),
        "max_shuffle_mean": max(shuffle_means),
        "mean_full_recall_rate": statistics.mean(shuffle_full),
        "real_minus_shuffle_mean": (
            tau_result["fly_real"]["mean_fact_recall"] - statistics.mean(shuffle_means)
        ),
    }
    print("fly_weight_shuffled", tau_result["fly_weight_shuffled"])
    result["conditions"][str(tau)] = tau_result

OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

print("\n=== REAL FLY MINUS SHUFFLED WEIGHT MEAN ===")
for tau in TAUS:
    d = result["conditions"][str(tau)]["fly_weight_shuffled"]
    print(tau, f"{d['real_minus_shuffle_mean']:+.5f}")

print("\nsaved", OUT)
