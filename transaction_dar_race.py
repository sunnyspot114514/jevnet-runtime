#!/usr/bin/env python3
"""Transaction race experiment: arrival order vs Durable Authorization Record.

No model/API calls.

Two complete transactions are both authorized against canonical version 5.
Only one may commit, because the first successful commit increments version to 6
and the other transaction's expected_version=5 becomes stale.

Old reducer:
- transaction evaluation order is first-seen txid in delivered proposal stream.
- outcome depends on message delivery order.

DAR reducer:
- authorization carries a durable authorization sequence (auth_seq).
- eligible transactions are evaluated in auth_seq order, independent of delivery.
"""

from __future__ import annotations

import itertools
import json
import random
from collections import Counter
from pathlib import Path

import runtime_state_runner as base

OUT = Path("transaction_dar_race_analysis.json")

CASE = {
    "family": "transaction",
    "initial_state": {
        "version": 5,
        "values": {"LEFT": "L0", "RIGHT": "R0"},
        "last_txid": "NONE",
    },
    "runtime_config": {"required_keys": ["LEFT", "RIGHT"]},
}

# Both transactions are complete and target the same canonical version.
# TB has the earlier durable authorization order even if TA messages arrive first.
EVENTS = [
    # TA
    {"event_type":"TX_WRITE","key":"LEFT","value":"LA","version":"NONE","writer":"A","txid":"TA","event_time":"NONE","expected_version":"5","auth_seq":"20"},
    {"event_type":"TX_WRITE","key":"RIGHT","value":"RA","version":"NONE","writer":"A","txid":"TA","event_time":"NONE","expected_version":"5","auth_seq":"20"},
    {"event_type":"AUTH","key":"NONE","value":"NONE","version":"NONE","writer":"AUTH","txid":"TA","event_time":"NONE","expected_version":"NONE","auth_seq":"20"},
    {"event_type":"COMMIT","key":"NONE","value":"NONE","version":"NONE","writer":"A","txid":"TA","event_time":"NONE","expected_version":"5","auth_seq":"20"},
    # TB
    {"event_type":"TX_WRITE","key":"LEFT","value":"LB","version":"NONE","writer":"B","txid":"TB","event_time":"NONE","expected_version":"5","auth_seq":"10"},
    {"event_type":"TX_WRITE","key":"RIGHT","value":"RB","version":"NONE","writer":"B","txid":"TB","event_time":"NONE","expected_version":"5","auth_seq":"10"},
    {"event_type":"AUTH","key":"NONE","value":"NONE","version":"NONE","writer":"AUTH","txid":"TB","event_time":"NONE","expected_version":"NONE","auth_seq":"10"},
    {"event_type":"COMMIT","key":"NONE","value":"NONE","version":"NONE","writer":"B","txid":"TB","event_time":"NONE","expected_version":"5","auth_seq":"10"},
]


def apply_transaction_dar(case, proposals):
    state = json.loads(json.dumps(case["initial_state"]))
    required_keys = list(case["runtime_config"]["required_keys"])
    tx = {}

    for p in proposals:
        txid = p.get("txid")
        if not txid or txid == "NONE":
            continue
        rec = tx.setdefault(txid, {
            "writes": {},
            "auth": False,
            "commit": False,
            "expected_version": None,
            "auth_seq": None,
        })

        # All records may repeat auth_seq; they must agree if present.
        raw_seq = p.get("auth_seq")
        if raw_seq not in (None, "NONE"):
            seq = int(raw_seq)
            if rec["auth_seq"] is None:
                rec["auth_seq"] = seq
            elif rec["auth_seq"] != seq:
                rec["auth_seq"] = "CONFLICT"

        et = p["event_type"]
        if et == "TX_WRITE":
            key = p.get("key")
            value = p.get("value")
            ev = p.get("expected_version")
            if key not in (None, "NONE") and value not in (None, "NONE"):
                rec["writes"][key] = value
            if ev not in (None, "NONE"):
                ev = int(ev)
                if rec["expected_version"] is None:
                    rec["expected_version"] = ev
                elif rec["expected_version"] != ev:
                    rec["expected_version"] = "CONFLICT"
        elif et == "AUTH":
            rec["auth"] = True
        elif et == "COMMIT":
            rec["commit"] = True
            ev = p.get("expected_version")
            if ev not in (None, "NONE"):
                ev = int(ev)
                if rec["expected_version"] is None:
                    rec["expected_version"] = ev
                elif rec["expected_version"] != ev:
                    rec["expected_version"] = "CONFLICT"

    eligible = []
    for txid, rec in tx.items():
        if not rec["auth"] or not rec["commit"]:
            continue
        if rec["auth_seq"] in (None, "CONFLICT"):
            continue
        if rec["expected_version"] in (None, "CONFLICT"):
            continue
        if any(k not in rec["writes"] for k in required_keys):
            continue
        eligible.append((int(rec["auth_seq"]), txid, rec))

    # Durable authorization order, not arrival order.
    eligible.sort(key=lambda x: (x[0], x[1]))

    for _, txid, rec in eligible:
        if int(rec["expected_version"]) != int(state["version"]):
            continue
        new_values = dict(state["values"])
        for k in required_keys:
            new_values[k] = rec["writes"][k]
        state["values"] = new_values
        state["version"] = int(state["version"]) + 1
        state["last_txid"] = txid

    return state


def outcome_key(state):
    return (
        state["version"],
        state["values"]["LEFT"],
        state["values"]["RIGHT"],
        state["last_txid"],
    )


# Exhaustive permutations are 40320, small enough.
old_counts = Counter()
dar_counts = Counter()
examples = {}

for perm in itertools.permutations(EVENTS):
    seq = list(perm)
    old_state = base.apply_transaction(CASE, seq)
    dar_state = apply_transaction_dar(CASE, seq)
    ok = outcome_key(old_state)
    dk = outcome_key(dar_state)
    old_counts[ok] += 1
    dar_counts[dk] += 1
    examples.setdefault(("old", ok), [f"{e['txid']}:{e['event_type']}" for e in seq])
    examples.setdefault(("dar", dk), [f"{e['txid']}:{e['event_type']}" for e in seq])

payload = {
    "n_permutations": 40320,
    "case": CASE,
    "events": EVENTS,
    "old_outcomes": [
        {"outcome": list(k), "count": v, "fraction": v / 40320}
        for k, v in old_counts.items()
    ],
    "dar_outcomes": [
        {"outcome": list(k), "count": v, "fraction": v / 40320}
        for k, v in dar_counts.items()
    ],
    "expected_dar_outcome": [6, "LB", "RB", "TB"],
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

print("OLD OUTCOMES")
for k, v in old_counts.items():
    print(k, v, v/40320)

print("\nDAR OUTCOMES")
for k, v in dar_counts.items():
    print(k, v, v/40320)

assert len(dar_counts) == 1
assert next(iter(dar_counts)) == (6, "LB", "RB", "TB")
print("\nDAR order invariance PASS across all 40320 deliveries")
