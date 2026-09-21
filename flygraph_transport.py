#!/usr/bin/env python3
"""Balanced six-permutation fact-transport test over FlyGraph controls.

Each logical slot is mapped to each physical graph node exactly once across six
cyclic permutations. This removes the single-assignment confound from the
non-safety benchmark. Primary endpoint: logical slot recall at mAL_m8 after two
message-passing rounds.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import time
from pathlib import Path

import flygraph_benchmark as fb

RUN_ID = "flygraph-transport-balanced-v1"
VARIANTS = ("fly", "rewired", "random")

BASE_TASK = {
    "id": "TRANSPORT",
    "category": "fact_transport",
    "question": (
        "Have all six unique logical source tokens been recovered at this node? "
        "Choose COMPLETE only if every logical slot 1 through 6 is known exactly."
    ),
    "slot_options": ["TOK_A", "TOK_B", "TOK_C", "TOK_D", "TOK_E", "TOK_F"],
    "slot_values": ["TOK_A", "TOK_B", "TOK_C", "TOK_D", "TOK_E", "TOK_F"],
    "answer_options": {
        "COMPLETE": "All six logical source tokens are known exactly.",
        "INCOMPLETE": "At least one logical source token is still missing or uncertain."
    },
    "expected": "COMPLETE"
}


def main():
    graphs = fb.load_graphs()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY is not set.")

    outdir = Path("flygraph_transport_results")
    outdir.mkdir(exist_ok=True)
    raw_path = outdir / f"raw-{RUN_ID}.jsonl"
    csv_path = outdir / f"summary-{RUN_ID}.csv"
    meta_path = outdir / f"meta-{RUN_ID}.json"
    if any(p.exists() for p in (raw_path, csv_path, meta_path)):
        raise SystemExit("Balanced transport run already exists; refusing replay.")

    items = []
    for shift in range(6):
        # physical node position i receives logical slot ((i+shift) mod 6)+1
        order = [((i + shift) % 6) + 1 for i in range(6)]
        task = dict(BASE_TASK)
        task["id"] = f"T{shift}"
        task["node_slot_order"] = order
        for variant in VARIANTS:
            items.append((shift, order, task, variant))

    rows = []
    with raw_path.open("w", encoding="utf-8") as rawf:
        for idx, (shift, order, task, variant) in enumerate(items, 1):
            result = fb.graph_run(api_key, task, variant, graphs, retries=4, timeout=60)
            rawf.write(json.dumps({
                "shift": shift,
                "node_slot_order": order,
                "variant": variant,
                "result": result,
            }, ensure_ascii=False) + "\n")
            rawf.flush()
            row = {
                "shift": shift,
                "variant": variant,
                "node_slot_order": json.dumps(order),
                "choice": result["choice"],
                "complete": int(result["choice"] == "COMPLETE"),
                "slot_accuracy": result["slot_accuracy"],
                "slot_known": result["slot_known"],
                "decision_ready": result["decision_ready"],
                "critical_path_ms": round(result["critical_path_ms"], 1),
                "input_tokens": result["input_tokens"],
            }
            rows.append(row)
            print(
                f"[{idx:02d}/{len(items)}] shift={shift} {variant:7s} "
                f"slots={result['slot_known']}/6 acc={result['slot_accuracy']:.2f} "
                f"head={result['choice']} ready={result['decision_ready']:.2f} "
                f"ms={result['critical_path_ms']:.0f}"
            )

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for variant in VARIANTS:
        rs = [r for r in rows if r["variant"] == variant]
        summary[variant] = {
            "mean_slot_accuracy": statistics.mean(r["slot_accuracy"] for r in rs),
            "mean_slots_known": statistics.mean(r["slot_known"] for r in rs),
            "complete_head_rate": statistics.mean(r["complete"] for r in rs),
            "mean_decision_ready": statistics.mean(r["decision_ready"] for r in rs),
            "mean_critical_path_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
        }

    meta = {
        "run_id": RUN_ID,
        "graph_sha256": fb.GRAPH_SHA256,
        "rounds": fb.ROUNDS,
        "permutations": 6,
        "balanced_property": "each logical slot maps to each physical node exactly once",
        "summary": summary,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("\n=== BALANCED TRANSPORT SUMMARY ===")
    for v, s in summary.items():
        print(
            f"{v:7s} slotacc={s['mean_slot_accuracy']:.3f} "
            f"known={s['mean_slots_known']:.2f}/6 complete={s['complete_head_rate']:.3f} "
            f"ready={s['mean_decision_ready']:.3f} ms={s['mean_critical_path_ms']:.0f}"
        )


if __name__ == "__main__":
    main()
