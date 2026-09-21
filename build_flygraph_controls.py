#!/usr/bin/env python3
"""Build frozen 6-node MaleCNS FlyGraph and topology controls."""

from __future__ import annotations

import json
import random
from pathlib import Path

import networkx as nx

SOURCE = Path("flygraph_pc1_motif_v1.json")
OUT = Path("flygraph_controls_v1.json")
SEED = 20260921
READOUT = "mAL_m8"
THRESHOLD = 250

src = json.loads(SOURCE.read_text(encoding="utf-8"))
nodes = ["pC1_12b", "mAL_m8", "SIP103m", "FLA001m", "SIP122m", "SIP100m"]

G = nx.DiGraph()
G.add_nodes_from(nodes)
for e in src["edges"]:
    if (
        e["source"] in nodes
        and e["target"] in nodes
        and int(e["weight"]) >= THRESHOLD
        and e["source"] != e["target"]
    ):
        G.add_edge(e["source"], e["target"], weight=int(e["weight"]))

assert nx.is_strongly_connected(G)
assert all(nx.shortest_path_length(G, n, READOUT) <= 2 for n in nodes)


def graph_metrics(g: nx.DiGraph):
    return {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "density": nx.density(g),
        "reciprocity": nx.reciprocity(g),
        "strongly_connected": nx.is_strongly_connected(g),
        "diameter": nx.diameter(g),
        "readout": READOUT,
        "max_distance_to_readout": max(nx.shortest_path_length(g, n, READOUT) for n in g.nodes),
        "in_degree_sequence": {n: g.in_degree(n) for n in nodes},
        "out_degree_sequence": {n: g.out_degree(n) for n in nodes},
    }


def serialize(g: nx.DiGraph):
    return {
        "nodes": nodes,
        "edges": [
            {"source": u, "target": v, "weight": int(d.get("weight", 1))}
            for u, v, d in sorted(g.edges(data=True))
        ],
        "metrics": graph_metrics(g),
    }


# Degree-preserving control with exactly the same per-node in/out degrees.
# On this tiny dense graph, repeated directed edge swaps have very few legal moves.
# Directed Havel-Hakimi gives a simple graph satisfying the exact degree constraints.
inseq = [G.in_degree(n) for n in nodes]
outseq = [G.out_degree(n) for n in nodes]
hh = nx.directed_havel_hakimi_graph(inseq, outseq, create_using=nx.DiGraph)
rewired = nx.relabel_nodes(hh, {i: n for i, n in enumerate(nodes)})
if set(rewired.edges()) == set(G.edges()):
    raise RuntimeError("Degree-preserving control unexpectedly identical to FlyGraph")
if not nx.is_strongly_connected(rewired):
    raise RuntimeError("Degree-preserving control is not strongly connected")
if max(nx.shortest_path_length(rewired, n, READOUT) for n in nodes) > 2:
    raise RuntimeError("Degree-preserving control exceeds two-hop readout coverage")

# Preserve biological weight multiset, but randomize which control edge gets which weight.
weights = sorted([d["weight"] for _, _, d in G.edges(data=True)], reverse=True)
rng = random.Random(SEED)
rng.shuffle(weights)
for (u, v), w in zip(sorted(rewired.edges()), weights):
    rewired[u][v]["weight"] = int(w)


# Same N/E random directed graph, constrained to comparable two-hop readout coverage.
random_graph = None
all_pairs = [(u, v) for u in nodes for v in nodes if u != v]
for attempt in range(10000):
    rr = random.Random(SEED * 10 + attempt)
    chosen = rr.sample(all_pairs, G.number_of_edges())
    cand = nx.DiGraph()
    cand.add_nodes_from(nodes)
    cand.add_edges_from(chosen)
    if not nx.is_strongly_connected(cand):
        continue
    if max(nx.shortest_path_length(cand, n, READOUT) for n in nodes) > 2:
        continue
    random_graph = cand
    rweights = weights.copy()
    rr.shuffle(rweights)
    for (u, v), w in zip(sorted(random_graph.edges()), rweights):
        random_graph[u][v]["weight"] = int(w)
    break

if random_graph is None:
    raise RuntimeError("Could not construct random control")

payload = {
    "version": "flygraph-controls-v1",
    "source_dataset": "MaleCNS v1.0",
    "source_level": "official type-level connectivity tables",
    "source_motif": str(SOURCE),
    "threshold": THRESHOLD,
    "readout_node": READOUT,
    "construction_seed": SEED,
    "fly": serialize(G),
    "rewired": serialize(rewired),
    "random": serialize(random_graph),
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

for name in ("fly", "rewired", "random"):
    print("\n", name)
    print(json.dumps(payload[name]["metrics"], indent=2))
    print("edges", [(e["source"], e["target"], e["weight"]) for e in payload[name]["edges"]])
print("\nsaved", OUT)
