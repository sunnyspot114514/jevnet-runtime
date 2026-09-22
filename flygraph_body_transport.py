#!/usr/bin/env python3
"""Pure Jev fact transport on the frozen 16-body MaleCNS graph and controls.

Every physical body owns one unique fact. Packet = 16 independent NOUL channels.
Five synchronous rounds are used so that every source can reach the fixed
biological readout in Fly, exact-degree, and random controls.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from artifact_integrity import frozen_text_sha256

from jevnet_experiment import post_jev, usage_tokens

GRAPH_PATH = Path("flygraph_body_controls_v1.json")
GRAPH_SHA256 = "acedf9820fb7e51d927b024f40cdcdc4f86f43a80cbdd234b7a00e4f478cf861"
RUN_ID = "flygraph-body-transport-v1"
ROUNDS = 5
VARIANTS = ("fly", "rewired", "random")


def sha256(path):
    return frozen_text_sha256(path)


def load_graphs():
    if sha256(GRAPH_PATH) != GRAPH_SHA256:
        raise SystemExit("body graph controls hash mismatch")
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


graphs = load_graphs()
N_FACTS = len(graphs["fly"]["nodes"])
NODES = graphs["fly"]["nodes"]

QUESTIONS = {
    f"fact_{i+1}": {
        "type": "noul",
        "instructions": (
            f"Is source fact {i+1} genuinely supported as PRESENT by local_fact_id, "
            "self_previous_packet, or incoming_packets? Apply monotonic provenance-preserving OR. "
            "Never infer one source fact from another."
        ),
        "criteria": {
            "true": f"Real provenance for source fact {i+1} is accessible.",
            "false": f"No provenance for source fact {i+1} is accessible.",
        },
    }
    for i in range(N_FACTS)
}


def ptrue(pkt, i):
    return float(pkt[f"fact_{i}"].get("noul", 0.0))


def run_variant(api_key, variant):
    graph = graphs[variant]
    nodes = graph["nodes"]
    readout = graphs["readout_body"]
    incoming = {n: [] for n in nodes}
    weight = {}
    for e in graph["edges"]:
        incoming[e["target"]].append(e["source"])
        weight[(e["source"], e["target"])] = e["weight"]

    fact_for_node = {node: i + 1 for i, node in enumerate(nodes)}
    responses = []
    times = []
    t0 = time.perf_counter()

    def init_node(node):
        state = {
            "node_scope": "body_fact_init",
            "graph_variant": variant,
            "body_id": node,
            "local_fact_id": fact_for_node[node],
            "contract_note": "Exactly one local fact is present at initialization; all other facts are absent.",
        }
        r, ms = post_jev(api_key, state, QUESTIONS, retries=4, timeout=60)
        return node, r, ms

    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        init_rows = list(ex.map(init_node, nodes))
    current = {n: r["answers"] for n, r, _ in init_rows}
    responses.extend(r for _, r, _ in init_rows)
    times.extend(ms for _, _, ms in init_rows)

    round_summary = []
    for round_idx in range(0, ROUNDS + 1):
        rp = current[readout]
        probs = [ptrue(rp, i) for i in range(1, N_FACTS + 1)]
        round_summary.append({
            "round": round_idx,
            "recovered_0_5": sum(p >= 0.5 for p in probs),
            "strong_0_8": sum(p >= 0.8 for p in probs),
            "mean_p": statistics.mean(probs),
            "min_p": min(probs),
            "probabilities": probs,
        })
        if round_idx == ROUNDS:
            break

        previous = current

        def update(node):
            preds = incoming[node]
            state = {
                "node_scope": "body_fact_update",
                "graph_variant": variant,
                "round": round_idx + 1,
                "body_id": node,
                "self_previous_packet": previous[node],
                "incoming_packets": {p: previous[p] for p in preds},
                "incoming_edge_weights": {str(p): weight[(p, node)] for p in preds},
                "contract_note": (
                    "Perform monotonic fact-wise OR by provenance. Facts must never be forgotten once supported. "
                    "Weights are metadata only and do not alter truth."
                ),
            }
            r, ms = post_jev(api_key, state, QUESTIONS, retries=4, timeout=60)
            return node, r, ms

        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            rows = list(ex.map(update, nodes))
        current = {n: r["answers"] for n, r, _ in rows}
        responses.extend(r for _, r, _ in rows)
        times.extend(ms for _, _, ms in rows)

    wall = (time.perf_counter() - t0) * 1000
    total_in = total_out = 0
    for r in responses:
        i, o = usage_tokens(r)
        total_in += i
        total_out += o

    return {
        "variant": variant,
        "readout": readout,
        "rounds": round_summary,
        "calls": len(responses),
        "critical_path_ms": wall,
        "sum_call_ms": sum(times),
        "input_tokens": total_in,
        "output_tokens": total_out,
    }


def main():
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("flygraph_body_transport_results")
    outdir.mkdir(exist_ok=True)
    raw = outdir / f"raw-{RUN_ID}.jsonl"
    csvp = outdir / f"summary-{RUN_ID}.csv"
    meta = outdir / f"meta-{RUN_ID}.json"
    if any(p.exists() for p in (raw, csvp, meta)):
        raise SystemExit("body transport run exists; refusing replay")

    rows = []
    with raw.open("w", encoding="utf-8") as f:
        for idx, variant in enumerate(VARIANTS, 1):
            res = run_variant(api_key, variant)
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()
            for rr in res["rounds"]:
                rows.append({
                    "variant": variant,
                    "round": rr["round"],
                    "recovered_0_5": rr["recovered_0_5"],
                    "strong_0_8": rr["strong_0_8"],
                    "mean_p": rr["mean_p"],
                    "min_p": rr["min_p"],
                    "critical_path_ms_total": round(res["critical_path_ms"], 1),
                    "input_tokens_total": res["input_tokens"],
                })
            final = res["rounds"][-1]
            print(
                f"[{idx}/3] {variant:7s} final={final['recovered_0_5']}/{N_FACTS} "
                f"strong={final['strong_0_8']}/{N_FACTS} meanP={final['mean_p']:.3f} "
                f"minP={final['min_p']:.3f} ms={res['critical_path_ms']:.0f} "
                f"input={res['input_tokens']}"
            )
            print(" rounds", [
                (r["round"], r["recovered_0_5"], round(r["mean_p"], 3))
                for r in res["rounds"]
            ])

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for variant in VARIANTS:
        rs = [r for r in rows if r["variant"] == variant]
        summary[variant] = {
            "round_curve": [
                {
                    "round": r["round"],
                    "recovered_0_5": r["recovered_0_5"],
                    "strong_0_8": r["strong_0_8"],
                    "mean_p": r["mean_p"],
                    "min_p": r["min_p"],
                }
                for r in rs
            ]
        }

    meta.write_text(json.dumps({
        "run_id": RUN_ID,
        "graph_sha256": GRAPH_SHA256,
        "n_facts": N_FACTS,
        "rounds": ROUNDS,
        "summary": summary,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
