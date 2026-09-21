#!/usr/bin/env python3
"""Dual-replica recovery: idempotency vs lease/fencing.

Two distinct distributed-runtime problems are tested.

A. Same-action recovery race
   R1 and R2 both recover the same Durable Authorization Record.
   Stable provider idempotency key must guarantee one external effect.

B. Lease handoff stale-owner race
   R1 owns resource lease fence=1 and has authorized command A.
   Lease expires; R2 acquires fence=2 and has authorized command B.
   R1 later resumes and tries to send stale command A.
   Idempotency does NOT help because A and B are different actions.
   Provider fencing must reject R1's stale fence.

The combination gives:
- action deduplication across replicas;
- stale-owner exclusion across lease generations.
"""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT = Path("dual_replica_fencing_analysis.json")


@dataclass
class Lease:
    owner: str | None = None
    fence: int = 0

    def acquire(self, owner: str) -> tuple[str, int]:
        self.fence += 1
        self.owner = owner
        return owner, self.fence

    def expire(self, owner: str) -> None:
        if self.owner == owner:
            self.owner = None


@dataclass
class IdempotentProvider:
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0

    def dispatch(self, idem_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if idem_key in self.effects:
            return copy.deepcopy(self.effects[idem_key])
        receipt = {
            "idem_key": idem_key,
            "receipt_id": f"R-{len(self.effects)+1}",
            "payload": copy.deepcopy(payload),
        }
        self.effects[idem_key] = receipt
        return copy.deepcopy(receipt)


@dataclass
class FencedResource:
    """A mutable external resource accepting commands from lease owners."""

    value: str = "INIT"
    max_fence: int = 0
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    seen_idempotency: dict[str, dict[str, Any]] = field(default_factory=dict)

    def dispatch(
        self,
        *,
        replica: str,
        fence: int,
        action_id: str,
        idem_key: str,
        value: str,
        enforce_fencing: bool,
        enforce_idempotency: bool,
    ) -> dict[str, Any]:
        command = {
            "replica": replica,
            "fence": fence,
            "action_id": action_id,
            "idem_key": idem_key,
            "value": value,
        }

        if enforce_fencing and fence < self.max_fence:
            self.rejected.append({**command, "reason": "STALE_FENCE"})
            return {"status": "REJECTED_STALE_FENCE", **command}

        if enforce_fencing and fence > self.max_fence:
            self.max_fence = fence

        if enforce_idempotency and idem_key in self.seen_idempotency:
            original = self.seen_idempotency[idem_key]
            return {
                "status": "IDEMPOTENT_REPLAY",
                "original": copy.deepcopy(original),
                **command,
            }

        self.value = value
        accepted = {**command, "status": "APPLIED"}
        self.accepted.append(copy.deepcopy(accepted))
        if enforce_idempotency:
            self.seen_idempotency[idem_key] = copy.deepcopy(accepted)
        return accepted


def same_action_recovery_race():
    provider = IdempotentProvider()
    idem = "ACTION-1"
    payload = {"operation": "SET", "key": "MODE", "value": "SAFE"}

    # Both replicas independently recover the same DAR and race.
    r1 = provider.dispatch(idem, payload)
    r2 = provider.dispatch(idem, payload)

    return {
        "provider_calls": provider.calls,
        "effect_count": len(provider.effects),
        "receipt_ids": [r1["receipt_id"], r2["receipt_id"]],
        "same_receipt": r1["receipt_id"] == r2["receipt_id"],
    }


def same_action_without_idempotency():
    effects = []
    payload = {"operation": "SET", "key": "MODE", "value": "SAFE"}
    # Two recovery replicas both execute because provider cannot deduplicate.
    effects.append(copy.deepcopy(payload))
    effects.append(copy.deepcopy(payload))
    return {"effect_count": len(effects)}


def stale_owner_scenario(enforce_fencing: bool):
    lease = Lease()
    resource = FencedResource()

    _, f1 = lease.acquire("R1")

    # R1 holds action A but pauses before dispatch.
    action_a = {
        "replica": "R1",
        "fence": f1,
        "action_id": "A",
        "idem_key": "IDEM-A",
        "value": "VALUE-A",
    }

    # Lease expires and R2 takes over with a new authorization/action.
    lease.expire("R1")
    _, f2 = lease.acquire("R2")
    action_b = {
        "replica": "R2",
        "fence": f2,
        "action_id": "B",
        "idem_key": "IDEM-B",
        "value": "VALUE-B",
    }

    # New owner dispatches first.
    rb = resource.dispatch(
        **action_b,
        enforce_fencing=enforce_fencing,
        enforce_idempotency=True,
    )

    # Old process resumes after failover.
    ra = resource.dispatch(
        **action_a,
        enforce_fencing=enforce_fencing,
        enforce_idempotency=True,
    )

    return {
        "f1": f1,
        "f2": f2,
        "final_value": resource.value,
        "accepted": resource.accepted,
        "rejected": resource.rejected,
        "r2_result": rb,
        "stale_r1_result": ra,
    }


def stale_same_owner_retry_after_handoff():
    """Even duplicate old action replays are rejected by fence after handoff."""
    lease = Lease()
    resource = FencedResource()
    _, f1 = lease.acquire("R1")

    a = dict(
        replica="R1", fence=f1, action_id="A", idem_key="IDEM-A", value="VALUE-A"
    )
    # First action A legitimately executes under fence 1.
    resource.dispatch(**a, enforce_fencing=True, enforce_idempotency=True)

    lease.expire("R1")
    _, f2 = lease.acquire("R2")
    b = dict(
        replica="R2", fence=f2, action_id="B", idem_key="IDEM-B", value="VALUE-B"
    )
    resource.dispatch(**b, enforce_fencing=True, enforce_idempotency=True)

    # Very late duplicate from R1 is stale by lease generation.
    late = resource.dispatch(**a, enforce_fencing=True, enforce_idempotency=True)

    return {
        "final_value": resource.value,
        "accepted": resource.accepted,
        "rejected": resource.rejected,
        "late_result": late,
    }


def handoff_interleavings(enforce_fencing: bool):
    """Enumerate relevant post-handoff command orders.

    Handoff itself has already occurred, so f2 > f1. We vary R2's command B,
    stale R1 command A, and duplicate stale A replay.
    """
    outcomes = []
    for order in itertools.permutations(("B", "A1", "A2")):
        resource = FencedResource(max_fence=2)
        cmds = {
            "B": dict(replica="R2", fence=2, action_id="B", idem_key="IDEM-B", value="VALUE-B"),
            "A1": dict(replica="R1", fence=1, action_id="A", idem_key="IDEM-A", value="VALUE-A"),
            "A2": dict(replica="R1", fence=1, action_id="A", idem_key="IDEM-A", value="VALUE-A"),
        }
        for name in order:
            resource.dispatch(
                **cmds[name],
                enforce_fencing=enforce_fencing,
                enforce_idempotency=True,
            )
        outcomes.append({
            "order": list(order),
            "final_value": resource.value,
            "accepted_actions": [r["action_id"] for r in resource.accepted],
            "rejected_actions": [r["action_id"] for r in resource.rejected],
        })
    return outcomes


def main():
    same = same_action_recovery_race()
    same_no = same_action_without_idempotency()
    no_fence = stale_owner_scenario(False)
    fenced = stale_owner_scenario(True)
    late = stale_same_owner_retry_after_handoff()
    inter_no = handoff_interleavings(False)
    inter_yes = handoff_interleavings(True)

    print("SAME ACTION RACE")
    print("with idempotency", same)
    print("without idempotency", same_no)

    print("\nSTALE OWNER WITHOUT FENCING")
    print(json.dumps(no_fence, indent=2))

    print("\nSTALE OWNER WITH FENCING")
    print(json.dumps(fenced, indent=2))

    print("\nPOST-HANDOFF INTERLEAVINGS")
    print("without fencing")
    for r in inter_no:
        print(r)
    print("with fencing")
    for r in inter_yes:
        print(r)

    assert same["effect_count"] == 1
    assert same["same_receipt"] is True
    assert same_no["effect_count"] == 2

    assert no_fence["final_value"] == "VALUE-A"
    assert len(no_fence["accepted"]) == 2

    assert fenced["final_value"] == "VALUE-B"
    assert [x["action_id"] for x in fenced["accepted"]] == ["B"]
    assert [x["action_id"] for x in fenced["rejected"]] == ["A"]

    assert late["final_value"] == "VALUE-B"
    assert late["late_result"]["status"] == "REJECTED_STALE_FENCE"

    # After handoff, every possible delivery order must leave B as canonical effect
    # when provider enforces fencing.
    assert all(r["final_value"] == "VALUE-B" for r in inter_yes)
    assert all(r["accepted_actions"] == ["B"] for r in inter_yes)

    # Without fencing, stale A may overwrite B depending on delivery order.
    assert len({r["final_value"] for r in inter_no}) > 1

    result = {
        "same_action_with_idempotency": same,
        "same_action_without_idempotency": same_no,
        "stale_owner_without_fencing": no_fence,
        "stale_owner_with_fencing": fenced,
        "late_retry_after_handoff": late,
        "post_handoff_without_fencing": inter_no,
        "post_handoff_with_fencing": inter_yes,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nDual-replica idempotency/fencing invariants PASS")


if __name__ == "__main__":
    main()
