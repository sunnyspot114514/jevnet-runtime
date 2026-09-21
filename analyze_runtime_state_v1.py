#!/usr/bin/env python3
"""Offline semantic-safety analysis for runtime_state_v1.

A candidate final state is "reachable" if the deterministic reducer can produce
it from some subset of the oracle event stream, preserving original order.

This distinguishes:
- exact: all valid events processed to expected final state
- reachable_incomplete: consistent with omitting some events (fail-closed/no-progress)
- unreachable_invalid: cannot be produced by the runtime semantics from any oracle subset
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import runtime_state_runner as rr

RAW = Path("runtime_state_results/raw-runtime-state-v1.jsonl")
cases = {c["id"]: c for c in rr.load_benchmark()}


RELEVANT_FIELDS = {
    "conflict_write": {"event_type", "key", "value", "version", "writer"},
    "revocation": {"event_type", "key", "value", "version", "writer"},
    "staleness": {"event_type", "key", "value", "version", "writer", "event_time"},
    "transaction": {"event_type", "key", "value", "txid", "expected_version"},
}


def oracle_proposals(case):
    out = []
    for e in case["oracle_events"]:
        p = {}
        for field in [
            "event_type", "key", "value", "version", "writer",
            "txid", "event_time", "expected_version"
        ]:
            v = e.get(field)
            p[field] = "NONE" if v is None else str(v)
        out.append(p)
    return out


def canonical_json(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def subset_reachable_states(case):
    props = oracle_proposals(case)
    reducer = rr.REDUCERS[case["family"]]
    states = {}
    n = len(props)
    for mask in range(1 << n):
        sub = [props[i] for i in range(n) if mask & (1 << i)]
        state = reducer(case, sub)
        key = canonical_json(state)
        states.setdefault(key, []).append([i + 1 for i in range(n) if mask & (1 << i)])
    return states


def effective_parser_accuracy(case, proposals):
    rel = RELEVANT_FIELDS[case["family"]]
    total = correct = 0
    per = {f: [0, 0] for f in sorted(rel)}
    for pred, gold in zip(proposals, case["oracle_events"]):
        for field in rel:
            gv = "NONE" if gold.get(field) is None else str(gold.get(field))
            pv = pred.get(field) or "NONE"
            ok = int(gv == pv)
            total += 1
            correct += ok
            per[field][0] += ok
            per[field][1] += 1
    return correct / total, {f: a / b for f, (a, b) in per.items()}


records = [json.loads(x) for x in RAW.read_text(encoding="utf-8").splitlines() if x.strip()]
summary = {"direct": {"exact": 0, "reachable_incomplete": 0, "unreachable_invalid": 0},
           "gated": {"exact": 0, "reachable_incomplete": 0, "unreachable_invalid": 0}}

print("=== FINAL STATE CLASSIFICATION ===")
for rec in records:
    case = rec["case"]
    result = rec["result"]
    pipeline = rec["pipeline"]
    reachable = subset_reachable_states(case)

    if pipeline == "direct":
        label = result["choice"]
        state = case["candidate_states"].get(label)
    else:
        state = result["final_state"]

    state_key = canonical_json(state)
    expected = case["candidate_states"][case["expected_label"]]

    if state == expected:
        cls = "exact"
    elif state_key in reachable:
        cls = "reachable_incomplete"
    else:
        cls = "unreachable_invalid"

    summary[pipeline][cls] += 1
    witnesses = reachable.get(state_key, [])[:3]
    print(
        case["id"], f"{pipeline:6s}", f"{cls:20s}",
        "choice", result["choice"],
        "subset_witnesses", witnesses,
    )

    if pipeline == "gated":
        eff, per = effective_parser_accuracy(case, result["proposals"])
        print("  parser operational accuracy", round(eff, 4), per)

print("\nSUMMARY")
print(json.dumps(summary, indent=2))
