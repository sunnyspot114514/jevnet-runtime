#!/usr/bin/env python3
"""Offline analysis of frozen FlyGraph non-safety benchmark results."""

from __future__ import annotations

import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

GRAPH_FILE = Path("flygraph_controls_v1.json")
BENCH_FILE = Path("non_safety_benchmark_v1.json")
RUN_FILES = {
    "direct": Path("flygraph_benchmark_results/raw-nonsafety-direct-fly-v1.jsonl"),
    "rewired": Path("flygraph_benchmark_results/raw-nonsafety-rewired-v1.jsonl"),
    "random": Path("flygraph_benchmark_results/raw-nonsafety-random-v1.jsonl"),
}

graphs = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
tasks = {t["id"]: t for t in json.loads(BENCH_FILE.read_text(encoding="utf-8"))}
nodes = graphs["fly"]["nodes"]
readout = graphs["readout_node"]


def choice(ans):
    if "choice" in ans:
        return ans["choice"]
    probs = ans.get("probabilities", {})
    return max(probs, key=probs.get) if probs else None


def final_packet(record):
    if record["variant"] == "direct":
        return record["trace"]["final"]["answers"]
    return record["trace"]["readout_packet"]


def observed_slots(record):
    p = final_packet(record)
    return [choice(p[f"slot_{i}"]) for i in range(1, 7)]


def solve(task, values):
    cat = task["category"]

    if cat == "set_majority":
        c = Counter(values)
        if not c:
            return None
        best = max(c.values())
        winners = [k for k, v in c.items() if v == best]
        return winners[0] if len(winners) == 1 else None

    if cat == "arithmetic_modulo":
        return "M" + str(sum(int(v) for v in values) % 4)

    if cat == "long_range_key_value":
        for v in values:
            k, val = v.split("=", 1)
            if k == "TARGET":
                return val
        return None

    if cat == "sequence_state":
        ops = []
        for v in values:
            step, op = v.split(":", 1)
            ops.append((int(step), op))
        x = 1
        for _, op in sorted(ops):
            if op.startswith("+"):
                x += int(op[1:])
            elif op.startswith("-"):
                x -= int(op[1:])
            elif op.startswith("*"):
                x *= int(op[1:])
            else:
                return None
        return str(x)

    if cat == "graph_reachability":
        g = nx.DiGraph()
        for v in values:
            a, b = v.split("->")
            g.add_edge(a, b)
        return "YES" if nx.has_path(g, "A", "E") else "NO"

    if cat == "distributed_logic":
        facts = set()
        rules = []
        for v in values:
            if "->" in v:
                a, b = v.split("->")
                rules.append((a, b))
            else:
                facts.add(v)
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
        for v in values:
            a, b = v.split("->")
            g.add_edge(a, b)
        for a in g.nodes:
            for b in g.successors(a):
                for c in g.successors(b):
                    if c != a and g.has_edge(c, a):
                        return "CYCLE"
        return "NO_CYCLE"

    if cat == "set_frequency":
        counts = Counter()
        for v in values:
            inner = v.strip("{}")
            for symbol in inner.split(","):
                counts[symbol] += 1
        winners = [k for k, n in counts.items() if n >= 4]
        return winners[0] if len(winners) == 1 else None

    raise ValueError(cat)


def possible_world_decode(task, slots):
    """Return answer if every completion of UNKNOWN slots agrees."""
    domains = []
    for s in slots:
        if s is None or s == "UNKNOWN":
            domains.append(task["slot_options"])
        else:
            domains.append([s])
    answers = set()
    for vals in itertools.product(*domains):
        ans = solve(task, list(vals))
        answers.add(ans)
        if len(answers) > 1:
            return "UNKNOWN"
    ans = next(iter(answers))
    return ans if ans is not None else "UNKNOWN"


# Validate benchmark oracle.
for t in tasks.values():
    oracle = solve(t, t["slot_values"])
    assert oracle == t["expected"], (t["id"], oracle, t["expected"])

records = []
for path in RUN_FILES.values():
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

print("=== OFFLINE DETERMINISTIC READOUT ===")
by_variant = defaultdict(list)
for r in records:
    task = tasks[r["task"]["id"]]
    slots = observed_slots(r)
    decoded = possible_world_decode(task, slots)
    true = task["slot_values"]
    correct_slots = sum(s == v for s, v in zip(slots, true))
    unknown_slots = sum(s == "UNKNOWN" for s in slots)
    wrong_slots = 6 - correct_slots - unknown_slots
    by_variant[r["variant"]].append({
        "id": task["id"],
        "expected": task["expected"],
        "jev": r["choice"],
        "decoded": decoded,
        "correct_slots": correct_slots,
        "unknown_slots": unknown_slots,
        "wrong_slots": wrong_slots,
        "slots": slots,
    })

for variant in ("direct", "fly", "rewired", "random"):
    rs = by_variant[variant]
    if not rs:
        continue
    jev_acc = sum(x["jev"] == x["expected"] for x in rs) / len(rs)
    det_acc = sum(x["decoded"] == x["expected"] for x in rs) / len(rs)
    mean_correct = sum(x["correct_slots"] for x in rs) / len(rs)
    mean_unknown = sum(x["unknown_slots"] for x in rs) / len(rs)
    mean_wrong = sum(x["wrong_slots"] for x in rs) / len(rs)
    print(
        f"{variant:7s} jev_acc={jev_acc:.3f} deterministic_acc={det_acc:.3f} "
        f"correct_slots={mean_correct:.2f}/6 unknown={mean_unknown:.2f} wrong={mean_wrong:.2f}"
    )
    for x in rs:
        print(
            f"  {x['id']} jev={x['jev']:8s} det={x['decoded']:8s} exp={x['expected']:8s} "
            f"slots={x['correct_slots']}C/{x['unknown_slots']}U/{x['wrong_slots']}W {x['slots']}"
        )

print("\n=== SLOT TRANSPORT BY SOURCE NODE ===")
for variant in ("fly", "rewired", "random"):
    g = nx.DiGraph()
    g.add_nodes_from(graphs[variant]["nodes"])
    g.add_edges_from((e["source"], e["target"]) for e in graphs[variant]["edges"])
    rs = by_variant[variant]
    print("\n", variant)
    for i, node in enumerate(nodes):
        hits = sum(x["slots"][i] == tasks[x["id"]]["slot_values"][i] for x in rs)
        unknown = sum(x["slots"][i] == "UNKNOWN" for x in rs)
        wrong = len(rs) - hits - unknown
        dist = nx.shortest_path_length(g, node, readout)
        paths = 0
        for p in nx.all_simple_paths(g, node, readout, cutoff=2):
            if len(p) - 1 <= 2:
                paths += 1
        print(
            f"slot{i+1} {node:10s} dist={dist} paths<=2={paths} "
            f"correct={hits}/{len(rs)} unknown={unknown} wrong={wrong}"
        )
