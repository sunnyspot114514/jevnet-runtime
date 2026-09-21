#!/usr/bin/env python3
"""16-node MaleCNS large-core Jev fact-transport probe.

Pure monotonic transport:
- 12 source facts placed on 12 nodes that are <=2 hops from the fixed readout
  in FlyGraph, degree-preserving control, and random control.
- 4 remaining nodes carry no source fact.
- 2 synchronous message-passing rounds.
- packet contains only 12 NOUL fact-presence channels.
- no task-answer head, arithmetic, or safety semantics.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jevnet_experiment import post_jev, usage_tokens

GRAPH_PATH = Path("flygraph_large_controls_v1.json")
GRAPH_SHA256 = "db39bb7941fd170a0c87cde3d410b1aa26350c0a630662c4e9e924183e2e9149"
RUN_ID = "flygraph-large-transport-v1"
VARIANTS = ("fly", "rewired", "random")
ROUNDS = 2
N_FACTS = 12

ELIGIBLE_SOURCES = [
    "AN08B020",
    "AVLP711m",
    "AVLP721m",
    "FLA001m",
    "LH006m",
    "SIP100m",
    "SIP103m",
    "SIP122m",
    "VES022",
    "mAL_m1",
    "mAL_m5b",
    "mAL_m8",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_graphs():
    if sha256(GRAPH_PATH) != GRAPH_SHA256:
        raise SystemExit("large graph control hash mismatch")
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


QUESTIONS = {
    f"fact_{i}": {
        "type": "noul",
        "instructions": (
            f"Is logical source fact {i} supported as PRESENT by the accessible evidence? "
            "Evidence may come from local_fact_id, self_previous_packet, or incoming_packets. "
            "This is a monotonic provenance-preserving OR operation: once a fact has real support "
            "it should remain present. Never mark a fact present merely because other fact IDs are present."
        ),
        "criteria": {
            "true": f"Accessible evidence contains real provenance for fact {i}.",
            "false": f"No accessible evidence contains provenance for fact {i}.",
        },
    }
    for i in range(1, N_FACTS + 1)
}


def ptrue(packet, i):
    ans = packet[f"fact_{i}"]
    return float(ans.get("noul", 0.0))


def run_one(api_key, graphs, variant, mapping_shift):
    graph = graphs[variant]
    nodes = graph["nodes"]
    readout = graphs["readout_node"]

    incoming = {n: [] for n in nodes}
    weights = {}
    for e in graph["edges"]:
        incoming[e["target"]].append(e["source"])
        weights[(e["source"], e["target"])] = e["weight"]

    # cyclic shift logical fact IDs over the same 12 eligible physical sources
    source_fact = {}
    for idx, node in enumerate(ELIGIBLE_SOURCES):
        source_fact[node] = ((idx + mapping_shift) % N_FACTS) + 1

    responses = []
    call_times = []
    t0 = time.perf_counter()

    def init_node(node):
        state = {
            "node_scope": "large_graph_fact_init",
            "graph_variant": variant,
            "node_id": node,
            "local_fact_id": source_fact.get(node),
            "contract_note": (
                "At initialization only local_fact_id, if non-null, is genuinely present. "
                "All other facts must be false."
            ),
        }
        resp, ms = post_jev(api_key, state, QUESTIONS, retries=4, timeout=60)
        return node, resp, ms

    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        init_rows = list(ex.map(init_node, nodes))
    current = {n: r["answers"] for n, r, _ in init_rows}
    responses.extend(r for _, r, _ in init_rows)
    call_times.extend(ms for _, _, ms in init_rows)
    traces = [{"round": 0, "nodes": {n: r for n, r, _ in init_rows}}]

    for round_idx in range(1, ROUNDS + 1):
        previous = current

        def update(node):
            preds = incoming[node]
            state = {
                "node_scope": "large_graph_fact_update",
                "graph_variant": variant,
                "round": round_idx,
                "node_id": node,
                "self_previous_packet": previous[node],
                "incoming_packets": {p: previous[p] for p in preds},
                "incoming_edge_weights": {p: weights[(p, node)] for p in preds},
                "contract_note": (
                    "Perform monotonic fact-wise OR by provenance. Preserve a fact if self or any incoming "
                    "packet provides real support. Edge weights are metadata and do not change truth. "
                    "Do not infer one fact from another fact."
                ),
            }
            resp, ms = post_jev(api_key, state, QUESTIONS, retries=4, timeout=60)
            return node, resp, ms

        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            rows = list(ex.map(update, nodes))
        current = {n: r["answers"] for n, r, _ in rows}
        responses.extend(r for _, r, _ in rows)
        call_times.extend(ms for _, _, ms in rows)
        traces.append({"round": round_idx, "nodes": {n: r for n, r, _ in rows}})

    wall = (time.perf_counter() - t0) * 1000
    out = current[readout]
    probs = [ptrue(out, i) for i in range(1, N_FACTS + 1)]
    recovered = sum(p >= 0.5 for p in probs)
    strong = sum(p >= 0.8 for p in probs)
    mean_p = statistics.mean(probs)
    min_p = min(probs)

    total_in = total_out = 0
    for resp in responses:
        i, o = usage_tokens(resp)
        total_in += i
        total_out += o

    return {
        "variant": variant,
        "mapping_shift": mapping_shift,
        "source_fact": source_fact,
        "readout": readout,
        "probabilities": probs,
        "recovered_at_0_5": recovered,
        "strong_at_0_8": strong,
        "mean_probability": mean_p,
        "min_probability": min_p,
        "critical_path_ms": wall,
        "sum_call_ms": sum(call_times),
        "calls": len(responses),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "trace": traces,
    }


def main():
    graphs = load_graphs()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("flygraph_large_transport_results")
    outdir.mkdir(exist_ok=True)
    raw = outdir / f"raw-{RUN_ID}.jsonl"
    csvp = outdir / f"summary-{RUN_ID}.csv"
    meta = outdir / f"meta-{RUN_ID}.json"
    if any(p.exists() for p in (raw, csvp, meta)):
        raise SystemExit("large transport run exists; refusing replay")

    items = [(variant, shift) for shift in (0, 4) for variant in VARIANTS]
    rows = []
    with raw.open("w", encoding="utf-8") as f:
        for idx, (variant, shift) in enumerate(items, 1):
            result = run_one(api_key, graphs, variant, shift)
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            f.flush()
            row = {
                "variant": variant,
                "mapping_shift": shift,
                "recovered_at_0_5": result["recovered_at_0_5"],
                "strong_at_0_8": result["strong_at_0_8"],
                "mean_probability": result["mean_probability"],
                "min_probability": result["min_probability"],
                "calls": result["calls"],
                "critical_path_ms": round(result["critical_path_ms"], 1),
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
            rows.append(row)
            print(
                f"[{idx:02d}/{len(items)}] shift={shift} {variant:7s} "
                f"recall={result['recovered_at_0_5']}/12 strong={result['strong_at_0_8']}/12 "
                f"meanP={result['mean_probability']:.3f} minP={result['min_probability']:.3f} "
                f"ms={result['critical_path_ms']:.0f} input={result['input_tokens']}"
            )

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for variant in VARIANTS:
        rs = [r for r in rows if r["variant"] == variant]
        summary[variant] = {
            "mean_recovered_at_0_5": statistics.mean(r["recovered_at_0_5"] for r in rs),
            "mean_strong_at_0_8": statistics.mean(r["strong_at_0_8"] for r in rs),
            "mean_probability": statistics.mean(r["mean_probability"] for r in rs),
            "mean_min_probability": statistics.mean(r["min_probability"] for r in rs),
            "mean_calls": statistics.mean(r["calls"] for r in rs),
            "mean_critical_path_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
        }

    meta.write_text(json.dumps({
        "run_id": RUN_ID,
        "graph_sha256": GRAPH_SHA256,
        "rounds": ROUNDS,
        "n_facts": N_FACTS,
        "eligible_sources": ELIGIBLE_SOURCES,
        "mapping_shifts": [0, 4],
        "summary": summary,
    }, indent=2), encoding="utf-8")

    print("\n=== LARGE GRAPH TRANSPORT SUMMARY ===")
    for v, s in summary.items():
        print(
            f"{v:7s} recovered={s['mean_recovered_at_0_5']:.2f}/12 "
            f"strong={s['mean_strong_at_0_8']:.2f}/12 meanP={s['mean_probability']:.3f} "
            f"minP={s['mean_min_probability']:.3f} ms={s['mean_critical_path_ms']:.0f}"
        )


if __name__ == "__main__":
    main()
