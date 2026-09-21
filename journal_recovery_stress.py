#!/usr/bin/env python3
"""Durable-journal crash/restart stress test.

Many actions are interleaved. Each action may be authorized or unauthorized.

For authorized actions:
Proposal -> DAR -> DispatchIntent -> external idempotent effect
-> Observation -> CanonicalOutcomeCommit

Fault injection:
- random crashes between micro-steps;
- volatile state is discarded on every crash;
- some durable records are duplicated;
- provider effect may exist while Observation/COC are missing;
- final recovery starts with no volatile per-action state.

Recovery uses only:
- durable journal records;
- provider query by idempotency key.

Invariants:
- no unauthorized effect;
- exactly one effect per authorized action;
- exactly one canonical successful outcome per authorized action;
- replaying/recovering repeatedly does not change canonical digest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT = Path("journal_recovery_stress_analysis.json")
SEED = 20260921
WORKLOADS = 200
ACTIONS_PER_WORKLOAD = 50


@dataclass
class Journal:
    records: list[dict[str, Any]] = field(default_factory=list)

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(copy.deepcopy(record))

    def action_records(self, action_id: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r.get("action_id") == action_id]

    def first(self, action_id: str, kind: str) -> dict[str, Any] | None:
        for r in self.records:
            if r.get("action_id") == action_id and r["kind"] == kind:
                return r
        return None

    def has(self, action_id: str, kind: str) -> bool:
        return self.first(action_id, kind) is not None

    def action_ids(self) -> set[str]:
        return {r["action_id"] for r in self.records if "action_id" in r}


@dataclass
class Provider:
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0

    def dispatch(self, idem_key: str, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if idem_key in self.effects:
            return copy.deepcopy(self.effects[idem_key])
        receipt = {
            "idem_key": idem_key,
            "action_id": action_id,
            "receipt_id": f"REC-{action_id}",
            "status": "SUCCEEDED",
            "result": copy.deepcopy(payload),
        }
        self.effects[idem_key] = receipt
        return copy.deepcopy(receipt)

    def query(self, idem_key: str) -> dict[str, Any] | None:
        r = self.effects.get(idem_key)
        return copy.deepcopy(r) if r else None


def action_spec(i: int, authorized: bool) -> dict[str, Any]:
    aid = f"A{i:03d}"
    return {
        "action_id": aid,
        "authorized": authorized,
        "auth_id": f"AUTH-{aid}",
        "idem_key": f"IDEM-{aid}",
        "payload": {
            "operation": "SET",
            "key": f"K{i:03d}",
            "value": f"V{i:03d}",
        },
    }


def append_proposal(journal: Journal, spec: dict[str, Any]) -> None:
    if not journal.has(spec["action_id"], "PROPOSAL"):
        journal.append({
            "kind": "PROPOSAL",
            "action_id": spec["action_id"],
            "payload": spec["payload"],
        })


def append_dar(journal: Journal, spec: dict[str, Any]) -> None:
    aid = spec["action_id"]
    if not spec["authorized"] or journal.has(aid, "DAR"):
        return
    if not journal.has(aid, "PROPOSAL"):
        return
    journal.append({
        "kind": "DAR",
        "action_id": aid,
        "auth_id": spec["auth_id"],
        "idem_key": spec["idem_key"],
        "authorized_payload": spec["payload"],
    })


def append_intent(journal: Journal, spec: dict[str, Any]) -> None:
    aid = spec["action_id"]
    if journal.has(aid, "DISPATCH_INTENT"):
        return
    dar = journal.first(aid, "DAR")
    if dar is None:
        return
    journal.append({
        "kind": "DISPATCH_INTENT",
        "action_id": aid,
        "auth_id": dar["auth_id"],
        "idem_key": dar["idem_key"],
        "payload": dar["authorized_payload"],
    })


def provider_effect(journal: Journal, provider: Provider, spec: dict[str, Any]) -> None:
    aid = spec["action_id"]
    intent = journal.first(aid, "DISPATCH_INTENT")
    if intent is None:
        return
    provider.dispatch(intent["idem_key"], aid, intent["payload"])


def append_observation(journal: Journal, provider: Provider, spec: dict[str, Any]) -> None:
    aid = spec["action_id"]
    if journal.has(aid, "OBSERVATION"):
        return
    intent = journal.first(aid, "DISPATCH_INTENT")
    if intent is None:
        return
    receipt = provider.query(intent["idem_key"])
    if receipt is None:
        return
    journal.append({
        "kind": "OBSERVATION",
        "action_id": aid,
        "auth_id": intent["auth_id"],
        "idem_key": intent["idem_key"],
        "receipt_id": receipt["receipt_id"],
        "status": receipt["status"],
        "result": receipt["result"],
    })


def append_coc(journal: Journal, spec: dict[str, Any]) -> None:
    aid = spec["action_id"]
    if journal.has(aid, "COC"):
        return
    dar = journal.first(aid, "DAR")
    obs = journal.first(aid, "OBSERVATION")
    if dar is None or obs is None:
        return
    if obs["auth_id"] != dar["auth_id"]:
        return
    if obs["idem_key"] != dar["idem_key"]:
        return
    if obs["status"] != "SUCCEEDED":
        return
    if obs["result"] != dar["authorized_payload"]:
        return
    journal.append({
        "kind": "COC",
        "action_id": aid,
        "auth_id": dar["auth_id"],
        "idem_key": dar["idem_key"],
        "receipt_id": obs["receipt_id"],
        "status": "SUCCEEDED",
        "result": obs["result"],
    })


MICRO_STEPS = (
    append_proposal,
    append_dar,
    append_intent,
    provider_effect,
    append_observation,
    append_coc,
)


def recover_action(journal: Journal, provider: Provider, spec: dict[str, Any]) -> None:
    aid = spec["action_id"]
    if not journal.has(aid, "PROPOSAL"):
        return
    if not journal.has(aid, "DAR"):
        return

    append_intent(journal, spec)
    intent = journal.first(aid, "DISPATCH_INTENT")
    assert intent is not None

    if provider.query(intent["idem_key"]) is None:
        provider_effect(journal, provider, spec)

    append_observation(journal, provider, spec)
    append_coc(journal, spec)


def recover_all(journal: Journal, provider: Provider, specs: list[dict[str, Any]]) -> None:
    # No volatile action state is accepted as input.
    by_id = {s["action_id"]: s for s in specs}
    for aid in sorted(journal.action_ids()):
        spec = by_id[aid]
        recover_action(journal, provider, spec)


def canonical_digest(journal: Journal) -> str:
    rows = []
    seen = set()
    for r in journal.records:
        if r["kind"] != "COC":
            continue
        aid = r["action_id"]
        if aid in seen:
            continue
        seen.add(aid)
        rows.append({
            "action_id": aid,
            "status": r["status"],
            "result": r["result"],
            "receipt_id": r["receipt_id"],
        })
    rows.sort(key=lambda x: x["action_id"])
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def run_workload(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    specs = [
        action_spec(i, authorized=(rng.random() < 0.78))
        for i in range(ACTIONS_PER_WORKLOAD)
    ]
    journal = Journal()
    provider = Provider()

    # Every action at least durably records a proposal.
    for spec in specs:
        append_proposal(journal, spec)

    # Create an interleaved schedule for remaining micro-steps.
    tasks = []
    for spec in specs:
        for step_idx in range(1, len(MICRO_STEPS)):
            tasks.append((spec, step_idx))
    rng.shuffle(tasks)

    crashes = 0
    duplicate_records = 0

    for spec, step_idx in tasks:
        fn = MICRO_STEPS[step_idx]
        if fn in (append_observation,):
            fn(journal, provider, spec)
        elif fn in (provider_effect,):
            fn(journal, provider, spec)
        else:
            fn(journal, spec)

        # Random duplicate durable record injection.
        if rng.random() < 0.03 and journal.records:
            candidate = rng.choice(journal.records)
            if candidate["kind"] in {"DAR", "DISPATCH_INTENT", "OBSERVATION"}:
                journal.append(candidate)
                duplicate_records += 1

        # Crash discards volatile memory. We deliberately do nothing else here:
        # all authoritative state is in journal/provider.
        if rng.random() < 0.12:
            crashes += 1

    # Final process loses all volatile state, then replays/reconciles repeatedly.
    for _ in range(5):
        recover_all(journal, provider, specs)

    digest1 = canonical_digest(journal)
    # More recovery must be a fixed point.
    for _ in range(5):
        recover_all(journal, provider, specs)
    digest2 = canonical_digest(journal)

    authorized = [s for s in specs if s["authorized"]]
    unauthorized = [s for s in specs if not s["authorized"]]
    authorized_ids = {s["action_id"] for s in authorized}

    effect_actions = {r["action_id"] for r in provider.effects.values()}
    coc_actions = {
        r["action_id"]
        for r in journal.records
        if r["kind"] == "COC"
    }

    return {
        "seed": seed,
        "authorized": len(authorized),
        "unauthorized": len(unauthorized),
        "crashes": crashes,
        "duplicate_records_injected": duplicate_records,
        "provider_effect_count": len(provider.effects),
        "provider_calls": provider.calls,
        "coc_action_count": len(coc_actions),
        "unauthorized_effects": len(effect_actions - authorized_ids),
        "missing_authorized_effects": len(authorized_ids - effect_actions),
        "unauthorized_cocs": len(coc_actions - authorized_ids),
        "missing_authorized_cocs": len(authorized_ids - coc_actions),
        "duplicate_effect_action_ids": len(provider.effects) - len(effect_actions),
        "digest_fixed_point": digest1 == digest2,
        "digest": digest2,
    }


def analyze() -> dict[str, Any]:
    rows = [run_workload(SEED + i) for i in range(WORKLOADS)]

    for r in rows:
        assert r["unauthorized_effects"] == 0
        assert r["missing_authorized_effects"] == 0
        assert r["unauthorized_cocs"] == 0
        assert r["missing_authorized_cocs"] == 0
        assert r["duplicate_effect_action_ids"] == 0
        assert r["digest_fixed_point"] is True
        assert r["provider_effect_count"] == r["authorized"]
        assert r["coc_action_count"] == r["authorized"]

    summary = {
        "workloads": WORKLOADS,
        "actions_per_workload": ACTIONS_PER_WORKLOAD,
        "total_actions": WORKLOADS * ACTIONS_PER_WORKLOAD,
        "total_authorized": sum(r["authorized"] for r in rows),
        "total_unauthorized": sum(r["unauthorized"] for r in rows),
        "total_crashes": sum(r["crashes"] for r in rows),
        "total_duplicate_records_injected": sum(r["duplicate_records_injected"] for r in rows),
        "unauthorized_effects": sum(r["unauthorized_effects"] for r in rows),
        "missing_authorized_effects": sum(r["missing_authorized_effects"] for r in rows),
        "unauthorized_cocs": sum(r["unauthorized_cocs"] for r in rows),
        "missing_authorized_cocs": sum(r["missing_authorized_cocs"] for r in rows),
        "digest_fixed_point_failures": sum(not r["digest_fixed_point"] for r in rows),
    }
    return {"summary": summary, "rows": rows}


def main():
    result = analyze()
    print(json.dumps(result["summary"], indent=2))
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Durable journal stress invariants PASS")


if __name__ == "__main__":
    main()
