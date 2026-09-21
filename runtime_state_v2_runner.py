#!/usr/bin/env python3
"""Confirmatory runtime-state benchmark v2 runner.

Created before runtime_state_benchmark_v2.json.

Pipelines:
- direct: Jev directly selects final canonical state.
- hybrid_gated: deterministic metadata extraction + Jev event-type classification
  + deterministic reducer.
- structured_receipt: oracle structured receipts directly into deterministic reducer
  (zero-model runtime reference; represents machine-native event sources).

The reducer logic is unchanged from frozen v1.
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
from typing import Any

import runtime_state_runner as base
import runtime_state_hybrid_parser as hybrid
from jevnet_experiment import usage_tokens

BENCH_PATH = Path("runtime_state_benchmark_v2.json")
BENCH_SHA256 = "cf3d5e8eaf3d421bb31bad05ea936e7ff0daf36feb16ff979ac3d115157abf96"
RUN_ID = "runtime-state-v2"
PIPELINES = ("direct", "hybrid_gated", "structured_receipt")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_benchmark():
    if BENCH_SHA256 == "__TO_BE_FROZEN__":
        raise SystemExit("benchmark v2 hash not frozen")
    if sha256(BENCH_PATH) != BENCH_SHA256:
        raise SystemExit("runtime_state_benchmark_v2 hash mismatch")
    cases = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
    base.validate_benchmark(cases)
    return cases


def oracle_proposals(case):
    out = []
    for e in case["oracle_events"]:
        p = {}
        for field in [
            "event_type", "key", "value", "version", "writer",
            "txid", "event_time", "expected_version",
        ]:
            v = e.get(field)
            p[field] = "NONE" if v is None else str(v)
        out.append(p)
    return out


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def reachable_states(case):
    props = oracle_proposals(case)
    reducer = base.REDUCERS[case["family"]]
    states = set()
    for mask in range(1 << len(props)):
        sub = [props[i] for i in range(len(props)) if mask & (1 << i)]
        states.add(canonical(reducer(case, sub)))
    return states


def state_class(case, state):
    expected = case["candidate_states"][case["expected_label"]]
    if state == expected:
        return "exact"
    if canonical(state) in reachable_states(case):
        return "reachable_incomplete"
    return "unreachable_invalid"


def direct_state(case, result):
    return case["candidate_states"].get(result["choice"])


def run_hybrid(api_key, case):
    t0 = time.perf_counter()

    def work(text):
        fields = hybrid.deterministic_fields(case, text)
        et, resp, ms = hybrid.classify_event_type(api_key, case, text)
        return {"event_type": et, **fields}, resp, ms

    with ThreadPoolExecutor(max_workers=len(case["events"])) as ex:
        parsed = list(ex.map(work, case["events"]))

    proposals = [p for p, _, _ in parsed]
    responses = [r for _, r, _ in parsed]
    final_state = base.REDUCERS[case["family"]](case, proposals)
    label = base.state_to_label(case, final_state)
    wall = (time.perf_counter() - t0) * 1000

    inp = out = 0
    for r in responses:
        i, o = usage_tokens(r)
        inp += i
        out += o

    return {
        "choice": label,
        "correct": int(label == case["expected_label"]),
        "final_state": final_state,
        "proposals": proposals,
        "operational_parser_accuracy": hybrid.operational_accuracy(case, proposals),
        "calls": len(responses),
        "critical_path_ms": wall,
        "input_tokens": inp,
        "output_tokens": out,
    }


def run_structured(case):
    t0 = time.perf_counter()
    props = oracle_proposals(case)
    final_state = base.REDUCERS[case["family"]](case, props)
    label = base.state_to_label(case, final_state)
    return {
        "choice": label,
        "correct": int(label == case["expected_label"]),
        "final_state": final_state,
        "calls": 0,
        "critical_path_ms": (time.perf_counter() - t0) * 1000,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def main():
    cases = load_benchmark()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("runtime_state_v2_results")
    outdir.mkdir(exist_ok=True)
    raw = outdir / f"raw-{RUN_ID}.jsonl"
    csvp = outdir / f"summary-{RUN_ID}.csv"
    meta = outdir / f"meta-{RUN_ID}.json"
    if any(p.exists() for p in (raw, csvp, meta)):
        raise SystemExit("runtime v2 run exists; refusing replay")

    items = [(case, pipeline) for case in cases for pipeline in PIPELINES]
    rows = []
    with raw.open("w", encoding="utf-8") as f:
        for idx, (case, pipeline) in enumerate(items, 1):
            if pipeline == "direct":
                result = base.run_direct(api_key, case, retries=4, timeout=60)
                state = direct_state(case, result)
            elif pipeline == "hybrid_gated":
                result = run_hybrid(api_key, case)
                state = result["final_state"]
            else:
                result = run_structured(case)
                state = result["final_state"]

            cls = state_class(case, state)
            record = {"case": case, "pipeline": pipeline, "state_class": cls, "result": result}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            row = {
                "id": case["id"],
                "family": case["family"],
                "pipeline": pipeline,
                "choice": result["choice"],
                "expected": case["expected_label"],
                "correct": result["correct"],
                "state_class": cls,
                "parser_accuracy": result.get("operational_parser_accuracy"),
                "calls": result["calls"],
                "critical_path_ms": round(result["critical_path_ms"], 1),
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
            rows.append(row)
            print(
                f"[{idx:02d}/{len(items)}] {case['id']} {pipeline:18s} "
                f"exp={case['expected_label']} got={result['choice']} "
                f"class={cls:20s} parse={row['parser_accuracy'] if row['parser_accuracy'] is not None else '-'} "
                f"ms={result['critical_path_ms']:.0f}"
            )

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for pipeline in PIPELINES:
        rs = [r for r in rows if r["pipeline"] == pipeline]
        summary[pipeline] = {
            "n": len(rs),
            "accuracy": statistics.mean(r["correct"] for r in rs),
            "exact": sum(r["state_class"] == "exact" for r in rs),
            "reachable_incomplete": sum(r["state_class"] == "reachable_incomplete" for r in rs),
            "unreachable_invalid": sum(r["state_class"] == "unreachable_invalid" for r in rs),
            "mean_calls": statistics.mean(r["calls"] for r in rs),
            "mean_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
        }
        if pipeline == "hybrid_gated":
            summary[pipeline]["mean_parser_accuracy"] = statistics.mean(
                r["parser_accuracy"] for r in rs if r["parser_accuracy"] is not None
            )

    by_family = {}
    for family in sorted({c["family"] for c in cases}):
        by_family[family] = {}
        for pipeline in PIPELINES:
            rs = [r for r in rows if r["family"] == family and r["pipeline"] == pipeline]
            by_family[family][pipeline] = {
                "accuracy": statistics.mean(r["correct"] for r in rs),
                "invalid": sum(r["state_class"] == "unreachable_invalid" for r in rs),
            }

    meta.write_text(json.dumps({
        "run_id": RUN_ID,
        "benchmark_sha256": BENCH_SHA256,
        "summary": summary,
        "by_family": by_family,
    }, indent=2), encoding="utf-8")

    print("\n=== RUNTIME V2 SUMMARY ===")
    print(json.dumps({"summary": summary, "by_family": by_family}, indent=2))


if __name__ == "__main__":
    main()
