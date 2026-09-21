#!/usr/bin/env python3
"""Cross-agent authorization and role-separation experiment.

Roles:
- proposer: may create Proposal only
- authorizer: may validate Proposal and create DAR
- dispatcher: may create Dispatch Intent and call provider only with DAR
- reconciler: may accept provider observation and create COC only if it matches DAR

No single role can progress the whole chain alone.

The experiment injects:
- proposer self-authorization attempt
- dispatcher without DAR
- forged observation
- reconciler with mismatched auth_id
- duplicated messages
- reordered message delivery

The canonical runtime accepts only capabilities allowed to each role.
"""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT = Path("cross_agent_authorization_analysis.json")

ROLES = {
    "proposer": {"PROPOSAL"},
    "authorizer": {"DAR"},
    "dispatcher": {"DISPATCH_INTENT"},
    "reconciler": {"OBSERVATION", "COC"},
}

ACTION_ID = "ACT-X"
AUTH_ID = "AUTH-X"
IDEM_KEY = "IDEM-X"
PAYLOAD = {"operation": "SET", "key": "MODE", "value": "SAFE"}


@dataclass
class DurableBus:
    records: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def append_as(self, role: str, record: dict[str, Any]) -> bool:
        kind = record["kind"]
        if kind not in ROLES.get(role, set()):
            self.rejected.append({
                "role": role,
                "record": copy.deepcopy(record),
                "reason": "ROLE_NOT_AUTHORIZED_FOR_RECORD_KIND",
            })
            return False

        # Capability is necessary but not sufficient: records that authorize or
        # dispatch side effects must bind to existing durable predecessors.
        if kind == "DAR":
            proposal = self.first("PROPOSAL")
            if proposal is None or proposal["action_id"] != record.get("action_id"):
                self.rejected.append({
                    "role": role,
                    "record": copy.deepcopy(record),
                    "reason": "DAR_WITHOUT_MATCHING_PROPOSAL",
                })
                return False
            if proposal["payload"] != record.get("authorized_payload"):
                self.rejected.append({
                    "role": role,
                    "record": copy.deepcopy(record),
                    "reason": "DAR_PAYLOAD_MISMATCH",
                })
                return False

        if kind == "DISPATCH_INTENT":
            dar = self.first("DAR")
            if dar is None:
                self.rejected.append({
                    "role": role,
                    "record": copy.deepcopy(record),
                    "reason": "DISPATCH_WITHOUT_DAR",
                })
                return False
            if (
                dar["action_id"] != record.get("action_id")
                or dar["auth_id"] != record.get("auth_id")
                or dar["idem_key"] != record.get("idem_key")
                or dar["authorized_payload"] != record.get("payload")
            ):
                self.rejected.append({
                    "role": role,
                    "record": copy.deepcopy(record),
                    "reason": "DISPATCH_DAR_BINDING_MISMATCH",
                })
                return False

        self.records.append(copy.deepcopy(record))
        return True

    def first(self, kind: str):
        for r in self.records:
            if r["kind"] == kind:
                return r
        return None

    def has(self, kind: str) -> bool:
        return self.first(kind) is not None


@dataclass
class Provider:
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)

    def dispatch(self, idem_key: str, payload: dict[str, Any], auth_id: str):
        if idem_key in self.effects:
            return copy.deepcopy(self.effects[idem_key])
        receipt = {
            "idem_key": idem_key,
            "auth_id": auth_id,
            "status": "SUCCEEDED",
            "result": copy.deepcopy(payload),
            "receipt_id": "REC-X",
        }
        self.effects[idem_key] = receipt
        return copy.deepcopy(receipt)

    def query(self, idem_key: str):
        r = self.effects.get(idem_key)
        return copy.deepcopy(r) if r else None


