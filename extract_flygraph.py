#!/usr/bin/env python3
"""Extract a small real type-level MaleCNS motif from official static connectivity tables."""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from collections import defaultdict
from pathlib import Path

import networkx as nx
import requests

BASE = "https://male-cns.janelia.org/build/tables"
SEED = "pC1_12b"
OUT = Path("flygraph_pc1_motif_v1.json")
CACHE = Path("flygraph_cache")
CACHE.mkdir(exist_ok=True)


def parse_table_html(text: str):
    key = '"data_json": '
    start = text.index(key) + len(key)
    val, _ = json.JSONDecoder().raw_decode(text[start:])
    return json.loads(val)


def fetch_rows(name: str):
    safe = urllib.parse.quote(name, safe="")
    cache = CACHE / f"{safe}_connections.html"
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
    else:
        url = f"{BASE}/{safe}_connections.html"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        text = r.text
        cache.write_text(text, encoding="utf-8")
    return parse_table_html(text)


def simple_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.+-]+", name))


seed_rows = fetch_rows(SEED)
ranked = sorted(seed_rows, key=lambda r: int(r[2]), reverse=True)

# Balanced strongest upstream/downstream partners around the seed.
candidates = [SEED]
seen = {SEED}
for direction in ("post", "pre"):
    count = 0
    for row in ranked:
        partner, rel, weight = row[0], row[1], int(row[2])
        if rel != direction or not simple_name(partner) or partner in seen:
            continue
        try:
            fetch_rows(partner)
        except Exception:
            continue
        candidates.append(partner)
        seen.add(partner)
        count += 1
        if count >= 10:
            break

# Build candidate induced graph from official tables.
edges = {}
for focal in candidates:
    try:
        rows = fetch_rows(focal)
    except Exception:
        continue
    for row in rows:
        partner, rel, weight = row[0], row[1], int(row[2])
        if partner not in seen or partner == focal:
            continue
        if rel == "post":
            u, v = focal, partner
        elif rel == "pre":
            u, v = partner, focal
        else:
            continue
        # Same type-level edge can appear from both endpoints; keep max identical evidence.
        edges[(u, v)] = max(edges.get((u, v), 0), weight)

G = nx.DiGraph()
G.add_nodes_from(candidates)
for (u, v), w in edges.items():
    G.add_edge(u, v, weight=w)

# Select seed + 11 nodes with largest internal weighted degree, retaining both directions.
scores = {}
for n in G.nodes:
    score = sum(d["weight"] for _, _, d in G.in_edges(n, data=True))
    score += sum(d["weight"] for _, _, d in G.out_edges(n, data=True))
    scores[n] = score

selected = [SEED] + [
    n for n, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if n != SEED
][:11]
H = G.subgraph(selected).copy()

# Basic topology metrics.
sccs = sorted((len(c) for c in nx.strongly_connected_components(H)), reverse=True)
weak = sorted((len(c) for c in nx.weakly_connected_components(H)), reverse=True)
weighted_in = {n: int(sum(d["weight"] for _, _, d in H.in_edges(n, data=True))) for n in H}
weighted_out = {n: int(sum(d["weight"] for _, _, d in H.out_edges(n, data=True))) for n in H}

payload = {
    "dataset": "MaleCNS v1.0",
    "level": "type-level connectivity from official MaleCNS static tables",
    "seed": SEED,
    "nodes": [
        {
            "id": n,
            "weighted_in": weighted_in[n],
            "weighted_out": weighted_out[n],
            "in_degree": H.in_degree(n),
            "out_degree": H.out_degree(n),
        }
        for n in selected
    ],
    "edges": [
        {"source": u, "target": v, "weight": int(d["weight"])}
        for u, v, d in sorted(H.edges(data=True))
    ],
    "metrics": {
        "n_nodes": H.number_of_nodes(),
        "n_edges": H.number_of_edges(),
        "density": nx.density(H),
        "reciprocity": nx.reciprocity(H),
        "largest_scc": sccs[0] if sccs else 0,
        "largest_weak_component": weak[0] if weak else 0,
        "total_synaptic_weight": int(sum(d["weight"] for _, _, d in H.edges(data=True))),
    },
    "candidate_nodes": candidates,
    "source_template": f"{BASE}/<type>_connections.html",
}

OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(json.dumps(payload["metrics"], indent=2))
print("nodes", selected)
print("edges")
for e in sorted(payload["edges"], key=lambda x: -x["weight"]):
    print(f"{e['source']:16s} -> {e['target']:16s} w={e['weight']}")
print("saved", OUT)
