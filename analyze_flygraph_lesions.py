#!/usr/bin/env python3
"""Offline lesion robustness analysis for the frozen 16-node MaleCNS core."""

from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

import networkx as nx

PATH = Path("flygraph_large_controls_v1.json")
OUT = Path("flygraph_large_lesion_analysis.json")
SEED = 20260921
TRIALS = 2000

x = json.loads(PATH.read_text(encoding="utf-8"))
readout = x["readout_node"]


def make_graph(name):
    g = nx.DiGraph()
    g.add_nodes_from(x[name]["nodes"])
    g.add_edges_from(
        (e["source"], e["target"], {"weight": e["weight"]})
        for e in x[name]["edges"]
    )
    return g


def reachable_fraction(g):
    if readout not in g:
        return 0.0
    nodes = list(g.nodes())
    if not nodes:
        return 0.0
    return sum(nx.has_path(g, n, readout) for n in nodes) / len(nodes)


def original_source_reach_fraction(g, original_nodes):
    """Fraction of original non-readout sources that still reach readout.

    Removed nodes count as failures.
    """
    if readout not in g:
        return 0.0
    sources = [n for n in original_nodes if n != readout]
    ok = 0
    for n in sources:
        if n in g and nx.has_path(g, n, readout):
            ok += 1
    return ok / len(sources)


result = {}
for name in ("fly", "rewired", "random"):
    G = make_graph(name)
    nodes = list(G.nodes())
    edges = list(G.edges())
    rng = random.Random(SEED + {"fly": 1, "rewired": 2, "random": 3}[name])

    edge_random = {}
    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        k = round(frac * len(edges))
        vals = []
        for _ in range(TRIALS):
            H = G.copy()
            H.remove_edges_from(rng.sample(edges, k))
            vals.append(original_source_reach_fraction(H, nodes))
        edge_random[str(frac)] = {
            "mean_source_reach": statistics.mean(vals),
            "median": statistics.median(vals),
            "p10": sorted(vals)[int(0.1 * (len(vals) - 1))],
            "p01": sorted(vals)[int(0.01 * (len(vals) - 1))],
            "full_reach_rate": sum(v == 1.0 for v in vals) / len(vals),
        }

    node_random = {}
    removable = [n for n in nodes if n != readout]
    for k in (1, 2, 3, 4, 5):
        vals = []
        for _ in range(TRIALS):
            H = G.copy()
            H.remove_nodes_from(rng.sample(removable, k))
            vals.append(original_source_reach_fraction(H, nodes))
        node_random[str(k)] = {
            "mean_source_reach": statistics.mean(vals),
            "median": statistics.median(vals),
            "p10": sorted(vals)[int(0.1 * (len(vals) - 1))],
            "full_reach_rate": sum(v == 1.0 for v in vals) / len(vals),
        }

    # Targeted edge lesions.
    ordered_high = sorted(edges, key=lambda e: G[e[0]][e[1]]["weight"], reverse=True)
    ordered_low = list(reversed(ordered_high))
    targeted = {}
    for label, ordering in (("high_weight_first", ordered_high), ("low_weight_first", ordered_low)):
        curve = {}
        for k in (1, 3, 5, 10, 15, 20, 30):
            H = G.copy()
            H.remove_edges_from(ordering[: min(k, len(ordering))])
            curve[str(k)] = {
                "source_reach": original_source_reach_fraction(H, nodes),
                "strongly_connected": nx.is_strongly_connected(H) if H.number_of_nodes() > 0 else False,
                "largest_scc": max((len(c) for c in nx.strongly_connected_components(H)), default=0),
            }
        targeted[label] = curve

    # Per-edge damage score: single-edge removal effect.
    edge_damage = []
    for e in edges:
        H = G.copy()
        H.remove_edge(*e)
        loss = 1.0 - original_source_reach_fraction(H, nodes)
        edge_damage.append({
            "source": e[0],
            "target": e[1],
            "weight": G[e[0]][e[1]]["weight"],
            "reach_loss": loss,
        })
    edge_damage.sort(key=lambda z: (-z["reach_loss"], -z["weight"], z["source"], z["target"]))

    result[name] = {
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "edge_random": edge_random,
        "node_random": node_random,
        "targeted": targeted,
        "top_single_edge_damage": edge_damage[:15],
    }

OUT.write_text(json.dumps({
    "graph_file": str(PATH),
    "readout": readout,
    "trials_per_condition": TRIALS,
    "result": result,
}, indent=2), encoding="utf-8")

print("=== RANDOM EDGE LESIONS: mean source reach ===")
for frac in ("0.1", "0.2", "0.3", "0.4", "0.5", "0.6"):
    print(
        frac,
        *(f"{name}={result[name]['edge_random'][frac]['mean_source_reach']:.4f}"
          for name in ("fly", "rewired", "random"))
    )

print("\n=== RANDOM NODE LESIONS: mean source reach ===")
for k in ("1", "2", "3", "4", "5"):
    print(
        k,
        *(f"{name}={result[name]['node_random'][k]['mean_source_reach']:.4f}"
          for name in ("fly", "rewired", "random"))
    )

print("\n=== TARGETED HIGH-WEIGHT EDGE LESIONS ===")
for k in ("1", "3", "5", "10", "15", "20", "30"):
    print(
        k,
        *(f"{name}={result[name]['targeted']['high_weight_first'][k]['source_reach']:.4f}"
          for name in ("fly", "rewired", "random"))
    )

print("\nTop Fly single-edge damage", result["fly"]["top_single_edge_damage"][:8])
print("saved", OUT)
