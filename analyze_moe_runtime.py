#!/usr/bin/env python3
"""Offline counterfactual: Jev router + deterministic executor.

Uses already-recorded MoE router outputs from frozen non-safety v1/v2.
No API calls.

Question:
If Jev is used only for semantic routing, and exact computation is delegated to
a deterministic runtime, what happens to accuracy and model-token cost?
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import networkx as nx

FILES = [
    ("v1", Path("non_safety_arch_results/raw-nonsafety-arch-zoo-v1.jsonl")),
    ("v2", Path("non_safety_v2_results/raw-nonsafety-v2-arch-confirm-v1.jsonl")),
]

ROUTE_FOR_CATEGORY = {
    "set_majority": "aggregation",
    "set_frequency": "aggregation",
    "arithmetic_modulo": "arithmetic_sequence",
    "sequence_state": "arithmetic_sequence",
    "long_range_key_value": "retrieval",
    "graph_reachability": "graph_logic",
    "distributed_logic": "graph_logic",
    "motif_detection": "graph_logic",
}


def solve(task):
    values = task["slot_values"]
    cat = task["category"]

    if cat == "set_majority":
        c = Counter(values)
        m = max(c.values())
        winners = [k for k, n in c.items() if n == m]
        return winners[0] if len(winners) == 1 else None

    if cat == "set_frequency":
        c = Counter()
        for v in values:
            for s in v.strip("{}").split(","):
                c[s] += 1
        winners = [k for k, n in c.items() if n >= 4]
        return winners[0] if len(winners) == 1 else None

    if cat == "arithmetic_modulo":
        return "M" + str(sum(map(int, values)) % 4)

    if cat == "sequence_state":
        x = 1
        operations = sorted(
            (int(step), op)
            for step, op in (v.split(":", 1) for v in values)
        )
        for _, op in operations:
            if op.startswith("+"):
                x += int(op[1:])
            elif op.startswith("-"):
                x -= int(op[1:])
            elif op.startswith("*"):
                x *= int(op[1:])
            else:
                raise ValueError(op)
        return str(x)

    if cat == "long_range_key_value":
        for v in values:
            k, val = v.split("=", 1)
            if k == "TARGET":
                return val
        return None

    if cat == "graph_reachability":
        g = nx.DiGraph()
        g.add_edges_from(v.split("->") for v in values)
        return "YES" if nx.has_path(g, "A", "E") else "NO"

    if cat == "distributed_logic":
        facts = {v for v in values if "->" not in v}
        rules = [v.split("->") for v in values if "->" in v]
        changed = True
        while changed:
            changed = False
            for a, b in rules:
                if a in facts and b not in facts:
                    facts.add(b)
                    changed = True
        return "YES" if "S" in facts else "NO"

    if cat == "motif_detection":
        g = nx.DiGraph()
        g.add_edges_from(v.split("->") for v in values)
        for a in g:
            for b in g.successors(a):
                for c in g.successors(b):
                    if c != a and g.has_edge(c, a):
                        return "CYCLE"
        return "NO_CYCLE"

    raise ValueError(cat)


rows = []
for version, path in FILES:
    for line in path.read_text(encoding="utf-8").splitlines():
        x = json.loads(line)
        if x["arch"] != "moe":
            continue

        task = x["task"]
        router = x["trace"]["router"]
        route_answer = router["answers"]["route"]
        probs = route_answer["probabilities"]
        top1 = max(probs, key=probs.get)
        expected_route = ROUTE_FOR_CATEGORY[task["category"]]
        det_answer = solve(task)

        router_usage = router.get("usage", {})
        router_in = int(router_usage.get("input_tokens", 0))
        router_out = int(router_usage.get("output_tokens", 0))

        rows.append({
            "version": version,
            "id": task["id"],
            "category": task["category"],
            "expected_route": expected_route,
            "router_top1": top1,
            "route_correct": top1 == expected_route,
            "moe_answer": x["choice"],
            "moe_correct": x["choice"] == task["expected"],
            "det_answer": det_answer,
            "hybrid_correct": det_answer == task["expected"],
            "router_input_tokens": router_in,
            "router_output_tokens": router_out,
            "full_moe_input_tokens": x["input_tokens"],
            "full_moe_output_tokens": x["output_tokens"],
        })

print("=== PER CASE ===")
for r in rows:
    print(
        r["version"], r["id"], f"{r['category']:22s}",
        "route", r["router_top1"],
        "routeOK", r["route_correct"],
        "MoE", r["moe_answer"], r["moe_correct"],
        "hybrid", r["det_answer"], r["hybrid_correct"],
        f"router_tokens={r['router_input_tokens']}+{r['router_output_tokens']}",
        f"full_moe={r['full_moe_input_tokens']}+{r['full_moe_output_tokens']}",
    )

n = len(rows)
route_acc = sum(r["route_correct"] for r in rows) / n
moe_acc = sum(r["moe_correct"] for r in rows) / n
hybrid_acc = sum(r["hybrid_correct"] for r in rows) / n
router_in = sum(r["router_input_tokens"] for r in rows)
router_out = sum(r["router_output_tokens"] for r in rows)
full_in = sum(r["full_moe_input_tokens"] for r in rows)
full_out = sum(r["full_moe_output_tokens"] for r in rows)

summary = {
    "n": n,
    "router_top1_accuracy": route_acc,
    "full_moe_accuracy": moe_acc,
    "router_plus_deterministic_accuracy": hybrid_acc,
    "router_input_tokens_total": router_in,
    "router_output_tokens_total": router_out,
    "full_moe_input_tokens_total": full_in,
    "full_moe_output_tokens_total": full_out,
    "input_token_reduction_fraction": 1 - router_in / full_in,
    "output_token_reduction_fraction": 1 - router_out / full_out,
}

print("\n=== SUMMARY ===")
print(json.dumps(summary, indent=2))
Path("moe_router_runtime_analysis.json").write_text(
    json.dumps({"summary": summary, "rows": rows}, indent=2),
    encoding="utf-8",
)
