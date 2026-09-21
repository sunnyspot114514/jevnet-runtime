#!/usr/bin/env python3
"""Build a frozen 16-node strongly-connected MaleCNS core and controls."""

from __future__ import annotations

import json
import random
from pathlib import Path

import networkx as nx

SOURCE = Path("flygraph_pc1_large_v1.json")
OUT = Path("flygraph_large_controls_v1.json")
THRESHOLD = 100
TARGET_N = 16
SEED = 20260921

src = json.loads(SOURCE.read_text(encoding="utf-8"))
G = nx.DiGraph()
for n in src["nodes"]:
    G.add_node(n["id"])
for e in src["edges"]:
    if int(e["weight"]) >= THRESHOLD:
        G.add_edge(e["source"], e["target"], weight=int(e["weight"]))

scc = max(nx.strongly_connected_components(G), key=len)
H = G.subgraph(scc).copy()
print("threshold_scc", H.number_of_nodes(), H.number_of_edges())

# Greedily remove the least internally weighted node as long as strong connectivity remains.
while H.number_of_nodes() > TARGET_N:
    scores = {}
    for n in H:
        scores[n] = sum(d["weight"] for _, _, d in H.in_edges(n, data=True))
        scores[n] += sum(d["weight"] for _, _, d in H.out_edges(n, data=True))
    removed = False
    for n, _ in sorted(scores.items(), key=lambda kv: (kv[1], kv[0])):
        C = H.copy()
        C.remove_node(n)
        if nx.is_strongly_connected(C):
            H = C
            print("removed", n, "remaining", H.number_of_nodes())
            removed = True
            break
    if not removed:
        raise RuntimeError("Could not reduce SCC while preserving strong connectivity")

nodes = sorted(H.nodes())

# Choose readout minimizing worst-case inbound distance, then mean inbound distance.
readout_scores = {}
for target in nodes:
    dists = [nx.shortest_path_length(H, src_node, target) for src_node in nodes]
    readout_scores[target] = (max(dists), sum(dists) / len(dists))
READOUT = min(nodes, key=lambda n: (readout_scores[n][0], readout_scores[n][1], n))

weights = [d["weight"] for _, _, d in H.edges(data=True)]

def metrics(g: nx.DiGraph):
    max_to = max(nx.shortest_path_length(g, n, READOUT) for n in g)
    mean_to = sum(nx.shortest_path_length(g, n, READOUT) for n in g) / g.number_of_nodes()
    return {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "density": nx.density(g),
        "reciprocity": nx.reciprocity(g),
        "strongly_connected": nx.is_strongly_connected(g),
        "diameter": nx.diameter(g),
        "readout": READOUT,
        "max_distance_to_readout": max_to,
        "mean_distance_to_readout": mean_to,
        "in_degree_sequence": {n: g.in_degree(n) for n in nodes},
        "out_degree_sequence": {n: g.out_degree(n) for n in nodes},
    }

def serialize(g):
    return {
        "nodes": nodes,
        "edges": [
            {"source": u, "target": v, "weight": int(d.get("weight", 1))}
            for u, v, d in sorted(g.edges(data=True))
        ],
        "metrics": metrics(g),
    }

# Degree-preserving Havel-Hakimi control.
inseq = [H.in_degree(n) for n in nodes]
outseq = [H.out_degree(n) for n in nodes]
hh = nx.directed_havel_hakimi_graph(inseq, outseq, create_using=nx.DiGraph)
rewired = nx.relabel_nodes(hh, {i: n for i, n in enumerate(nodes)})

# If HH isn't strongly connected or readout reachability is poor, try relabel permutations.
# Relabeling preserves abstract degree sequence but changes which biological label has which role;
# we require the exact per-node degree map, so only accept identity labeling first.
if not nx.is_strongly_connected(rewired):
    raise RuntimeError("Havel-Hakimi control is not strongly connected")
if max(nx.shortest_path_length(rewired, n, READOUT) for n in nodes) > metrics(H)["max_distance_to_readout"] + 1:
    print("warning: rewired readout distance is larger than FlyGraph")

rng = random.Random(SEED)
rw = weights.copy()
rng.shuffle(rw)
for (u, v), w in zip(sorted(rewired.edges()), rw):
    rewired[u][v]["weight"] = int(w)

# Random same-N/E control, matched to strong connectivity and approximately matched readout max distance.
all_pairs = [(u, v) for u in nodes for v in nodes if u != v]
random_graph = None
fly_max = metrics(H)["max_distance_to_readout"]
for attempt in range(20000):
    rr = random.Random(SEED * 100 + attempt)
    chosen = rr.sample(all_pairs, H.number_of_edges())
    R = nx.DiGraph()
    R.add_nodes_from(nodes)
    R.add_edges_from(chosen)
    if not nx.is_strongly_connected(R):
        continue
    max_to = max(nx.shortest_path_length(R, n, READOUT) for n in nodes)
    if abs(max_to - fly_max) > 1:
        continue
    random_graph = R
    rweights = weights.copy()
    rr.shuffle(rweights)
    for (u, v), w in zip(sorted(random_graph.edges()), rweights):
        random_graph[u][v]["weight"] = int(w)
    break

if random_graph is None:
    raise RuntimeError("Could not construct random control")

payload = {
    "version": "flygraph-large-controls-v1",
    "dataset": "MaleCNS v1.0",
    "source": str(SOURCE),
    "threshold": THRESHOLD,
    "selection": "largest SCC at threshold, greedily reduced to 16 while preserving strong connectivity",
    "readout_selection": "minimize maximum inbound shortest-path distance, then mean inbound distance",
    "readout_node": READOUT,
    "construction_seed": SEED,
    "fly": serialize(H),
    "rewired": serialize(rewired),
    "random": serialize(random_graph),
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

for name in ("fly", "rewired", "random"):
    print("\n", name)
    print(json.dumps(payload[name]["metrics"], indent=2))
print("\nreadout_scores_top")
for n in sorted(nodes, key=lambda n: readout_scores[n])[:8]:
    print(n, readout_scores[n])
print("\nsaved", OUT)
