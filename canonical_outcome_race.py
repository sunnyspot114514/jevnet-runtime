#!/usr/bin/env python3
"""Observation reconciliation race: naive arrival order vs Canonical Outcome Commit.

No model/API calls.

One authorized dispatch has several observations:
- valid seq1 RUNNING
- valid seq2 SUCCEEDED
- valid seq3 ROLLED_BACK (later reconciliation corrected the provisional success)
- duplicate seq3 ROLLED_BACK
- spoofed seq4 SUCCEEDED with wrong authorization record
- conflicting duplicate seq2 FAILED

Naive last-arrival reducer:
- accepts any observation mentioning the dispatch;
- final state depends on delivery order.

Canonical Outcome Commit:
- requires matching auth_id, dispatch_id and idempotency_key;
- deduplicates identical (seq,status,result);
- same-seq conflict is quarantined;
- chooses the highest valid observation_seq;
- therefore delivery order does not affect canonical outcome.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter
from pathlib import Path

OUT = Path("canonical_outcome_race_analysis.json")

AUTH = {
    "auth_id": "AUTH-42",
    "dispatch_id": "DISP-42",
    "idempotency_key": "ORDER-7",
}

OBSERVATIONS = [
    {
        "obs_id": "O1",
        "auth_id": "AUTH-42",
        "dispatch_id": "DISP-42",
        "idempotency_key": "ORDER-7",
        "seq": 1,
        "status": "RUNNING",
        "result": "NONE",
    },
    {
        "obs_id": "O2",
        "auth_id": "AUTH-42",
        "dispatch_id": "DISP-42",
        "idempotency_key": "ORDER-7",
        "seq": 2,
        "status": "SUCCEEDED",
        "result": "R1",
    },
    {
        "obs_id": "O3",
        "auth_id": "AUTH-42",
        "dispatch_id": "DISP-42",
        "idempotency_key": "ORDER-7",
        "seq": 3,
        "status": "ROLLED_BACK",
        "result": "NONE",
    },
    {
        "obs_id": "O3-DUP",
        "auth_id": "AUTH-42",
        "dispatch_id": "DISP-42",
        "idempotency_key": "ORDER-7",
        "seq": 3,
        "status": "ROLLED_BACK",
        "result": "NONE",
    },
    {
        "obs_id": "SPOOF",
        "auth_id": "AUTH-FAKE",
        "dispatch_id": "DISP-42",
        "idempotency_key": "ORDER-7",
        "seq": 4,
        "status": "SUCCEEDED",
        "result": "EVIL",
    },
    {
        "obs_id": "O2-CONFLICT",
        "auth_id": "AUTH-42",
        "dispatch_id": "DISP-42",
        "idempotency_key": "ORDER-7",
        "seq": 2,
        "status": "FAILED",
        "result": "E2",
    },
]


def naive_last_arrival(auth, observations):
    state = {
        "status": "DISPATCHED",
        "result": "NONE",
        "seq": 0,
        "source_obs": "NONE",
    }
    for obs in observations:
        # Naive system checks only dispatch ID and overwrites by arrival.
        if obs["dispatch_id"] != auth["dispatch_id"]:
            continue
        state = {
            "status": obs["status"],
            "result": obs["result"],
            "seq": obs["seq"],
            "source_obs": obs["obs_id"],
        }
    return state


def canonical_outcome_commit(auth, observations):
    valid = []
    rejected = []
    quarantined = []

    for obs in observations:
        if obs["auth_id"] != auth["auth_id"]:
            rejected.append((obs["obs_id"], "auth_mismatch"))
            continue
        if obs["dispatch_id"] != auth["dispatch_id"]:
            rejected.append((obs["obs_id"], "dispatch_mismatch"))
            continue
        if obs["idempotency_key"] != auth["idempotency_key"]:
            rejected.append((obs["obs_id"], "idempotency_mismatch"))
            continue
        valid.append(obs)

    # Group by sequence and reconcile duplicates/conflicts.
    by_seq = {}
    for obs in valid:
        key = int(obs["seq"])
        by_seq.setdefault(key, []).append(obs)

    reconciled = []
    for seq, group in sorted(by_seq.items()):
        signatures = {(g["status"], g["result"]) for g in group}
        if len(signatures) > 1:
            # Conflicting same-seq receipts are not allowed to become canonical.
            for g in group:
                quarantined.append((g["obs_id"], f"same_seq_conflict:{seq}"))
            continue
        # Identical duplicate receipts collapse to one deterministic representative.
        chosen = sorted(group, key=lambda g: g["obs_id"])[0]
        reconciled.append(chosen)

    if not reconciled:
        return {
            "status": "DISPATCHED",
            "result": "NONE",
            "seq": 0,
            "source_obs": "NONE",
            "rejected": rejected,
            "quarantined": quarantined,
        }

    # Highest reconciled sequence is the canonical outcome.
    chosen = max(reconciled, key=lambda g: int(g["seq"]))
    return {
        "status": chosen["status"],
        "result": chosen["result"],
        "seq": int(chosen["seq"]),
        "source_obs": chosen["obs_id"],
        "rejected": sorted(rejected),
        "quarantined": sorted(quarantined),
    }


def simple_outcome(s):
    return (s["status"], s["result"], int(s["seq"]))


naive_counts = Counter()
canonical_counts = Counter()
canonical_diagnostics = Counter()

# 6! = 720 exhaustive delivery orders.
for perm in itertools.permutations(OBSERVATIONS):
    naive = naive_last_arrival(AUTH, perm)
    can = canonical_outcome_commit(AUTH, perm)
    naive_counts[simple_outcome(naive)] += 1
    canonical_counts[simple_outcome(can)] += 1
    canonical_diagnostics[
        (
            tuple(can["rejected"]),
            tuple(can["quarantined"]),
        )
    ] += 1

payload = {
    "n_permutations": 720,
    "authorization": AUTH,
    "observations": OBSERVATIONS,
    "naive_outcomes": [
        {"outcome": list(k), "count": v, "fraction": v / 720}
        for k, v in sorted(naive_counts.items())
    ],
    "canonical_outcomes": [
        {"outcome": list(k), "count": v, "fraction": v / 720}
        for k, v in sorted(canonical_counts.items())
    ],
    "canonical_diagnostic_variants": len(canonical_diagnostics),
    "expected_canonical": ["ROLLED_BACK", "NONE", 3],
}
OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

print("NAIVE OUTCOMES")
for k, v in sorted(naive_counts.items()):
    print(k, v, v / 720)

print("\nCANONICAL OUTCOMES")
for k, v in sorted(canonical_counts.items()):
    print(k, v, v / 720)

print("\ncanonical diagnostic variants", len(canonical_diagnostics))
for k, v in canonical_diagnostics.items():
    print("count", v, "rejected/quarantined", k)

assert len(canonical_counts) == 1
assert next(iter(canonical_counts)) == ("ROLLED_BACK", "NONE", 3)
assert len(canonical_diagnostics) == 1
print("\nCanonical Outcome Commit permutation invariance PASS: 720/720")