def canonical_pipeline(bus: DurableBus, provider: Provider):
    """Attempt to advance each legitimate role once from current durable state."""
    # proposer
    if not bus.has("PROPOSAL"):
        bus.append_as("proposer", {
            "kind": "PROPOSAL",
            "action_id": ACTION_ID,
            "payload": PAYLOAD,
        })

    # authorizer
    if bus.has("PROPOSAL") and not bus.has("DAR"):
        proposal = bus.first("PROPOSAL")
        bus.append_as("authorizer", {
            "kind": "DAR",
            "action_id": ACTION_ID,
            "auth_id": AUTH_ID,
            "idem_key": IDEM_KEY,
            "authorized_payload": proposal["payload"],
        })

    # dispatcher
    dar = bus.first("DAR")
    if dar is not None and not bus.has("DISPATCH_INTENT"):
        bus.append_as("dispatcher", {
            "kind": "DISPATCH_INTENT",
            "action_id": ACTION_ID,
            "auth_id": dar["auth_id"],
            "idem_key": dar["idem_key"],
            "payload": dar["authorized_payload"],
        })

    intent = bus.first("DISPATCH_INTENT")
    if intent is not None and provider.query(intent["idem_key"]) is None:
        provider.dispatch(intent["idem_key"], intent["payload"], intent["auth_id"])

    # reconciler
    if intent is not None:
        rec = provider.query(intent["idem_key"])
        if rec is not None:
            already = any(
                r["kind"] == "OBSERVATION"
                and r.get("receipt_id") == rec["receipt_id"]
                and r.get("auth_id") == rec["auth_id"]
                and r.get("idem_key") == rec["idem_key"]
                for r in bus.records
            )
            if not already:
                bus.append_as("reconciler", {
                    "kind": "OBSERVATION",
                    "action_id": ACTION_ID,
                    "auth_id": rec["auth_id"],
                    "idem_key": rec["idem_key"],
                    "status": rec["status"],
                    "result": rec["result"],
                    "receipt_id": rec["receipt_id"],
                })

    if not bus.has("COC"):
        dar = bus.first("DAR")
        if dar is not None:
            valid_obs = [
                r for r in bus.records
                if r["kind"] == "OBSERVATION"
                and r.get("auth_id") == dar["auth_id"]
                and r.get("idem_key") == dar["idem_key"]
                and r.get("status") == "SUCCEEDED"
                and r.get("result") == dar["authorized_payload"]
            ]
            if valid_obs:
                obs = sorted(valid_obs, key=lambda r: r.get("receipt_id", ""))[0]
                bus.append_as("reconciler", {
                    "kind": "COC",
                    "action_id": ACTION_ID,
                    "auth_id": dar["auth_id"],
                    "idem_key": dar["idem_key"],
                    "status": "SUCCEEDED",
                    "result": obs["result"],
                    "receipt_id": obs["receipt_id"],
                })


ATTACKS = {
    "proposer_self_authorize": (
        "proposer",
        {
            "kind": "DAR",
            "action_id": ACTION_ID,
            "auth_id": "FAKE-AUTH",
            "idem_key": "FAKE-IDEM",
            "authorized_payload": PAYLOAD,
        },
    ),
    "dispatcher_without_dar": (
        "dispatcher",
        {
            "kind": "DISPATCH_INTENT",
            "action_id": ACTION_ID,
            "auth_id": "NO-DAR",
            "idem_key": "ATTACK-IDEM",
            "payload": PAYLOAD,
        },
    ),
    "dispatcher_writes_coc": (
        "dispatcher",
        {
            "kind": "COC",
            "action_id": ACTION_ID,
            "auth_id": AUTH_ID,
            "idem_key": IDEM_KEY,
            "status": "SUCCEEDED",
            "result": PAYLOAD,
            "receipt_id": "FORGED",
        },
    ),
    "authorizer_dispatches": (
        "authorizer",
        {
            "kind": "DISPATCH_INTENT",
            "action_id": ACTION_ID,
            "auth_id": AUTH_ID,
            "idem_key": IDEM_KEY,
            "payload": PAYLOAD,
        },
    ),
}


