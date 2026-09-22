#!/usr/bin/env python3
"""Non-safety distributed reasoning benchmark over frozen graph topologies.

Each task has six node-local atomic slot values. Jev nodes may only infer slot
values from their own local value, their previous packet, and incoming neighbor
packets. Two synchronous message-passing rounds are run. The final answer is
read only from the fixed readout node (mAL_m8).

Graph variants:
- fly: real MaleCNS type-level strong-connection motif
- rewired: exact per-node in/out-degree control
- random: same N/E random strongly-connected control
- direct: one Jev call with all six slot values (upper/reference baseline)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from artifact_integrity import frozen_text_sha256
from typing import Any

from jevnet_experiment import MODEL, API_URL, post_jev, choice_probs, winner, usage_tokens

GRAPH_PATH = Path("flygraph_controls_v1.json")
GRAPH_SHA256 = "3ee9ef19e5ce68d333cea19fdd227328623b624e52c8627ef59ff81678f0dafb"
BENCH_PATH = Path("non_safety_benchmark_v1.json")
BENCH_SHA256 = "f5532639f5e0a3b0e75ed9d6135e4bb593a12ce49adeb314fd117a56d0547571"

GRAPH_VARIANTS = ("direct", "fly", "rewired", "random")
ROUNDS = 2


def sha256(path: Path) -> str:
    return frozen_text_sha256(path)


def load_graphs() -> dict[str, Any]:
    if sha256(GRAPH_PATH) != GRAPH_SHA256:
        raise SystemExit("flygraph_controls_v1.json hash mismatch")
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def load_benchmark() -> list[dict[str, Any]]:
    if BENCH_SHA256 == "__TO_BE_FROZEN__":
        raise SystemExit("Benchmark hash not frozen yet.")
    if sha256(BENCH_PATH) != BENCH_SHA256:
        raise SystemExit("non_safety_benchmark_v1.json hash mismatch")
    return json.loads(BENCH_PATH.read_text(encoding="utf-8"))


def make_questions(task: dict[str, Any]) -> dict[str, Any]:
    slot_options = task["slot_options"]
    questions: dict[str, Any] = {}

    criteria = {str(v): f"The slot's exact value is {v!r}." for v in slot_options}
    criteria["UNKNOWN"] = "The slot value has not reached this node or cannot be inferred reliably."

    for i in range(1, 7):
        questions[f"slot_{i}"] = {
            "type": "choice",
            "instructions": (
                f"Infer the value of source slot {i} from ONLY the accessible evidence in state. "
                "Use the local slot, self_previous_packet, and incoming_packets. "
                "Do not guess an unseen slot. Preserve an already known slot value unless directly contradicted."
            ),
            "criteria": criteria,
        }

    questions["decision_ready"] = {
        "type": "noul",
        "instructions": (
            "Does the accessible evidence contain enough source-slot information to answer task_question "
            "reliably? This is about information coverage, not general confidence."
        ),
        "criteria": {
            "true": "Enough required slot values are known to answer reliably.",
            "false": "Required information is still missing or ambiguous.",
        },
    }

    questions["answer"] = {
        "type": "choice",
        "instructions": (
            "Answer task_question using ONLY source-slot values supported by accessible evidence. "
            "If information is missing, prefer UNKNOWN rather than inventing hidden slot values."
        ),
        "criteria": {
            **{k: v for k, v in task["answer_options"].items()},
            "UNKNOWN": "The accessible evidence is insufficient to determine the answer.",
        },
    }
    return questions


def packet(resp: dict[str, Any]) -> dict[str, Any]:
    return resp["answers"]


def answer_choice(resp_or_packet: dict[str, Any]) -> str | None:
    p = resp_or_packet.get("answers", resp_or_packet)
    return winner(p["answer"])


def answer_prob(resp_or_packet: dict[str, Any], expected: str) -> float:
    p = resp_or_packet.get("answers", resp_or_packet)
    return choice_probs(p["answer"]).get(expected, 0.0)


def slot_choice(pkt: dict[str, Any], i: int) -> str | None:
    return winner(pkt[f"slot_{i}"])


def slot_accuracy(pkt: dict[str, Any], values: list[str]) -> float:
    return sum(slot_choice(pkt, i + 1) == str(v) for i, v in enumerate(values)) / len(values)


def slot_known(pkt: dict[str, Any]) -> int:
    return sum(slot_choice(pkt, i) != "UNKNOWN" for i in range(1, 7))


def call_packet(api_key, state, questions, retries, timeout):
    return post_jev(api_key, state, questions, retries=retries, timeout=timeout)


def direct_run(api_key, task, retries, timeout):
    q = make_questions(task)
    state = {
        "node_scope": "direct_full_information_baseline",
        "task_question": task["question"],
        "all_slot_values": {
            f"slot_{i+1}": str(v) for i, v in enumerate(task["slot_values"])
        },
        "contract_note": "All six source slots are directly visible in this baseline.",
    }
    t0 = time.perf_counter()
    resp, ms = call_packet(api_key, state, q, retries, timeout)
    wall = (time.perf_counter() - t0) * 1000
    inp, out = usage_tokens(resp)
    p = packet(resp)
    return {
        "choice": answer_choice(p),
        "expected_p": answer_prob(p, task["expected"]),
        "slot_accuracy": slot_accuracy(p, [str(v) for v in task["slot_values"]]),
        "slot_known": slot_known(p),
        "decision_ready": float(p["decision_ready"].get("noul", 0.0)),
        "critical_path_ms": wall,
        "sum_call_ms": ms,
        "input_tokens": inp,
        "output_tokens": out,
        "calls": 1,
        "trace": {"final": resp},
    }


def graph_run(api_key, task, graph_name, graphs, retries, timeout):
    graph = graphs[graph_name]
    nodes = graph["nodes"]
    readout = graphs["readout_node"]
    q = make_questions(task)

    incoming = {n: [] for n in nodes}
    edge_weight = {}
    for e in graph["edges"]:
        incoming[e["target"]].append(e["source"])
        edge_weight[(e["source"], e["target"])] = e["weight"]

    responses = []
    times = []
    t0 = time.perf_counter()

    # Round 0: local observation only.
    # Optional node_slot_order maps physical node position -> 1-based logical slot.
    slot_order = task.get("node_slot_order", list(range(1, 7)))

    def init_node(item):
        idx, node = item
        slot_idx = int(slot_order[idx])
        state = {
            "node_scope": "distributed_local_init",
            "graph_variant": graph_name,
            "node_id": node,
            "slot_index": slot_idx,
            "local_slot_value": str(task["slot_values"][slot_idx - 1]),
            "task_question": task["question"],
            "contract_note": (
                "Only the local source slot is observed at initialization. Other source slots are UNKNOWN."
            ),
        }
        resp, ms = call_packet(api_key, state, q, retries, timeout)
        return node, resp, ms

    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        init_rows = list(ex.map(init_node, list(enumerate(nodes))))
    current = {n: packet(r) for n, r, _ in init_rows}
    responses.extend(r for _, r, _ in init_rows)
    times.extend(ms for _, _, ms in init_rows)
    round_traces = [{"round": 0, "nodes": {n: r for n, r, _ in init_rows}}]

    # Synchronous message passing.
    for round_idx in range(1, ROUNDS + 1):
        previous = current

        def update_node(node):
            preds = incoming[node]
            state = {
                "node_scope": "distributed_message_update",
                "graph_variant": graph_name,
                "round": round_idx,
                "node_id": node,
                "task_question": task["question"],
                "self_previous_packet": previous[node],
                "incoming_packets": {p: previous[p] for p in preds},
                "incoming_edge_weights": {
                    p: edge_weight[(p, node)] for p in preds
                },
                "contract_note": (
                    "Merge source-slot evidence by provenance. A slot is a named source variable, so repeated "
                    "copies through multiple paths must NOT be double-counted. Synaptic weights are topology metadata "
                    "only in this unweighted-message experiment; they do not change a fact's truth."
                ),
            }
            resp, ms = call_packet(api_key, state, q, retries, timeout)
            return node, resp, ms

        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            rows = list(ex.map(update_node, nodes))
        current = {n: packet(r) for n, r, _ in rows}
        responses.extend(r for _, r, _ in rows)
        times.extend(ms for _, _, ms in rows)
        round_traces.append({"round": round_idx, "nodes": {n: r for n, r, _ in rows}})

    wall = (time.perf_counter() - t0) * 1000
    readout_packet = current[readout]

    total_in = total_out = 0
    for resp in responses:
        i, o = usage_tokens(resp)
        total_in += i
        total_out += o

    return {
        "choice": answer_choice(readout_packet),
        "expected_p": answer_prob(readout_packet, task["expected"]),
        "slot_accuracy": slot_accuracy(readout_packet, [str(v) for v in task["slot_values"]]),
        "slot_known": slot_known(readout_packet),
        "decision_ready": float(readout_packet["decision_ready"].get("noul", 0.0)),
        "critical_path_ms": wall,
        "sum_call_ms": sum(times),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "calls": len(responses),
        "trace": {
            "graph": graph_name,
            "readout": readout,
            "rounds": round_traces,
            "readout_packet": readout_packet,
        },
    }


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--graph", action="append", choices=GRAPH_VARIANTS, default=[])
    p.add_argument("--run-id", required=True)
    p.add_argument("--output-dir", default="flygraph_benchmark_results")
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    variants = args.graph or list(GRAPH_VARIANTS)
    graphs = load_graphs()
    tasks = load_benchmark()

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    raw_path = outdir / f"raw-{args.run_id}.jsonl"
    csv_path = outdir / f"summary-{args.run_id}.csv"
    meta_path = outdir / f"meta-{args.run_id}.json"
    if any(p.exists() for p in (raw_path, csv_path, meta_path)):
        raise SystemExit(f"Run id '{args.run_id}' already exists; refusing replay.")

    items = [(task, variant) for task in tasks for variant in variants]
    print(
        f"FlyGraph non-safety benchmark | tasks={len(tasks)} | variants={','.join(variants)} "
        f"| items={len(items)} | rounds={ROUNDS}"
    )
    if args.dry_run:
        for t, g in items:
            print(t["id"], g, t["expected"], t["category"])
        return

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY is not set.")

    rows = []
    with raw_path.open("w", encoding="utf-8") as rawf:
        for idx, (task, variant) in enumerate(items, 1):
            if variant == "direct":
                result = direct_run(api_key, task, args.retries, args.timeout)
            else:
                result = graph_run(api_key, task, variant, graphs, args.retries, args.timeout)
            record = {"task": task, "variant": variant, **result}
            rawf.write(json.dumps(record, ensure_ascii=False) + "\n")
            rawf.flush()

            row = {
                "id": task["id"],
                "category": task["category"],
                "expected": task["expected"],
                "variant": variant,
                "choice": result["choice"],
                "correct": int(result["choice"] == task["expected"]),
                "expected_p": result["expected_p"],
                "slot_accuracy": result["slot_accuracy"],
                "slot_known": result["slot_known"],
                "decision_ready": result["decision_ready"],
                "calls": result["calls"],
                "critical_path_ms": round(result["critical_path_ms"], 1),
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
            rows.append(row)
            print(
                f"[{idx:02d}/{len(items)}] {task['id']} {variant:7s} "
                f"exp={task['expected']:8s} got={str(result['choice']):8s} "
                f"P={result['expected_p']:.2f} slots={result['slot_known']}/6 "
                f"slotacc={result['slot_accuracy']:.2f} ready={result['decision_ready']:.2f} "
                f"ms={result['critical_path_ms']:.0f}"
            )

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    per_variant = {}
    for variant in variants:
        rs = [r for r in rows if r["variant"] == variant]
        per_variant[variant] = {
            "n": len(rs),
            "accuracy": statistics.mean(r["correct"] for r in rs),
            "mean_expected_p": statistics.mean(r["expected_p"] for r in rs),
            "mean_slot_accuracy": statistics.mean(r["slot_accuracy"] for r in rs),
            "mean_slots_known": statistics.mean(r["slot_known"] for r in rs),
            "mean_decision_ready": statistics.mean(r["decision_ready"] for r in rs),
            "mean_calls": statistics.mean(r["calls"] for r in rs),
            "mean_critical_path_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
        }

    meta = {
        "run_id": args.run_id,
        "model": MODEL,
        "api_url": API_URL,
        "graph_sha256": GRAPH_SHA256,
        "benchmark_sha256": BENCH_SHA256,
        "rounds": ROUNDS,
        "readout_node": graphs["readout_node"],
        "variants": per_variant,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for name, s in per_variant.items():
        print(
            f"{name:7s} acc={s['accuracy']:.3f} P={s['mean_expected_p']:.3f} "
            f"slotacc={s['mean_slot_accuracy']:.3f} known={s['mean_slots_known']:.2f}/6 "
            f"ready={s['mean_decision_ready']:.2f} calls={s['mean_calls']:.1f} "
            f"ms={s['mean_critical_path_ms']:.0f} input={s['mean_input_tokens']:.0f}"
        )


if __name__ == "__main__":
    main()
