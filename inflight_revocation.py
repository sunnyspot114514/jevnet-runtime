#!/usr/bin/env python3
"""In-flight authorization revocation and TOCTOU experiment.

Cases:
1. Revocation before local validation -> no dispatch.
2. Revocation after local validation but before provider effect:
   - local-check-only provider incorrectly applies stale command;
   - provider-side authorization fence rejects stale command.
3. Revocation after effect:
   - effect is real and cannot be wished away;
   - compensatable effect -> compensate, canonical REVOKED_COMPENSATED;
   - non-compensatable effect -> canonical REVOKED_AFTER_EFFECT_ESCALATE.

This distinguishes:
- local validation;
- provider-enforced authorization generation/fence;
- post-effect reconciliation.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT = Path("inflight_revocation_analysis.json")


@dataclass
class AuthorizationRegistry:
    generation: int = 0
    active: dict[str, bool] = field(default_factory=dict)

    def issue(self, auth_id: str) -> int:
        self.generation += 1
        self.active[auth_id] = True
        return self.generation

    def revoke(self, auth_id: str) -> int:
        self.generation += 1
        self.active[auth_id] = False
        return self.generation

    def is_active(self, auth_id: str) -> bool:
        return self.active.get(auth_id, False)


@dataclass
class Provider:
    value: str = "INIT"
    min_auth_generation: int = 0
    effects: list[dict[str, Any]] = field(default_factory=list)
    compensations: list[dict[str, Any]] = field(default_factory=list)

    def advance_auth_fence(self, generation: int) -> None:
        self.min_auth_generation = max(self.min_auth_generation, generation)

    def dispatch(
        self,
        *,
        auth_id: str,
        auth_generation: int,
        value: str,
        enforce_provider_fence: bool,
    ) -> dict[str, Any]:
        if enforce_provider_fence and auth_generation < self.min_auth_generation:
            return {
                "status": "REJECTED_REVOKED_AUTH",
                "auth_id": auth_id,
                "auth_generation": auth_generation,
                "provider_min_generation": self.min_auth_generation,
            }

        old = self.value
        self.value = value
        receipt = {
            "status": "APPLIED",
            "auth_id": auth_id,
            "auth_generation": auth_generation,
            "old_value": old,
            "new_value": value,
            "effect_id": f"E{len(self.effects)+1}",
        }
        self.effects.append(copy.deepcopy(receipt))
        return receipt

    def compensate(self, effect_id: str) -> dict[str, Any]:
        effect = next(e for e in self.effects if e["effect_id"] == effect_id)
        self.value = effect["old_value"]
        receipt = {
            "status": "COMPENSATED",
            "effect_id": effect_id,
            "restored_value": effect["old_value"],
            "compensation_id": f"C{len(self.compensations)+1}",
        }
        self.compensations.append(copy.deepcopy(receipt))
        return receipt


AUTH_ID = "AUTH-R"
TARGET_VALUE = "NEW"


def issue_dar(registry: AuthorizationRegistry) -> dict[str, Any]:
    generation = registry.issue(AUTH_ID)
    return {
        "kind": "DAR",
        "auth_id": AUTH_ID,
        "auth_generation": generation,
        "value": TARGET_VALUE,
    }


def revocation_before_validation():
    registry = AuthorizationRegistry()
    provider = Provider()
    dar = issue_dar(registry)
    revoke_gen = registry.revoke(AUTH_ID)
    provider.advance_auth_fence(revoke_gen)

    locally_valid = registry.is_active(AUTH_ID)
    receipt = None
    if locally_valid:
        receipt = provider.dispatch(
            auth_id=dar["auth_id"],
            auth_generation=dar["auth_generation"],
            value=dar["value"],
            enforce_provider_fence=True,
        )

    return {
        "locally_valid": locally_valid,
        "receipt": receipt,
        "effects": len(provider.effects),
        "final_value": provider.value,
    }


def toctou_after_local_check(enforce_provider_fence: bool):
    registry = AuthorizationRegistry()
    provider = Provider()
    dar = issue_dar(registry)

    # Dispatcher validates while auth is active.
    locally_valid = registry.is_active(AUTH_ID)
    assert locally_valid is True

    # Revocation happens before command reaches provider.
    revoke_gen = registry.revoke(AUTH_ID)
    if enforce_provider_fence:
        provider.advance_auth_fence(revoke_gen)

    # Dispatcher is running on stale local knowledge.
    receipt = provider.dispatch(
        auth_id=dar["auth_id"],
        auth_generation=dar["auth_generation"],
        value=dar["value"],
        enforce_provider_fence=enforce_provider_fence,
    )

    return {
        "locally_valid_before_race": locally_valid,
        "revoke_generation": revoke_gen,
        "dar_generation": dar["auth_generation"],
        "receipt": receipt,
        "effects": len(provider.effects),
        "final_value": provider.value,
    }


def revocation_after_effect(compensatable: bool):
    registry = AuthorizationRegistry()
    provider = Provider()
    dar = issue_dar(registry)

    # Legitimate effect occurs while authorization is active.
    provider.advance_auth_fence(dar["auth_generation"])
    effect = provider.dispatch(
        auth_id=dar["auth_id"],
        auth_generation=dar["auth_generation"],
        value=dar["value"],
        enforce_provider_fence=True,
    )
    assert effect["status"] == "APPLIED"

    # Revocation is later than the real effect.
    revoke_gen = registry.revoke(AUTH_ID)
    provider.advance_auth_fence(revoke_gen)

    if compensatable:
        comp = provider.compensate(effect["effect_id"])
        canonical = {
            "status": "REVOKED_COMPENSATED",
            "effect_id": effect["effect_id"],
            "compensation_id": comp["compensation_id"],
            "final_value": provider.value,
        }
    else:
        canonical = {
            "status": "REVOKED_AFTER_EFFECT_ESCALATE",
            "effect_id": effect["effect_id"],
            "compensation_id": "NONE",
            "final_value": provider.value,
        }

    return {
        "effect": effect,
        "revocation_generation": revoke_gen,
        "compensatable": compensatable,
        "compensations": len(provider.compensations),
        "canonical": canonical,
    }


def main():
    before = revocation_before_validation()
    local_only = toctou_after_local_check(False)
    fenced = toctou_after_local_check(True)
    after_comp = revocation_after_effect(True)
    after_no_comp = revocation_after_effect(False)

    result = {
        "revocation_before_validation": before,
        "toctou_local_check_only": local_only,
        "toctou_provider_fenced": fenced,
        "revocation_after_effect_compensatable": after_comp,
        "revocation_after_effect_noncompensatable": after_no_comp,
    }

    print(json.dumps(result, indent=2))

    assert before["effects"] == 0

    # Local validation alone is TOCTOU-vulnerable.
    assert local_only["receipt"]["status"] == "APPLIED"
    assert local_only["effects"] == 1
    assert local_only["final_value"] == TARGET_VALUE

    # Provider-side auth fence closes the race.
    assert fenced["receipt"]["status"] == "REJECTED_REVOKED_AUTH"
    assert fenced["effects"] == 0
    assert fenced["final_value"] == "INIT"

    # Post-effect revoke needs reconciliation, not retroactive denial.
    assert after_comp["canonical"]["status"] == "REVOKED_COMPENSATED"
    assert after_comp["canonical"]["final_value"] == "INIT"
    assert after_comp["compensations"] == 1

    assert after_no_comp["canonical"]["status"] == "REVOKED_AFTER_EFFECT_ESCALATE"
    assert after_no_comp["canonical"]["final_value"] == TARGET_VALUE
    assert after_no_comp["compensations"] == 0

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nIn-flight revocation invariants PASS")


if __name__ == "__main__":
    main()
