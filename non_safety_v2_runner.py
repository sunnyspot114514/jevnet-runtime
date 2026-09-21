#!/usr/bin/env python3
"""Frozen non-safety benchmark v2 evaluator.

Architecture implementations are imported unchanged from non_safety_arch_zoo.py.
This file is created before non_safety_benchmark_v2.json is frozen.

Architectures:
- direct (full-information reference)
- mlp_dense
- rnn_residual
- transformer1
- moe

No architecture prompt or packet-schema tuning is permitted after the v2 hash is frozen.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
from pathlib import Path

import flygraph_benchmark as fb
import non_safety_arch_zoo as zoo

BENCH_PATH = Path("non_safety_benchmark_v2.json")
BENCH_SHA256 = "f568722107a79b9998756f704e2595cb7bbb89cba2427f8e4b1b243ec628dd13"
RUN_ID = "nonsafety-v2-arch-confirm-v1"
ARCHES = ("direct", "mlp_dense", "rnn_residual", "transformer1", "moe")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_benchmark():
    if BENCH_SHA256 == "__TO_BE_FROZEN__":
        raise SystemExit("Benchmark v2 hash has not been frozen yet.")
    if sha256(BENCH_PATH) != BENCH_SHA256:
        raise SystemExit("non_safety_benchmark_v2.json hash mismatch")
    return json.loads(BENCH_PATH.read_text(encoding="utf-8"))


def run_direct(api_key, task):
    return fb.direct_run(api_key, task, retries=4, timeout=60)


RUNNERS = {
    "direct": run_direct,
    "mlp_dense": lambda key, task: zoo.run_mlp(key, task, 4, 60),
    "rnn_residual": lambda key, task: zoo.run_rnn(key, task, 4, 60),
    "transformer1": lambda key, task: zoo.run_transformer(key, task, 4, 60),
    "moe": lambda key, task: zoo.run_moe(key, task, 4, 60),
}


def main():
    tasks = load_benchmark()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("non_safety_v2_results")
    outdir.mkdir(exist_ok=True)
    raw = outdir / f"raw-{RUN_ID}.jsonl"
    csvp = outdir / f"summary-{RUN_ID}.csv"
    meta = outdir / f"meta-{RUN_ID}.json"
    if any(p.exists() for p in (raw, csvp, meta)):
        raise SystemExit("v2 run already exists; refusing replay")

    rows = []
    items = [(task, arch) for task in tasks for arch in ARCHES]
    with raw.open("w", encoding="utf-8") as f:
        for idx, (task, arch) in enumerate(items, 1):
            res = RUNNERS[arch](api_key, task)
            record = {"task": task, "arch": arch, **res}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            row = {
                "id": task["id"],
                "category": task["category"],
                "expected": task["expected"],
                "arch": arch,
                "choice": res["choice"],
                "correct": int(res["choice"] == task["expected"]),
                "expected_p": res["expected_p"],
                "slot_accuracy": res["slot_accuracy"],
                "slot_known": res["slot_known"],
                "decision_ready": res["decision_ready"],
                "calls": res["calls"],
                "critical_path_ms": round(res["critical_path_ms"], 1),
                "input_tokens": res["input_tokens"],
            }
            rows.append(row)
            print(
                f"[{idx:02d}/{len(items)}] {task['id']} {arch:12s} "
                f"exp={task['expected']:8s} got={str(res['choice']):8s} "
                f"P={res['expected_p']:.2f} slots={res['slot_known']}/6 "
                f"slotacc={res['slot_accuracy']:.2f} ms={res['critical_path_ms']:.0f}"
            )

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for arch in ARCHES:
        rs = [r for r in rows if r["arch"] == arch]
        summary[arch] = {
            "n": len(rs),
            "accuracy": statistics.mean(r["correct"] for r in rs),
            "mean_expected_p": statistics.mean(r["expected_p"] for r in rs),
            "mean_slot_accuracy": statistics.mean(r["slot_accuracy"] for r in rs),
            "mean_slots_known": statistics.mean(r["slot_known"] for r in rs),
            "mean_ready": statistics.mean(r["decision_ready"] for r in rs),
            "mean_calls": statistics.mean(r["calls"] for r in rs),
            "mean_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
        }

    meta.write_text(json.dumps({
        "run_id": RUN_ID,
        "benchmark_sha256": BENCH_SHA256,
        "architectures_imported_from": "non_safety_arch_zoo.py",
        "summary": summary,
    }, indent=2), encoding="utf-8")

    print("\n=== NON-SAFETY V2 SUMMARY ===")
    for arch, s in summary.items():
        print(
            f"{arch:12s} acc={s['accuracy']:.3f} P={s['mean_expected_p']:.3f} "
            f"slotacc={s['mean_slot_accuracy']:.3f} known={s['mean_slots_known']:.2f}/6 "
            f"ready={s['mean_ready']:.2f} calls={s['mean_calls']:.1f} "
            f"ms={s['mean_ms']:.0f} input={s['mean_input_tokens']:.0f}"
        )


if __name__ == "__main__":
    main()
