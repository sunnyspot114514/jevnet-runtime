#!/usr/bin/env python3
"""Extract a body-level MaleCNS motif from the public neuPrint API."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import requests

DATASET = "male-cns:v1.0"
API = "https://neuprint.janelia.org/api/custom/custom"
SEED_BODY = 13562
TOP_EACH_DIRECTION = 20
TARGET_N = 16
OUT = Path("flygraph_body_pc1_v1.json")


def query(cypher: str):
    r = requests.post(API, json={"dataset": DATASET, "cypher": cypher}, timeout=60)
    r.raise_for_status()
    x = r.json()
    return x["columns"], x["data"]


def rows_as_dicts(columns, data):
    return [dict(zip(columns, row)) for row in data]


# Seed metadata.
cols, data = query(
    f"MATCH (n:Neuron) WHERE n.bodyId={SEED_BODY} "
    "RETURN n.bodyId AS bodyId, n.type AS type, n.instance AS instance"
)
seed_meta = rows_as_dicts(cols, data)[0]

# Strongest outgoing/incoming body-level partners.
q_out = (
    "MATCH (n:Neuron)-[e:ConnectsTo]->(m:Neuron) "
    f"WHERE n.bodyId={SEED_BODY} "
    "RETURN m.bodyId AS bodyId, m.type AS type, m.instance AS instance, "
    "e.weight AS weight ORDER BY e.weight DESC "
    f"LIMIT {TOP_EACH_DIRECTION}"
)
q_in = (
    "MATCH (m:Neuron)-[e:ConnectsTo]->(n:Neuron) "
    f"WHERE n.bodyId={SEED_BODY} "
    "RETURN m.bodyId AS bodyId, m.type AS type, m.instance AS instance, "
    "e.weight AS weight ORDER BY e.weight DESC "
    f"LIMIT {TOP_EACH_DIRECTION}"
)
co, do = query(q_out)
ci, di = query(q_in)
out_rows = rows_as_dicts(co, do)
in_rows = rows_as_dicts(ci, di)

meta = {int(seed_meta["bodyId"]): seed_meta}
for row in out_rows + in_rows:
    meta[int(row["bodyId"])] = {
        "bodyId": int(row["bodyId"]),
        "type": row.get("type"),
        "instance": row.get("instance"),
    }

candidates = sorted(meta)
id_list = "[" + ",".join(map(str, candidates)) + "]"

# Induced edges among candidate bodies.
qe = (
    "MATCH (a:Neuron)-[e:ConnectsTo]->(b:Neuron) "
    f"WHERE a.bodyId IN {id_list} AND b.bodyId IN {id_list} "
    "RETURN a.bodyId AS source, b.bodyId AS target, e.weight AS weight "
    "ORDER BY e.weight DESC"
)
ce, de = query(qe)
edge_rows = rows_as_dicts(ce, de)

G = nx.DiGraph()
G.add_nodes_from(candidates)
for row in edge_rows:
    u, v, w = int(row["source"]), int(row["target"]), int(row["weight"])
    if u != v:
        G.add_edge(u, v, weight=w)


def metrics(g):
    weak = sorted((len(c) for c in nx.weakly_connected_components(g)), reverse=True)
    strong = sorted((len(c) for c in nx.strongly_connected_components(g)), reverse=True)
    return {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "density": nx.density(g),
        "reciprocity": nx.reciprocity(g) if g.number_of_edges() else None,
        "largest_wcc": weak[0] if weak else 0,
        "largest_scc": strong[0] if strong else 0,
        "strongly_connected": nx.is_strongly_connected(g) if g.number_of_nodes() else False,
        "total_weight": int(sum(d["weight"] for _, _, d in g.edges(data=True))),
    }


threshold_metrics = {}
threshold_graphs = {}
for threshold in (1, 2, 3, 5, 8, 10, 12, 15, 20):
    T = nx.DiGraph()
    T.add_nodes_from(candidates)
    T.add_edges_from(
        (u, v, d)
        for u, v, d in G.edges(data=True)
        if int(d["weight"]) >= threshold
    )
    threshold_metrics[str(threshold)] = metrics(T)
    threshold_graphs[threshold] = T

# Choose the sparsest threshold whose largest SCC still contains at least TARGET_N nodes.
viable = [
    t for t, g in threshold_graphs.items()
    if max((len(c) for c in nx.strongly_connected_components(g)), default=0) >= TARGET_N
]
if not viable:
    raise RuntimeError("No threshold retains a 16-node SCC")
chosen_threshold = max(viable)
T = threshold_graphs[chosen_threshold]
largest_scc = max(nx.strongly_connected_components(T), key=len)
H = T.subgraph(largest_scc).copy()

# Greedily reduce to TARGET_N while preserving SCC and seed if seed belongs to SCC.
if SEED_BODY not in H:
    raise RuntimeError("Seed body dropped out of largest SCC at chosen threshold")

while H.number_of_nodes() > TARGET_N:
    scores = {}
    for n in H:
        scores[n] = sum(d["weight"] for _, _, d in H.in_edges(n, data=True))
        scores[n] += sum(d["weight"] for _, _, d in H.out_edges(n, data=True))

    removed = False
    for n, _ in sorted(scores.items(), key=lambda kv: (kv[1], kv[0])):
        if n == SEED_BODY:
            continue
        C = H.copy()
        C.remove_node(n)
        if nx.is_strongly_connected(C):
            H = C
            removed = True
            break
    if not removed:
        raise RuntimeError("Could not reduce body-level SCC to target size")

# Choose a readout minimizing inbound eccentricity then mean distance.
readout_scores = {}
for target in H.nodes:
    dists = [nx.shortest_path_length(H, source, target) for source in H.nodes]
    readout_scores[target] = (max(dists), sum(dists) / len(dists))
readout = min(H.nodes, key=lambda n: (readout_scores[n][0], readout_scores[n][1], n))

payload = {
    "version": "male-cns-body-pc1-v1",
    "dataset": DATASET,
    "api": API,
    "seed_body": SEED_BODY,
    "seed_metadata": seed_meta,
    "top_each_direction": TOP_EACH_DIRECTION,
    "candidate_count": len(candidates),
    "candidate_bodies": [
        {
            "bodyId": int(b),
            "type": meta[b].get("type"),
            "instance": meta[b].get("instance"),
        }
        for b in candidates
    ],
    "full_candidate_metrics": metrics(G),
    "threshold_metrics": threshold_metrics,
    "chosen_threshold": chosen_threshold,
    "core_metrics": metrics(H),
    "readout_body": int(readout),
    "readout_metadata": meta[int(readout)],
    "readout_score": {
        "max_inbound_distance": readout_scores[readout][0],
        "mean_inbound_distance": readout_scores[readout][1],
    },
    "nodes": [
        {
            "bodyId": int(n),
            "type": meta[int(n)].get("type"),
            "instance": meta[int(n)].get("instance"),
            "in_degree": H.in_degree(n),
            "out_degree": H.out_degree(n),
        }
        for n in sorted(H.nodes)
    ],
    "edges": [
        {
            "source": int(u),
            "target": int(v),
            "weight": int(d["weight"]),
        }
        for u, v, d in sorted(H.edges(data=True))
    ],
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

print("seed", seed_meta)
print("candidate_count", len(candidates))
print("full_candidate", json.dumps(payload["full_candidate_metrics"], indent=2))
print("thresholds")
for th, m in threshold_metrics.items():
    print(th, m)
print("\nchosen_threshold", chosen_threshold)
print("core", json.dumps(payload["core_metrics"], indent=2))
print("readout", payload["readout_body"], payload["readout_metadata"], payload["readout_score"])
print("nodes")
for n in payload["nodes"]:
    print(n)
print("saved", OUT)
