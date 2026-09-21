#!/usr/bin/env python3
"""Crash/restart recovery experiment for a durable agent runtime.

The experiment models one side-effecting action with:
Proposal -> Validation -> DAR -> Dispatch Intent -> Provider Effect
-> Observation -> Reconciliation -> Canonical Outcome Commit (COC)

All volatile memory may disappear after ANY durable/effect step.

Recovery is permitted to use only:
- durable runtime records;
- provider state queried by idempotency key.

Goal:
- exactly-once external effect;
- identical canonical outcome after recovery;
- no effect without Durable Authorization Record;
- no duplicate effect across repeated recovery.
"""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT = Path("crash_recovery_analysis.json")


@dataclass
class Provider:
    """External provider with idempotent dispatch."""

    effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    call_count: int = 0

    def dispatch(self, idem_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        if idem_key in self.effects:
            return copy.deepcopy(self.effects[idem_key])
        receipt = {
            "idem_key": idem_key,
            "provider_status": "SUCCEEDED",
            "provider_result": copy.deepcopy(payload),
            "receipt_id": f"R-{len(self.effects)+1}",
        }
        self.effects[idem_key] = receipt
        return copy.deepcopy(receipt)

    def query(self, idem_key: str) -> dict[str, Any] | None:
        if idem_key not in self.effects:
            return None
        return copy.deepcopy(self.effects[idem_key])


@dataclass
class DurableLog:
    records: list[dict[str, Any]] = field(default_factory=list)

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(copy.deepcopy(record))

    def find(self, kind: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["kind"] == kind]

    def first(self, kind: str) -> dict[str, Any] | None:
        rows = self.find(kind)
        return rows[0] if rows else None

    def has(self, kind: str) -> bool:
        return self.first(kind) is not None


ACTION_ID = "ACT-7"
AUTH_ID = "AUTH-7"
IDEM_KEY = "IDEM-ACT-7"
PAYLOAD = {"operation": "SET", "key": "MODE", "value": "SAFE"}


def base_log() -> DurableLog:
    log = DurableLog()
    log.append({
        "kind": "PROPOSAL",
        "action_id": ACTION_ID,
        "payload": PAYLOAD,
    })
    return log


def validate_and_authorize(log: DurableLog) -> None:
    if log.has("DAR"):
        return
    proposal = log.first("PROPOSAL")
    if proposal is None:
        return
    log.append({
        "kind": "DAR",
        "action_id": ACTION_ID,
        "auth_id": AUTH_ID,
        "idem_key": IDEM_KEY,
        "authorized_payload": proposal["payload"],
        "auth_seq": 10,
    })


def durable_dispatch_intent(log: DurableLog) -> None:
    if log.has("DISPATCH_INTENT"):
        return
    dar = log.first("DAR")
    if dar is None:
        return
    log.append({
        "kind": "DISPATCH_INTENT",
        "action_id": ACTION_ID,
        "auth_id": dar["auth_id"],
        "idem_key": dar["idem_key"],
        "payload": dar["authorized_payload"],
    })


def perform_external_dispatch(log: DurableLog, provider: Provider) -> None:
    intent = log.first("DISPATCH_INTENT")
    if intent is None:
        return
    provider.dispatch(intent["idem_key"], intent["payload"])


def durable_observation(log: DurableLog, provider: Provider) -> None:
    if log.has("OBSERVATION"):
        return
    intent = log.first("DISPATCH_INTENT")
    if intent is None:
        return
    receipt = provider.query(intent["idem_key"])
    if receipt is None:
        return
    log.append({
        "kind": "OBSERVATION",
        "action_id": ACTION_ID,
        "auth_id": intent["auth_id"],
        "idem_key": intent["idem_key"],
        "receipt_id": receipt["receipt_id"],
        "provider_status": receipt["provider_status"],
        "provider_result": receipt["provider_result"],
    })


def canonical_commit(log: DurableLog) -> None:
    if log.has("COC"):
        return
    dar = log.first("DAR")
    obs = log.first("OBSERVATION")
    if dar is None or obs is None:
        return

    # Reconciliation: receipt must bind to durable authorization.
    if obs["auth_id"] != dar["auth_id"]:
        return
    if obs["idem_key"] != dar["idem_key"]:
        return
    if obs["provider_status"] != "SUCCEEDED":
        return
    if obs["provider_result"] != dar["authorized_payload"]:
        return

    log.append({
        "kind": "COC",
        "action_id": ACTION_ID,
        "auth_id": dar["auth_id"],
        "idem_key": dar["idem_key"],
        "canonical_status": "SUCCEEDED",
        "canonical_result": obs["provider_result"],
        "receipt_id": obs["receipt_id"],
    })


def recover(log: DurableLog, provider: Provider) -> None:
    """Idempotent recovery from durable state only."""
    if not log.has("PROPOSAL"):
        return

    # Proposal without authorization has no effect authority.
    if not log.has("DAR"):
        return

    durable_dispatch_intent(log)

    # If an effect is already visible at provider, never blindly re-execute.
    intent = log.first("DISPATCH_INTENT")
    assert intent is not None
    receipt = provider.query(intent["idem_key"])
    if receipt is None:
        perform_external_dispatch(log, provider)

    durable_observation(log, provider)
    canonical_commit(log)


STEPS = (
    "PROPOSAL",
    "DAR",
    "DISPATCH_INTENT",
    "PROVIDER_EFFECT",
    "OBSERVATION",
    "COC",
)


def run_until(cut: int) -> tuple[DurableLog, Provider]:
    """Execute first 'cut' workflow steps, then crash."""
    log = DurableLog()
    provider = Provider()
    actions = [
        lambda: log.append({"kind": "PROPOSAL", "action_id": ACTION_ID, "payload": PAYLOAD}),
        lambda: validate_and_authorize(log),
        lambda: durable_dispatch_intent(log),
        lambda: perform_external_dispatch(log, provider),
        lambda: durable_observation(log, provider),
        lambda: canonical_commit(log),
    ]
    for fn in actions[:cut]:
        fn()
    return log, provider


def canonical_tuple(log: DurableLog) -> tuple[Any, ...] | None:
    coc = log.first("COC")
    if coc is None:
        return None
    return (
        coc["canonical_status"],
        coc["canonical_result"]["operation"],
        coc["canonical_result"]["key"],
        coc["canonical_result"]["value"],
        coc["receipt_id"],
    )


def analyze() -> dict[str, Any]:
    rows = []

    # Crash after every cut point from before proposal to after COC.
    for cut in range(0, len(STEPS) + 1):
        log, provider = run_until(cut)
        before_records = len(log.records)
        before_effects = len(provider.effects)
        before_calls = provider.call_count

        # Recover repeatedly to test idempotence.
        for _ in range(5):
            recover(log, provider)

        rows.append({
            "cut": cut,
            "after_step": "START" if cut == 0 else STEPS[cut - 1],
            "before_records": before_records,
            "before_effects": before_effects,
            "before_provider_calls": before_calls,
            "after_records": len(log.records),
            "after_effects": len(provider.effects),
            "after_provider_calls": provider.call_count,
            "canonical": canonical_tuple(log),
            "record_kinds": [r["kind"] for r in log.records],
        })

    # Duplicate durable records should not change recovery outcome.
    dup_log, dup_provider = run_until(5)  # through OBSERVATION
    for kind in ("DAR", "DISPATCH_INTENT", "OBSERVATION"):
        r = dup_log.first(kind)
        if r:
            dup_log.append(r)
    for _ in range(5):
        recover(dup_log, dup_provider)

    duplicate_case = {
        "canonical": canonical_tuple(dup_log),
        "effects": len(dup_provider.effects),
        "provider_calls": dup_provider.call_count,
        "record_kinds": [r["kind"] for r in dup_log.records],
    }

    # Unauthorized proposal must remain effect-free even after repeated recovery.
    unauth = base_log()
    unauth_provider = Provider()
    for _ in range(10):
        recover(unauth, unauth_provider)
    unauthorized_case = {
        "effects": len(unauth_provider.effects),
        "provider_calls": unauth_provider.call_count,
        "canonical": canonical_tuple(unauth),
        "record_kinds": [r["kind"] for r in unauth.records],
    }

    return {
        "steps": list(STEPS),
        "crash_rows": rows,
        "duplicate_record_case": duplicate_case,
        "unauthorized_case": unauthorized_case,
    }


def main():
    result = analyze()

    print("=== CRASH CUTS ===")
    for r in result["crash_rows"]:
        print(
            f"cut={r['cut']} after={r['after_step']:15s} "
            f"effects {r['before_effects']}->{r['after_effects']} "
            f"calls {r['before_provider_calls']}->{r['after_provider_calls']} "
            f"canonical={r['canonical']}"
        )

    print("\nDUPLICATE RECORD CASE")
    print(result["duplicate_record_case"])

    print("\nUNAUTHORIZED CASE")
    print(result["unauthorized_case"])

    # Cuts before DAR cannot legally progress.
    for r in result["crash_rows"]:
        if r["cut"] <= 1:
            assert r["after_effects"] == 0
            assert r["canonical"] is None
        else:
            assert r["after_effects"] == 1
            assert r["canonical"] == ("SUCCEEDED", "SET", "MODE", "SAFE", "R-1")

    assert result["duplicate_record_case"]["effects"] == 1
    assert result["duplicate_record_case"]["canonical"] == ("SUCCEEDED", "SET", "MODE", "SAFE", "R-1")
    assert result["unauthorized_case"]["effects"] == 0
    assert result["unauthorized_case"]["canonical"] is None

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nCrash/restart invariants PASS")


if __name__ == "__main__":
    main()
