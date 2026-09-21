#!/usr/bin/env python3
"""Mechanism probes for Jev packet bandwidth and depth retention."""

from __future__ import annotations

import csv
import json
import os
import statistics
import time
from pathlib import Path

import flygraph_benchmark as fb
from jevnet_experiment import post_jev, winner

TOKENS = ["TOK_A", "TOK_B", "TOK_C", "TOK_D", "TOK_E", "TOK_F"]
TASK = {
    "id": "CHANNEL",
    "category": "packet_transport",
    "question": "Have all six logical source tokens been recovered? Choose COMPLETE only if every slot 1 through 6 is known exactly.",
    "slot_options": TOKENS,
    "slot_values": TOKENS,
    "answer_options": {
        "COMPLETE": "All six logical slots are known exactly.",
        "INCOMPLETE": "At least one logical slot is missing or uncertain."
    },
    "expected": "COMPLETE"
}
Q = fb.make_questions(TASK)


def onehot_choice(value, options):
    probs = {o: float(o == value) for o in options}
    return {"type": "choice", "choice": value, "probabilities": probs, "confidence": 1.0}


def perfect_partial(slot_index):
    p = {}
    opts = TOKENS + ["UNKNOWN"]
    for i, tok in enumerate(TOKENS, 1):
        p[f"slot_{i}"] = onehot_choice(tok if i == slot_index else "UNKNOWN", opts)
    p["decision_ready"] = {"type": "noul", "noul": 0.0}
    p["answer"] = onehot_choice("UNKNOWN", ["COMPLETE", "INCOMPLETE", "UNKNOWN"])
    return p


def perfect_full():
    p = {}
    opts = TOKENS + ["UNKNOWN"]
    for i, tok in enumerate(TOKENS, 1):
        p[f"slot_{i}"] = onehot_choice(tok, opts)
    p["decision_ready"] = {"type": "noul", "noul": 1.0}
    p["answer"] = onehot_choice("COMPLETE", ["COMPLETE", "INCOMPLETE", "UNKNOWN"])
    return p


def slot_stats(pkt):
    correct = unknown = wrong = 0
    for i, tok in enumerate(TOKENS, 1):
        got = winner(pkt[f"slot_{i}"])
        if got == tok:
            correct += 1
        elif got == "UNKNOWN":
            unknown += 1
        else:
            wrong += 1
    return correct, unknown, wrong


def call(api_key, state):
    r, ms = post_jev(api_key, state, Q, retries=4, timeout=60)
    return r, ms


def main():
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("mechanism_probe_results")
    outdir.mkdir(exist_ok=True)
    raw = outdir / "raw-channel-capacity-v1.jsonl"
    csvp = outdir / "summary-channel-capacity-v1.csv"
    meta = outdir / "meta-channel-capacity-v1.json"
    if any(p.exists() for p in (raw, csvp, meta)):
        raise SystemExit("mechanism probe already exists; refusing replay")

    rows = []
    with raw.open("w", encoding="utf-8") as f:
        # Fan-in: 5 balanced repeats for each k.
        for k in range(1, 7):
            for rep in range(5):
                slots = [((rep + j) % 6) + 1 for j in range(k)]
                upstream = {f"src_{s}": perfect_partial(s) for s in slots}
                state = {
                    "node_scope": "fan_in_capacity_probe",
                    "task_question": TASK["question"],
                    "upstream_packets": upstream,
                    "expected_visible_slots": slots,
                    "contract_note": (
                        "This is an identity/union test. Preserve every known source slot exactly, keep all unseen "
                        "slots UNKNOWN, and do not invent hidden values."
                    ),
                }
                t0 = time.perf_counter()
                resp, ms = call(api_key, state)
                wall = (time.perf_counter() - t0) * 1000
                pkt = resp["answers"]
                c, u, w = slot_stats(pkt)
                visible_correct = sum(
                    winner(pkt[f"slot_{s}"]) == TOKENS[s - 1] for s in slots
                )
                hallucinated_hidden = sum(
                    winner(pkt[f"slot_{s}"]) != "UNKNOWN"
                    for s in range(1, 7) if s not in slots
                )
                row = {
                    "probe": "fanin",
                    "k": k,
                    "rep": rep,
                    "depth": 0,
                    "visible_correct": visible_correct,
                    "visible_total": k,
                    "all_correct": c,
                    "unknown": u,
                    "wrong": w,
                    "hallucinated_hidden": hallucinated_hidden,
                    "answer": winner(pkt["answer"]),
                    "ready": float(pkt["decision_ready"].get("noul", 0)),
                    "ms": wall,
                }
                rows.append(row)
                f.write(json.dumps({"row": row, "response": resp}, ensure_ascii=False) + "\n")
                f.flush()
                print(
                    f"fanin k={k} rep={rep} visible={visible_correct}/{k} "
                    f"all={c}C/{u}U/{w}W halluc={hallucinated_hidden} "
                    f"answer={row['answer']} ready={row['ready']:.2f}"
                )

        # Depth relay: 3 chains, report every depth from 1..6.
        for rep in range(3):
            current = perfect_full()
            for depth in range(1, 7):
                state = {
                    "node_scope": "identity_depth_probe",
                    "depth": depth,
                    "task_question": TASK["question"],
                    "previous_packet": current,
                    "contract_note": (
                        "Identity relay only. Preserve all six slot values exactly. No new evidence exists and no "
                        "slot should be forgotten, changed, or set to UNKNOWN."
                    ),
                }
                t0 = time.perf_counter()
                resp, ms = call(api_key, state)
                wall = (time.perf_counter() - t0) * 1000
                current = resp["answers"]
                c, u, w = slot_stats(current)
                row = {
                    "probe": "depth",
                    "k": 6,
                    "rep": rep,
                    "depth": depth,
                    "visible_correct": c,
                    "visible_total": 6,
                    "all_correct": c,
                    "unknown": u,
                    "wrong": w,
                    "hallucinated_hidden": 0,
                    "answer": winner(current["answer"]),
                    "ready": float(current["decision_ready"].get("noul", 0)),
                    "ms": wall,
                }
                rows.append(row)
                f.write(json.dumps({"row": row, "response": resp}, ensure_ascii=False) + "\n")
                f.flush()
                print(
                    f"depth rep={rep} d={depth} slots={c}C/{u}U/{w}W "
                    f"answer={row['answer']} ready={row['ready']:.2f}"
                )

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    fan = {}
    for k in range(1, 7):
        rs = [r for r in rows if r["probe"] == "fanin" and r["k"] == k]
        fan[str(k)] = {
            "mean_visible_retention": statistics.mean(r["visible_correct"] / r["visible_total"] for r in rs),
            "mean_total_correct_slots": statistics.mean(r["all_correct"] for r in rs),
            "mean_hallucinated_hidden": statistics.mean(r["hallucinated_hidden"] for r in rs),
            "mean_ready": statistics.mean(r["ready"] for r in rs),
        }

    depth_summary = {}
    for d in range(1, 7):
        rs = [r for r in rows if r["probe"] == "depth" and r["depth"] == d]
        depth_summary[str(d)] = {
            "mean_correct_slots": statistics.mean(r["all_correct"] for r in rs),
            "full_retention_rate": statistics.mean(r["all_correct"] == 6 for r in rs),
            "mean_ready": statistics.mean(r["ready"] for r in rs),
        }

    meta.write_text(json.dumps({
        "fanin": fan,
        "depth": depth_summary,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
