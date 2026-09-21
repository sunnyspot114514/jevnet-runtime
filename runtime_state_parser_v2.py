#!/usr/bin/env python3
"""Exploratory typed/parallel parser V2 on frozen runtime_state_benchmark_v1.

This does NOT replace the frozen v1 confirmatory runner.
Changes:
- family-specific event-type semantics;
- transaction expected_version is explicitly separated from version;
- only explicitly stated writers are extracted;
- events are parsed in parallel, then restored to original order;
- deterministic reducer is unchanged.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import runtime_state_runner as v1
from jevnet_experiment import post_jev, winner, usage_tokens

RUN_ID = "runtime-state-parser-v2-posthoc"


def event_type_criteria(family: str) -> dict[str, str]:
    if family == "conflict_write":
        return {
            "WRITE": "A normal state write/update proposing key=value at a version.",
            "NONE": "Not a state write event.",
        }
    if family == "revocation":
        return {
            "WRITE": "A state write/update proposing key=value at a version.",
            "REVOKE": "An explicit revoke/tombstone operation.",
            "NONE": "Neither write nor revoke.",
        }
    if family == "staleness":
        return {
            "SENSOR": "A timestamped sensor/report observation with sequence/version.",
            "NONE": "Not a sensor/report event.",
        }
    if family == "transaction":
        return {
            "TX_WRITE": (
                "Stages/proposes/sets a key=value inside a named transaction. "
                "Words such as 'stages' count as TX_WRITE even if the literal word WRITE is absent."
            ),
            "AUTH": "Authorizes/approves a named transaction.",
            "COMMIT": "Requests/issues commit for a named transaction.",
            "NONE": "No transaction write, authorization, or commit operation is present.",
        }
    raise ValueError(family)


def q_choice(name: str, instruction: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {
        name: {
            "type": "choice",
            "instructions": instruction,
            "criteria": criteria,
        }
    }


def questions(case: dict[str, Any]) -> dict[str, Any]:
    d = case["domains"]
    q: dict[str, Any] = {}

    q.update(q_choice(
        "event_type",
        "Classify the exact operation expressed by event_text. Use the semantic definitions, not literal keyword matching.",
        event_type_criteria(case["family"]),
    ))

    q.update(q_choice(
        "key",
        "Extract the exact state key explicitly targeted. Use NONE if no key is stated.",
        {o: f"The key is {o}." for o in d["key"]},
    ))
    q.update(q_choice(
        "value",
        "Extract the exact proposed value explicitly stated. Use NONE if no value is stated.",
        {o: f"The value is {o}." for o in d["value"]},
    ))

    version_instruction = (
        "Extract an ACTUAL event/write version or sensor sequence. "
        "For transaction events, an 'expected version' is a precondition and MUST NOT be copied into version; "
        "use NONE unless a distinct actual version is explicitly stated."
    )
    q.update(q_choice(
        "version",
        version_instruction,
        {o: f"The actual version/sequence is {o}." for o in d["version"]},
    ))

    q.update(q_choice(
        "writer",
        "Extract the writer/actor only if explicitly named in event_text. Do not infer a missing writer. Use NONE if absent.",
        {o: f"The explicit writer is {o}." for o in d["writer"]},
    ))
    q.update(q_choice(
        "txid",
        "Extract the transaction ID exactly. Use NONE if this is not a transaction event.",
        {o: f"The transaction ID is {o}." for o in d["txid"]},
    ))
    q.update(q_choice(
        "event_time",
        "Extract the actual event timestamp exactly. Use NONE if absent.",
        {o: f"The event time is {o}." for o in d["event_time"]},
    ))
    q.update(q_choice(
        "expected_version",
        (
            "Extract the transaction precondition/expected current-state version exactly. "
            "This is separate from actual event version. Use NONE if absent."
        ),
        {o: f"The expected version is {o}." for o in d["expected_version"]},
    ))
    return q


def parse_one(api_key, case, text, retries=4, timeout=60):
    state = {
        "node_scope": "runtime_event_parser_v2",
        "family": case["family"],
        "event_text": text,
        "runtime_rules": case["runtime_rules"],
        "contract_note": (
            "Produce a typed Proposal only. Extract literal event semantics. "
            "Do not resolve the event against canonical state."
        ),
    }
    resp, ms = post_jev(api_key, state, questions(case), retries=retries, timeout=timeout)
    proposal = {name: winner(ans) for name, ans in resp["answers"].items()}
    return proposal, resp, ms


def operational_accuracy(case, proposals):
    relevant = {
        "conflict_write": {"event_type", "key", "value", "version", "writer"},
        "revocation": {"event_type", "key", "value", "version", "writer"},
        "staleness": {"event_type", "key", "value", "version", "writer", "event_time"},
        "transaction": {"event_type", "key", "value", "txid", "expected_version"},
    }[case["family"]]

    c = t = 0
    for pred, gold in zip(proposals, case["oracle_events"]):
        for field in relevant:
            gv = "NONE" if gold.get(field) is None else str(gold.get(field))
            pv = pred.get(field) or "NONE"
            t += 1
            c += pv == gv
    return c / t


def main():
    cases = v1.load_benchmark()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("runtime_state_results")
    outdir.mkdir(exist_ok=True)
    raw = outdir / f"raw-{RUN_ID}.jsonl"
    meta = outdir / f"meta-{RUN_ID}.json"
    if raw.exists() or meta.exists():
        raise SystemExit("posthoc parser-v2 run exists; refusing replay")

    rows = []
    with raw.open("w", encoding="utf-8") as f:
        for case in cases:
            t0 = time.perf_counter()

            def work(text):
                return parse_one(api_key, case, text)

            with ThreadPoolExecutor(max_workers=len(case["events"])) as ex:
                parsed = list(ex.map(work, case["events"]))

            proposals = [p for p, _, _ in parsed]
            responses = [r for _, r, _ in parsed]
            call_times = [ms for _, _, ms in parsed]

            state = v1.REDUCERS[case["family"]](case, proposals)
            label = v1.state_to_label(case, state)
            op_acc = operational_accuracy(case, proposals)
            wall = (time.perf_counter() - t0) * 1000

            inp = out = 0
            for resp in responses:
                i, o = usage_tokens(resp)
                inp += i
                out += o

            rec = {
                "id": case["id"],
                "family": case["family"],
                "expected": case["expected_label"],
                "choice": label,
                "correct": int(label == case["expected_label"]),
                "operational_parser_accuracy": op_acc,
                "proposals": proposals,
                "final_state": state,
                "wall_ms": wall,
                "sum_call_ms": sum(call_times),
                "input_tokens": inp,
                "output_tokens": out,
            }
            rows.append(rec)
            f.write(json.dumps({"case": case, "result": rec}, ensure_ascii=False) + "\n")
            f.flush()
            print(
                case["id"], case["family"],
                "expected", case["expected_label"], "got", label,
                "ok", rec["correct"],
                "parse", f"{op_acc:.3f}",
                "wall", f"{wall:.0f}ms",
            )

    summary = {
        "n": len(rows),
        "accuracy": statistics.mean(r["correct"] for r in rows),
        "mean_operational_parser_accuracy": statistics.mean(r["operational_parser_accuracy"] for r in rows),
        "mean_wall_ms": statistics.mean(r["wall_ms"] for r in rows),
        "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rows),
        "frozen_benchmark_sha256": v1.BENCH_SHA256,
        "status": "posthoc/exploratory on v1; requires fresh benchmark v2 for confirmation",
    }
    meta.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
