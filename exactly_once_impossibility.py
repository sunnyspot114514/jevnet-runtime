#!/usr/bin/env python3
"""Exactly-once impossibility under an unobservable ambiguous outcome.

A provider has no idempotency key and no query API.

After the first dispatch times out, the runtime sees the exact same local
observation in two possible worlds:

World A: external effect happened, response was lost.
World B: external effect did not happen, response was lost.

Any deterministic recovery decision must be the same in both worlds.

- RETRY: fixes World B, duplicates World A.
- DO_NOT_RETRY: preserves World A, loses World B.

Therefore exactly-once cannot be guaranteed from runtime logic alone when the
external system provides neither idempotency nor a queryable/durable receipt.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path("exactly_once_impossibility.json")

WORLDS = {
    "effect_happened": {
        "hidden_effect_count_after_timeout": 1,
        "observable_runtime_state": "TIMEOUT_NO_RECEIPT",
    },
    "effect_did_not_happen": {
        "hidden_effect_count_after_timeout": 0,
        "observable_runtime_state": "TIMEOUT_NO_RECEIPT",
    },
}

DECISIONS = ("RETRY", "DO_NOT_RETRY")


def outcome(world: dict, decision: str) -> dict:
    count = int(world["hidden_effect_count_after_timeout"])
    if decision == "RETRY":
        # Non-idempotent retry produces another effect.
        count += 1
    elif decision != "DO_NOT_RETRY":
        raise ValueError(decision)

    return {
        "final_effect_count": count,
        "exactly_once": count == 1,
    }


def analyze():
    table = {}
    for decision in DECISIONS:
        table[decision] = {
            name: outcome(world, decision)
            for name, world in WORLDS.items()
        }

    # A policy can only depend on observable state. Both worlds are observationally identical.
    assert len({w["observable_runtime_state"] for w in WORLDS.values()}) == 1

    # Neither possible deterministic decision succeeds in both worlds.
    for decision in DECISIONS:
        assert not all(v["exactly_once"] for v in table[decision].values())

    result = {
        "worlds": WORLDS,
        "decision_table": table,
        "conclusion": (
            "Exactly-once cannot be guaranteed after ambiguous timeout if the provider "
            "offers neither idempotency nor a queryable durable receipt."
        ),
        "sufficient_external_primitives_to_escape_ambiguity": [
            "idempotency key recognized by provider",
            "queryable operation/receipt ID",
            "transactional protocol/outbox with externally visible commit state",
            "compensatable effect with durable compensation identity (gives eventual semantic repair, not literal exactly-once)",
        ],
    }
    return result


def main():
    result = analyze()
    print(json.dumps(result, indent=2))
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
