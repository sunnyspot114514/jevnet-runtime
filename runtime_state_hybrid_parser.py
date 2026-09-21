#!/usr/bin/env python3
"""Hybrid runtime parser: deterministic fields + Jev semantic event type.

Post-hoc exploratory on frozen runtime_state_benchmark_v1.

Mechanical metadata is extracted deterministically from event text using the
case's frozen domains. Jev classifies only event_type.

This approximates production structured receipts:
- IDs, versions, keys, timestamps, txids are machine fields
- Jev is used only when semantic classification is actually needed
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import runtime_state_runner as v1
import runtime_state_parser_v2 as pv2
from jevnet_experiment import post_jev, winner, usage_tokens

RUN_ID = "runtime-state-hybrid-parser-posthoc"


def exact_domain_match(text: str, options: list[str]) -> str:
    candidates = [o for o in options if o != "NONE"]
    hits = []
    for o in candidates:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(o)}(?![A-Za-z0-9_])", text, flags=re.I):
            hits.append(o)
    # Prefer longest token to avoid substrings if domains overlap.
    if not hits:
        return "NONE"
    hits.sort(key=lambda x: (-len(x), x))
    return hits[0]


def deterministic_fields(case, text):
    d = case["domains"]
    family = case["family"]

    key = exact_domain_match(text, d["key"])
    value = exact_domain_match(text, d["value"])
    writer = exact_domain_match(text, d["writer"])
    txid = exact_domain_match(text, d["txid"])

    event_time = "NONE"
    m = re.search(r"event\s+time\s+(?:is\s+)?(-?\d+)", text, flags=re.I)
    if m and m.group(1) in d["event_time"]:
        event_time = m.group(1)

    expected_version = "NONE"
    m = re.search(r"expected\s+version\s+(-?\d+)", text, flags=re.I)
    if m and m.group(1) in d["expected_version"]:
        expected_version = m.group(1)

    version = "NONE"
    if family == "staleness":
        m = re.search(r"sequence\s+(-?\d+)", text, flags=re.I)
        if m and m.group(1) in d["version"]:
            version = m.group(1)
    elif family in ("conflict_write", "revocation"):
        # Remove expected-version phrases first so a precondition is never copied into version.
        cleaned = re.sub(r"expected\s+version\s+-?\d+", "", text, flags=re.I)
        matches = re.findall(r"(?:old\s+)?version\s+(-?\d+)", cleaned, flags=re.I)
        if matches:
            for candidate in matches:
                if candidate in d["version"]:
                    version = candidate
                    break
    elif family == "transaction":
        version = "NONE"

    return {
        "key": key,
        "value": value,
        "version": version,
        "writer": writer,
        "txid": txid,
        "event_time": event_time,
        "expected_version": expected_version,
    }


def classify_event_type(api_key, case, text):
    q = {
        "event_type": {
            "type": "choice",
            "instructions": (
                "Classify the semantic operation expressed by event_text. "
                "Use the operation definitions; do not extract any other fields."
            ),
            "criteria": pv2.event_type_criteria(case["family"]),
        }
    }
    state = {
        "node_scope": "runtime_event_type_only",
        "family": case["family"],
        "event_text": text,
    }
    resp, ms = post_jev(api_key, state, q, retries=4, timeout=60)
    return winner(resp["answers"]["event_type"]), resp, ms


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
            c += pv == gv
            t += 1
    return c / t


def main():
    cases = v1.load_benchmark()
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir = Path("runtime_state_results")
    raw = outdir / f"raw-{RUN_ID}.jsonl"
    meta = outdir / f"meta-{RUN_ID}.json"
    if raw.exists() or meta.exists():
        raise SystemExit("hybrid parser run exists; refusing replay")

    rows = []
    with raw.open("w", encoding="utf-8") as f:
        for case in cases:
            t0 = time.perf_counter()

            def work(text):
                fields = deterministic_fields(case, text)
                et, resp, ms = classify_event_type(api_key, case, text)
                return {"event_type": et, **fields}, resp, ms

            with ThreadPoolExecutor(max_workers=len(case["events"])) as ex:
                parsed = list(ex.map(work, case["events"]))

            proposals = [p for p, _, _ in parsed]
            responses = [r for _, r, _ in parsed]
            times = [ms for _, _, ms in parsed]

            final_state = v1.REDUCERS[case["family"]](case, proposals)
            label = v1.state_to_label(case, final_state)
            acc = operational_accuracy(case, proposals)
            wall = (time.perf_counter() - t0) * 1000

            inp = out = 0
            for r in responses:
                i, o = usage_tokens(r)
                inp += i
                out += o

            rec = {
                "id": case["id"],
                "family": case["family"],
                "choice": label,
                "expected": case["expected_label"],
                "correct": int(label == case["expected_label"]),
                "operational_parser_accuracy": acc,
                "proposals": proposals,
                "final_state": final_state,
                "wall_ms": wall,
                "input_tokens": inp,
                "output_tokens": out,
            }
            rows.append(rec)
            f.write(json.dumps({"case": case, "result": rec}, ensure_ascii=False) + "\n")
            f.flush()
            print(
                case["id"], case["family"],
                "exp", case["expected_label"], "got", label,
                "ok", rec["correct"],
                "parse", f"{acc:.3f}",
                "wall", f"{wall:.0f}ms",
                "tokens", f"{inp}+{out}",
            )

    summary = {
        "n": len(rows),
        "accuracy": statistics.mean(r["correct"] for r in rows),
        "mean_operational_parser_accuracy": statistics.mean(r["operational_parser_accuracy"] for r in rows),
        "mean_wall_ms": statistics.mean(r["wall_ms"] for r in rows),
        "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rows),
        "mean_output_tokens": statistics.mean(r["output_tokens"] for r in rows),
        "status": "posthoc/exploratory on frozen v1",
    }
    meta.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
