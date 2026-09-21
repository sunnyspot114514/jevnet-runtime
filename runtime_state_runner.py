#!/usr/bin/env python3
"""State-runtime benchmark runner.

This file is defined before runtime_state_benchmark_v1.json is frozen.

Pipelines:
  direct:
    One Jev call reads initial state + event stream and chooses a final-state candidate.

  gated:
    Jev parses each natural-language event into a typed Proposal.
    A deterministic reducer validates and commits proposals into canonical state.

Families:
  conflict_write
  revocation
  staleness
  transaction

The deterministic runtime never reads the natural-language text directly; it
only consumes Jev proposals. The benchmark includes hidden oracle event structs
for auditing parser accuracy and validating the benchmark itself.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from jevnet_experiment import post_jev, choice_probs, winner, usage_tokens

BENCH_PATH = Path("runtime_state_benchmark_v1.json")
BENCH_SHA256 = "c3bebbe71cf438c3cc74df4c4ee24163d4d64e1557f030e1c42f41960e952692"
RUN_ID = "runtime-state-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_benchmark() -> list[dict[str, Any]]:
    if BENCH_SHA256 == "__TO_BE_FROZEN__":
        raise SystemExit("benchmark hash is not frozen")
    if sha256(BENCH_PATH) != BENCH_SHA256:
        raise SystemExit("runtime_state_benchmark_v1.json hash mismatch")
    return json.loads(BENCH_PATH.read_text(encoding="utf-8"))


def _choice_question(label: str, description: str, options: list[str]) -> dict[str, Any]:
    return {
        label: {
            "type": "choice",
            "instructions": description,
            "criteria": {o: f"The exact value is {o}." for o in options},
        }
    }


def parse_questions(case: dict[str, Any]) -> dict[str, Any]:
    d = case["domains"]
    q: dict[str, Any] = {}

    fields = [
        ("event_type", "Classify the exact event type expressed by event_text.", d["event_type"]),
        ("key", "Extract the exact state key targeted by event_text. Use NONE if not applicable.", d["key"]),
        ("value", "Extract the exact proposed value. Use NONE if not applicable.", d["value"]),
        ("version", "Extract the exact integer version/sequence as a string. Use NONE if absent.", d["version"]),
        ("writer", "Extract the exact writer/actor identity. Use NONE if absent.", d["writer"]),
        ("txid", "Extract the exact transaction ID. Use NONE if absent.", d["txid"]),
        ("event_time", "Extract the exact event time/epoch as a string. Use NONE if absent.", d["event_time"]),
        ("expected_version", "Extract the exact expected current-state version as a string. Use NONE if absent.", d["expected_version"]),
    ]
    for name, instruction, options in fields:
        q.update(_choice_question(name, instruction, options))
    return q


def parse_event(
    api_key: str,
    case: dict[str, Any],
    event_text: str,
    retries: int,
    timeout: float,
) -> tuple[dict[str, str], dict[str, Any], float]:
    state = {
        "node_scope": "runtime_event_parser",
        "family": case["family"],
        "event_text": event_text,
        "runtime_rules": case["runtime_rules"],
        "contract_note": (
            "Extract fields literally from event_text. Do not resolve conflicts, apply policy, "
            "or predict the final state. You are producing a Proposal only."
        ),
    }
    resp, ms = post_jev(
        api_key,
        state,
        parse_questions(case),
        retries=retries,
        timeout=timeout,
    )
    answers = resp["answers"]
    proposal = {field: winner(ans) for field, ans in answers.items()}
    return proposal, resp, ms


def normalize_none(v: str | None) -> str | None:
    if v is None or v == "NONE":
        return None
    return v


def parse_int(v: str | None) -> int | None:
    v = normalize_none(v)
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def apply_conflict_write(case: dict[str, Any], proposals: list[dict[str, str]]) -> dict[str, Any]:
    state = json.loads(json.dumps(case["initial_state"]))
    priorities = case["runtime_config"]["writer_priority"]

    for p in proposals:
        if p["event_type"] != "WRITE":
            continue
        key = normalize_none(p["key"])
        value = normalize_none(p["value"])
        writer = normalize_none(p["writer"])
        version = parse_int(p["version"])
        if None in (key, value, writer, version):
            continue
        if key != state["key"]:
            continue

        current_version = int(state["version"])
        current_writer = state["writer"]

        accept = False
        if version > current_version:
            accept = True
        elif version == current_version:
            new_prio = int(priorities.get(writer, -1))
            old_prio = int(priorities.get(current_writer, -1))
            if new_prio > old_prio:
                accept = True

        if accept:
            state["value"] = value
            state["version"] = version
            state["writer"] = writer

    return state


def apply_revocation(case: dict[str, Any], proposals: list[dict[str, str]]) -> dict[str, Any]:
    state = json.loads(json.dumps(case["initial_state"]))

    for p in proposals:
        et = p["event_type"]
        if et not in ("WRITE", "REVOKE"):
            continue
        key = normalize_none(p["key"])
        version = parse_int(p["version"])
        if key != state["key"] or version is None:
            continue

        current_version = int(state["version"])
        if version <= current_version:
            continue

        if et == "REVOKE":
            state["value"] = "REVOKED"
            state["revoked"] = True
            state["version"] = version
            state["writer"] = normalize_none(p["writer"]) or state.get("writer")
        else:
            # A later write may replace a tombstone only if it carries a strictly newer version.
            value = normalize_none(p["value"])
            if value is None:
                continue
            state["value"] = value
            state["revoked"] = False
            state["version"] = version
            state["writer"] = normalize_none(p["writer"]) or state.get("writer")

    return state


def apply_staleness(case: dict[str, Any], proposals: list[dict[str, str]]) -> dict[str, Any]:
    state = json.loads(json.dumps(case["initial_state"]))
    now = int(case["runtime_config"]["now"])
    ttl = int(case["runtime_config"]["ttl"])

    for p in proposals:
        if p["event_type"] != "SENSOR":
            continue
        key = normalize_none(p["key"])
        value = normalize_none(p["value"])
        seq = parse_int(p["version"])
        event_time = parse_int(p["event_time"])
        if None in (key, value, seq, event_time):
            continue
        if key != state["key"]:
            continue
        if seq <= int(state["seq"]):
            continue
        if event_time < now - ttl or event_time > now:
            continue

        state["value"] = value
        state["seq"] = seq
        state["event_time"] = event_time
        state["writer"] = normalize_none(p["writer"]) or state.get("writer")

    return state


def apply_transaction(case: dict[str, Any], proposals: list[dict[str, str]]) -> dict[str, Any]:
    state = json.loads(json.dumps(case["initial_state"]))
    required_keys = list(case["runtime_config"]["required_keys"])

    tx: dict[str, dict[str, Any]] = {}

    for p in proposals:
        et = p["event_type"]
        txid = normalize_none(p["txid"])
        if txid is None:
            continue
        rec = tx.setdefault(txid, {"writes": {}, "auth": False, "commit": False, "expected_version": None})

        if et == "TX_WRITE":
            key = normalize_none(p["key"])
            value = normalize_none(p["value"])
            ev = parse_int(p["expected_version"])
            if key is None or value is None:
                continue
            rec["writes"][key] = value
            if ev is not None:
                if rec["expected_version"] is None:
                    rec["expected_version"] = ev
                elif rec["expected_version"] != ev:
                    rec["expected_version"] = "CONFLICT"
        elif et == "AUTH":
            rec["auth"] = True
        elif et == "COMMIT":
            ev = parse_int(p["expected_version"])
            rec["commit"] = True
            if ev is not None:
                if rec["expected_version"] is None:
                    rec["expected_version"] = ev
                elif rec["expected_version"] != ev:
                    rec["expected_version"] = "CONFLICT"

    # Transactions are evaluated in first-seen order from the proposal stream.
    seen_order = []
    for p in proposals:
        txid = normalize_none(p["txid"])
        if txid and txid not in seen_order:
            seen_order.append(txid)

    for txid in seen_order:
        rec = tx[txid]
        if not rec["auth"] or not rec["commit"]:
            continue
        if rec["expected_version"] == "CONFLICT":
            continue
        if rec["expected_version"] is None:
            continue
        if int(rec["expected_version"]) != int(state["version"]):
            continue
        if any(k not in rec["writes"] for k in required_keys):
            continue
        if any(k not in state["values"] for k in required_keys):
            continue

        # Atomic commit.
        new_values = dict(state["values"])
        for k in required_keys:
            new_values[k] = rec["writes"][k]
        state["values"] = new_values
        state["version"] = int(state["version"]) + 1
        state["last_txid"] = txid

    return state


REDUCERS = {
    "conflict_write": apply_conflict_write,
    "revocation": apply_revocation,
    "staleness": apply_staleness,
    "transaction": apply_transaction,
}


def direct_questions(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_state": {
            "type": "choice",
            "instructions": (
                "Apply runtime_rules exactly to initial_state and event_stream, then choose the canonical final state. "
                "Do not treat a later textual mention as authoritative unless the rules permit it."
            ),
            "criteria": {
                label: json.dumps(state, sort_keys=True)
                for label, state in case["candidate_states"].items()
            },
        }
    }


def run_direct(api_key: str, case: dict[str, Any], retries: int, timeout: float) -> dict[str, Any]:
    state = {
        "node_scope": "runtime_direct_final_state",
        "family": case["family"],
        "runtime_rules": case["runtime_rules"],
        "runtime_config": case["runtime_config"],
        "initial_state": case["initial_state"],
        "event_stream": case["events"],
    }
    t0 = time.perf_counter()
    resp, ms = post_jev(api_key, state, direct_questions(case), retries=retries, timeout=timeout)
    wall = (time.perf_counter() - t0) * 1000
    choice = winner(resp["answers"]["final_state"])
    probs = choice_probs(resp["answers"]["final_state"])
    inp, out = usage_tokens(resp)
    return {
        "choice": choice,
        "expected_p": probs.get(case["expected_label"], 0.0),
        "correct": int(choice == case["expected_label"]),
        "calls": 1,
        "critical_path_ms": wall,
        "input_tokens": inp,
        "output_tokens": out,
        "response": resp,
    }


def proposal_field_accuracy(case: dict[str, Any], proposals: list[dict[str, str]]) -> dict[str, Any]:
    oracle = case["oracle_events"]
    total = 0
    correct = 0
    per_field: dict[str, list[int]] = {}

    fields = ["event_type", "key", "value", "version", "writer", "txid", "event_time", "expected_version"]
    for pred, gold in zip(proposals, oracle):
        for field in fields:
            gv = str(gold.get(field, "NONE")) if gold.get(field) is not None else "NONE"
            pv = pred.get(field) or "NONE"
            ok = int(pv == gv)
            total += 1
            correct += ok
            per_field.setdefault(field, []).append(ok)

    return {
        "overall": correct / total if total else 1.0,
        "per_field": {k: sum(v) / len(v) for k, v in per_field.items()},
        "correct": correct,
        "total": total,
    }


def state_to_label(case: dict[str, Any], state: dict[str, Any]) -> str:
    for label, candidate in case["candidate_states"].items():
        if state == candidate:
            return label
    return "UNLISTED"


def run_gated(api_key: str, case: dict[str, Any], retries: int, timeout: float) -> dict[str, Any]:
    proposals = []
    responses = []
    times = []
    t0 = time.perf_counter()

    for text in case["events"]:
        proposal, resp, ms = parse_event(api_key, case, text, retries, timeout)
        proposals.append(proposal)
        responses.append(resp)
        times.append(ms)

    reducer = REDUCERS[case["family"]]
    final_state = reducer(case, proposals)
    label = state_to_label(case, final_state)

    wall = (time.perf_counter() - t0) * 1000
    inp = out = 0
    for resp in responses:
        i, o = usage_tokens(resp)
        inp += i
        out += o

    field_acc = proposal_field_accuracy(case, proposals)
    return {
        "choice": label,
        "correct": int(label == case["expected_label"]),
        "final_state": final_state,
        "proposals": proposals,
        "parser_accuracy": field_acc,
        "calls": len(responses),
        "critical_path_ms": wall,
        "input_tokens": inp,
        "output_tokens": out,
        "responses": responses,
    }


def oracle_reduce(case: dict[str, Any]) -> dict[str, Any]:
    proposals = []
    for e in case["oracle_events"]:
        p = {}
        for field in ["event_type", "key", "value", "version", "writer", "txid", "event_time", "expected_version"]:
            v = e.get(field)
            p[field] = "NONE" if v is None else str(v)
        proposals.append(p)
    return REDUCERS[case["family"]](case, proposals)


def validate_benchmark(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        oracle_state = oracle_reduce(case)
        expected_state = case["candidate_states"][case["expected_label"]]
        if oracle_state != expected_state:
            raise RuntimeError(
                f"oracle mismatch {case['id']}: {oracle_state} != {expected_state}"
            )


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pipeline", action="append", choices=("direct", "gated"), default=[])
    p.add_argument("--run-id", default=RUN_ID)
    p.add_argument("--output-dir", default="runtime_state_results")
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    cases = load_benchmark()
    validate_benchmark(cases)
    pipelines = args.pipeline or ["direct", "gated"]

    outdir = Path(args.output_dir)
    outdir.mkdir(exist_ok=True)
    raw = outdir / f"raw-{args.run_id}.jsonl"
    csvp = outdir / f"summary-{args.run_id}.csv"
    meta = outdir / f"meta-{args.run_id}.json"
    if any(p.exists() for p in (raw, csvp, meta)):
        raise SystemExit("runtime benchmark run exists; refusing replay")

    items = [(case, pipeline) for case in cases for pipeline in pipelines]
    print(f"runtime state benchmark | cases={len(cases)} | pipelines={pipelines} | items={len(items)}")
    if args.dry_run:
        for case, pipeline in items:
            print(case["id"], case["family"], pipeline, case["expected_label"])
        return

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    rows = []
    with raw.open("w", encoding="utf-8") as f:
        for idx, (case, pipeline) in enumerate(items, 1):
            if pipeline == "direct":
                result = run_direct(api_key, case, args.retries, args.timeout)
                parser_acc = None
            else:
                result = run_gated(api_key, case, args.retries, args.timeout)
                parser_acc = result["parser_accuracy"]["overall"]

            record = {"case": case, "pipeline": pipeline, "result": result}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            row = {
                "id": case["id"],
                "family": case["family"],
                "pipeline": pipeline,
                "choice": result["choice"],
                "expected": case["expected_label"],
                "correct": result["correct"],
                "parser_accuracy": parser_acc,
                "calls": result["calls"],
                "critical_path_ms": round(result["critical_path_ms"], 1),
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
            rows.append(row)
            print(
                f"[{idx:02d}/{len(items)}] {case['id']} {pipeline:6s} "
                f"exp={case['expected_label']} got={result['choice']} "
                f"ok={result['correct']} parser={parser_acc if parser_acc is not None else '-'} "
                f"calls={result['calls']} ms={result['critical_path_ms']:.0f}"
            )

    with csvp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for pipeline in pipelines:
        rs = [r for r in rows if r["pipeline"] == pipeline]
        summary[pipeline] = {
            "n": len(rs),
            "accuracy": statistics.mean(r["correct"] for r in rs),
            "mean_calls": statistics.mean(r["calls"] for r in rs),
            "mean_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
            "mean_output_tokens": statistics.mean(r["output_tokens"] for r in rs),
        }
        if pipeline == "gated":
            summary[pipeline]["mean_parser_accuracy"] = statistics.mean(
                r["parser_accuracy"] for r in rs if r["parser_accuracy"] is not None
            )

    family_summary = {}
    for family in sorted({c["family"] for c in cases}):
        family_summary[family] = {}
        for pipeline in pipelines:
            rs = [r for r in rows if r["family"] == family and r["pipeline"] == pipeline]
            family_summary[family][pipeline] = {
                "accuracy": statistics.mean(r["correct"] for r in rs),
                "n": len(rs),
            }

    meta.write_text(json.dumps({
        "run_id": args.run_id,
        "benchmark_sha256": BENCH_SHA256,
        "summary": summary,
        "by_family": family_summary,
    }, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps({"summary": summary, "by_family": family_summary}, indent=2))


if __name__ == "__main__":
    main()
