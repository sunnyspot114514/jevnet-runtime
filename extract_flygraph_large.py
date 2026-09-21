#!/usr/bin/env python3
"""Extract and freeze a larger real MaleCNS type-level motif.

The graph is built only from official MaleCNS static connectivity tables.
No Jev/API calls are involved.

Strategy:
- seed: pC1_12b
- fetch strongest 16 pre and 16 post partner types that have official tables
- reconstruct the induced type-level weighted graph from official tables
- keep the seed plus 23 nodes with highest internal weighted degree
- report thresholded topology at several biological-weight cutoffs
"""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

import networkx as nx
import requests

BASE = "https://male-cns.janelia.org/build/tables"
SEED = "pC1_12b"
CACHE = Path("flygraph_cache")
OUT = Path("flygraph_pc1_large_v1.json")
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
        return parse_table_html(cache.read_text(encoding="utf-8"))
    url = f"{BASE}/{safe}_connections.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    cache.write_text(r.text, encoding="utf-8")
    return parse_table_html(r.text)


def simple_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.+-]+", name))


seed_rows = sorted(fetch_rows(SEED), key=lambda r: int(r[2]), reverse=True)

candidates = [SEED]
seen = {SEED}
for direction in ("post", "pre"):
    count = 0
    for row in seed_rows:
        partner, rel = row[0], row[1]
        if rel != direction or partner in seen or not simple_name(partner):
            continue
        try:
            fetch_rows(partner)
        except Exception:
            continue
        candidates.append(partner)
        seen.add(partner)
        count += 1
        if count >= 16:
            break

print("candidate_count", len(candidates))

edges = {}
for i, focal in enumerate(candidates, 1):
    rows = fetch_rows(focal)
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
        edges[(u, v)] = max(edges.get((u, v), 0), weight)
    print(f"[{i:02d}/{len(candidates)}] {focal} induced_edges_so_far={len(edges)}")

G = nx.DiGraph()
G.add_nodes_from(candidates)
for (u, v), w in edges.items():
    G.add_edge(u, v, weight=w)

weighted_degree = {}
for n in G:
    weighted_degree[n] = sum(d["weight"] for _, _, d in G.in_edges(n, data=True))
    weighted_degree[n] += sum(d["weight"] for _, _, d in G.out_edges(n, data=True))

selected = [SEED] + [
    n for n, _ in sorted(weighted_degree.items(), key=lambda kv: (-kv[1], kv[0]))
    if n != SEED
][:23]

H = G.subgraph(selected).copy()


def metrics(g: nx.DiGraph):
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


thresholds = {}
for threshold in (25, 50, 100, 150, 200, 250, 300, 400, 500):
    T = nx.DiGraph()
    T.add_nodes_from(selected)
    T.add_edges_from(
        (u, v, d)
        for u, v, d in H.edges(data=True)
        if int(d["weight"]) >= threshold
    )
    thresholds[str(threshold)] = metrics(T)

payload = {
    "version": "male-cns-pc1-large-v1",
    "dataset": "MaleCNS v1.0",
    "level": "official type-level static connectivity tables",
    "seed": SEED,
    "candidate_count": len(candidates),
    "candidate_nodes": candidates,
    "selection": "seed + 23 types with highest internal weighted degree in candidate induced graph",
    "nodes": [
        {
            "id": n,
            "weighted_degree": int(weighted_degree[n]),
            "in_degree_full": H.in_degree(n),
            "out_degree_full": H.out_degree(n),
        }
        for n in selected
    ],
    "edges": [
        {"source": u, "target": v, "weight": int(d["weight"])}
        for u, v, d in sorted(H.edges(data=True))
    ],
    "full_metrics": metrics(H),
    "threshold_metrics": thresholds,
    "source_template": f"{BASE}/<type>_connections.html",
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

print("\nselected_nodes", selected)
print("\nfull", json.dumps(payload["full_metrics"], indent=2))
print("\nthresholds")
for th, m in thresholds.items():
    print(th, m)
print("\nsaved", OUT)