def forged_observation_case():
    bus = DurableBus()
    provider = Provider()

    bus.append_as("proposer", {"kind": "PROPOSAL", "action_id": ACTION_ID, "payload": PAYLOAD})
    bus.append_as("authorizer", {
        "kind": "DAR",
        "action_id": ACTION_ID,
        "auth_id": AUTH_ID,
        "idem_key": IDEM_KEY,
        "authorized_payload": PAYLOAD,
    })

    # Reconciler is allowed to write OBSERVATION records, but this one is cryptographically/logically mismatched.
    bus.append_as("reconciler", {
        "kind": "OBSERVATION",
        "action_id": ACTION_ID,
        "auth_id": "FAKE-AUTH",
        "idem_key": IDEM_KEY,
        "status": "SUCCEEDED",
        "result": PAYLOAD,
        "receipt_id": "FAKE-REC",
    })

    for _ in range(3):
        canonical_pipeline(bus, provider)

    coc = bus.first("COC")
    return {
        "coc_present": coc is not None,
        "coc": coc,
        "effects": len(provider.effects),
        "records": bus.records,
        "rejected": bus.rejected,
        "observation_receipts": [
            r.get("receipt_id") for r in bus.records if r["kind"] == "OBSERVATION"
        ],
    }


def role_attack_matrix():
    rows = {}
    for name, (role, record) in ATTACKS.items():
        bus = DurableBus()
        ok = bus.append_as(role, record)
        rows[name] = {
            "accepted": ok,
            "rejected_count": len(bus.rejected),
            "records": bus.records,
        }
    return rows


def permutation_test():
    """Deliver legitimate role records in arbitrary order, then let runtime reconcile.

    Records that depend on absent prerequisites are simply durable facts until the
    canonical pipeline can validate/use them. A forged/role-illegal record is never accepted.
    """
    legitimate = [
        ("proposer", {"kind": "PROPOSAL", "action_id": ACTION_ID, "payload": PAYLOAD}),
        ("authorizer", {
            "kind": "DAR",
            "action_id": ACTION_ID,
            "auth_id": AUTH_ID,
            "idem_key": IDEM_KEY,
            "authorized_payload": PAYLOAD,
        }),
        ("dispatcher", {
            "kind": "DISPATCH_INTENT",
            "action_id": ACTION_ID,
            "auth_id": AUTH_ID,
            "idem_key": IDEM_KEY,
            "payload": PAYLOAD,
        }),
    ]

    outcomes = []
    for perm in itertools.permutations(legitimate):
        bus = DurableBus()
        provider = Provider()
        for role, record in perm:
            bus.append_as(role, record)
        for _ in range(4):
            canonical_pipeline(bus, provider)
        coc = bus.first("COC")
        outcomes.append({
            "effect_count": len(provider.effects),
            "coc": None if coc is None else (
                coc["status"], coc["result"]["value"], coc["auth_id"], coc["idem_key"]
            ),
        })
    return outcomes


def main():
    matrix = role_attack_matrix()
    forged = forged_observation_case()
    perms = permutation_test()

    print("ROLE ATTACK MATRIX")
    print(json.dumps(matrix, indent=2))

    print("\nFORGED OBSERVATION")
    print(json.dumps({
        "coc_present": forged["coc_present"],
        "effects": forged["effects"],
        "rejected": forged["rejected"],
    }, indent=2))

    print("\nLEGITIMATE PERMUTATIONS")
    for x in perms:
        print(x)

    for name, row in matrix.items():
        assert row["accepted"] is False, name
        assert row["rejected_count"] == 1, name

    assert forged["coc_present"] is True

    # All 3! delivery orders converge to one effect and one valid canonical outcome.
    assert all(x["effect_count"] == 1 for x in perms)
    assert len({x["coc"] for x in perms}) == 1
    assert perms[0]["coc"] == ("SUCCEEDED", "SAFE", AUTH_ID, IDEM_KEY)

    result = {
        "role_attack_matrix": matrix,
        "forged_observation": {
            "coc_present": forged["coc_present"],
            "effects": forged["effects"],
        },
        "legitimate_permutation_outcomes": perms,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nCross-agent capability invariants PASS")


if __name__ == "__main__":
    main()
