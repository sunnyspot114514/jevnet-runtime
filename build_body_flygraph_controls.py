#!/usr/bin/env python3
"""Freeze controls for the 16-body MaleCNS core."""

from __future__ import annotations

import json
import random
from pathlib import Path

import networkx as nx

SOURCE = Path("flygraph_body_pc1_v1.json")
OUT = Path("flygraph_body_controls_v1.json")
SEED = 20260921

src = json.loads(SOURCE.read_text(encoding="utf-8"))
nodes = [int(n["bodyId"]) for n in src["nodes"]]
readout = int(src["readout_body"])

G = nx.DiGraph()
G.add_nodes_from(nodes)
for e in src["edges"]:
    G.add_edge(int(e["source"]), int(e["target"]), weight=int(e["weight"]))

assert nx.is_strongly_connected(G)

def metrics(g):
    dists = [nx.shortest_path_length(g, n, readout) for n in g]
    return {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "density": nx.density(g),
        "reciprocity": nx.reciprocity(g),
        "strongly_connected": nx.is_strongly_connected(g),
        "diameter": nx.diameter(g),
        "readout": readout,
        "max_distance_to_readout": max(dists),
        "mean_distance_to_readout": sum(dists) / len(dists),
        "in_degree_sequence": {str(n): g.in_degree(n) for n in nodes},
        "out_degree_sequence": {str(n): g.out_degree(n) for n in nodes},
    }

def serialize(g):
    return {
        "nodes": nodes,
        "edges": [
            {"source": int(u), "target": int(v), "weight": int(d.get("weight", 1))}
            for u, v, d in sorted(g.edges(data=True))
        ],
        "metrics": metrics(g),
    }

# Exact per-node in/out degree control.
inseq = [G.in_degree(n) for n in nodes]
outseq = [G.out_degree(n) for n in nodes]
hh = nx.directed_havel_hakimi_graph(inseq, outseq, create_using=nx.DiGraph)
rewired = nx.relabel_nodes(hh, {i: n for i, n in enumerate(nodes)})

if not nx.is_strongly_connected(rewired):
    # Try degree-preserving directed swaps from the real graph.
    rewired = None
    for attempt in range(200):
        C = G.copy()
        try:
            nx.directed_edge_swap(
                C,
                nswap=min(30, max(3, G.number_of_edges() // 2)),
                max_tries=20000,
                seed=SEED + attempt,
            )
        except Exception:
            continue
        if nx.is_strongly_connected(C) and set(C.edges()) != set(G.edges()):
            rewired = C
            break
    if rewired is None:
        raise RuntimeError("Could not create strongly connected degree control")

weights = [d["weight"] for _, _, d in G.edges(data=True)]
rng = random.Random(SEED)
rw = weights.copy()
rng.shuffle(rw)
for (u, v), w in zip(sorted(rewired.edges()), rw):
    rewired[u][v]["weight"] = int(w)

# Same-N/E random control, constrained to strong connectivity and max readout distance within +/-1.
fly_max = metrics(G)["max_distance_to_readout"]
all_pairs = [(u, v) for u in nodes for v in nodes if u != v]
random_graph = None
for attempt in range(30000):
    rr = random.Random(SEED * 100 + attempt)
    chosen = rr.sample(all_pairs, G.number_of_edges())
    R = nx.DiGraph()
    R.add_nodes_from(nodes)
    R.add_edges_from(chosen)
    if not nx.is_strongly_connected(R):
        continue
    max_to = max(nx.shortest_path_length(R, n, readout) for n in nodes)
    if abs(max_to - fly_max) > 1:
        continue
    random_graph = R
    rweights = weights.copy()
    rr.shuffle(rweights)
    for (u, v), w in zip(sorted(R.edges()), rweights):
        R[u][v]["weight"] = int(w)
    break

if random_graph is None:
    raise RuntimeError("Could not create random control")

payload = {
    "version": "male-cns-body-controls-v1",
    "source": str(SOURCE),
    "source_sha256": "2399a3977ac282e8bdf324e16d332d5317bab2106194ad117f02bbaf6c9be0d6",
    "dataset": src["dataset"],
    "seed_body": src["seed_body"],
    "readout_body": readout,
    "construction_seed": SEED,
    "fly": serialize(G),
    "rewired": serialize(rewired),
    "random": serialize(random_graph),
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

for name in ("fly", "rewired", "random"):
    print("\n", name)
    print(json.dumps(payload[name]["metrics"], indent=2))
print("saved", OUT)
