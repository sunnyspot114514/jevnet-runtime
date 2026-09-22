#!/usr/bin/env python3
"""Runtime-gated body-level Jev transport.

Key distinction:
- Jev outputs are PROPOSALS with soft probabilities.
- The runtime maintains a canonical set of authorized fact IDs.
- Only facts already present locally/self/incoming are authorized.
- Only proposed facts with p>=0.5 may be committed.
- Previously committed facts are monotonic and cannot be forgotten.

Thus weak soft probabilities do not become provenance.
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
RUN_ID = "flygraph-body-transport-gated-v1"
VARIANTS = ("fly", "rewired", "random")
ROUNDS = 5
THRESHOLD = 0.5


def sha256(path):
    return frozen_text_sha256(path)


if sha256(GRAPH_PATH) != GRAPH_SHA256:
    raise SystemExit("body graph controls hash mismatch")

graphs = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
nodes = graphs["fly"]["nodes"]
N = len(nodes)

QUESTIONS = {
    f"fact_{i}": {
        "type": "noul",
        "instructions": (
            f"Should source fact {i} be proposed as PRESENT given ONLY the explicit canonical "
            "self_present_facts and incoming_present_facts in state? A fact ID not listed anywhere "
            "in those canonical sets has no provenance and must be false."
        ),
        "criteria": {
            "true": f"fact {i} appears in at least one canonical authorized fact set.",
            "false": f"fact {i} appears in none of the canonical authorized fact sets.",
        },
    }
    for i in range(1, N + 1)
}


def ptrue(pkt, i):
    return float(pkt[f"fact_{i}"].get("noul", 0.0))


def run_variant(api_key, variant):
    graph = graphs[variant]
    readout = graphs["readout_body"]
    incoming = {n: [] for n in nodes}
    weights = {}
    for e in graph["edges"]:
        incoming[e["target"]].append(e["source"])
        weights[(e["source"], e["target"])] = e["weight"]

    fact_for_node = {node: i + 1 for i, node in enumerate(nodes)}

    # Canonical runtime state starts exact, no model needed.
    current = {node: {fact_for_node[node]} for node in nodes}
    responses = []
    times = []
    t0 = time.perf_counter()

    round_stats = [{
        "round": 0,
        "readout_facts": sorted(current[readout]),
        "readout_count": len(current[readout]),
        "proposed_false_positive_count": 0,
        "blocked_false_positive_count": 0,
        "authorized_but_not_proposed_count": 0,
    }]

    for round_idx in range(1, ROUNDS + 1):
        previous = {n: set(v) for n, v in current.items()}

        def update(node):
            pred_sets = {p: sorted(previous[p]) for p in incoming[node]}
            authorized = set(previous[node])
            for vals in pred_sets.values():
                authorized.update(vals)

            state = {
                "node_scope": "runtime_gated_fact_proposal",
                "graph_variant": variant,
                "round": round_idx,
                "node_id": node,
                "self_present_facts": sorted(previous[node]),
                "incoming_present_facts": pred_sets,
                "incoming_edge_weights": {str(p): weights[(p, node)] for p in incoming[node]},
                "contract_note": (
                    "Canonical fact lists are the only provenance. Propose every authorized fact as present, "
                    "and every non-authorized fact as absent. Soft probability is a proposal, not provenance."
                ),
            }
            resp, ms = post_jev(api_key, state, QUESTIONS, retries=4, timeout=60)
            pkt = resp["answers"]
            proposed = {i for i in range(1, N + 1) if ptrue(pkt, i) >= THRESHOLD}

            false_proposals = proposed - authorized
            missed_authorized = authorized - proposed

            # Runtime validation + canonical commit.
            committed = set(previous[node])
            committed.update(proposed & authorized)

            return node, resp, ms, committed, authorized, proposed, false_proposals, missed_authorized

        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            rows = list(ex.map(update, nodes))

        current = {node: committed for node, _, _, committed, _, _, _, _ in rows}
        responses.extend(resp for _, resp, _, _, _, _, _, _ in rows)
        times.extend(ms for _, _, ms, _, _, _, _, _ in rows)

        false_count = sum(len(fp) for _, _, _, _, _, _, fp, _ in rows)
        missed_count = sum(len(miss) for _, _, _, _, _, _, _, miss in rows)

        round_stats.append({
            "round": round_idx,
            "readout_facts": sorted(current[readout]),
            "readout_count": len(current[readout]),
            "proposed_false_positive_count": false_count,
            "blocked_false_positive_count": false_count,
            "authorized_but_not_proposed_count": missed_count,
        })

    wall = (time.perf_counter() - t0) * 1000
    total_in = total_out = 0
    for r in responses:
        i, o = usage_tokens(r)
        total_in += i
        total_out += o

    return {
        "variant": variant,
        "readout": readout,
        "rounds": round_stats,
        "final_count": len(current[readout]),
        "final_facts": sorted(current[readout]),
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
        raise SystemExit("gated transport run exists; refusing replay")

    all_rows = []
    with raw.open("w", encoding="utf-8") as f:
        results = []
        for idx, variant in enumerate(VARIANTS, 1):
            res = run_variant(api_key, variant)
            results.append(res)
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            f.flush()

            print(
                f"[{idx}/3] {variant:7s} final={res['final_count']}/{N} "
                f"ms={res['critical_path_ms']:.0f} input={res['input_tokens']}"
            )
            for rr in res["rounds"]:
                print(
                    " round", rr["round"],
                    "readout", rr["readout_count"],
                    "false_proposals", rr["proposed_false_positive_count"],
                    "missed_authorized", rr["authorized_but_not_proposed_count"],
                )
                all_rows.append({
                    "variant": variant,
                    "round": rr["round"],
                    "readout_count": rr["readout_count"],
                    "false_proposals": rr["proposed_false_positive_count"],
                    "missed_authorized": rr["authorized_but_not_proposed_count"],
                })

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)

    meta.write_text(json.dumps({
        "run_id": RUN_ID,
        "graph_sha256": GRAPH_SHA256,
        "threshold": THRESHOLD,
        "rounds": ROUNDS,
        "runtime_rule": "commit iff proposed>=threshold AND authorized by canonical self/incoming provenance; previous commits monotonic",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
