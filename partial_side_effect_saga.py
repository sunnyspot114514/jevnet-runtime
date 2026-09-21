#!/usr/bin/env python3
"""Partial side-effect / compensation experiment.

Workflow:
  authorize order
  -> reserve inventory
  -> charge payment
  -> canonical success

Failure modes:
- charge succeeds externally but response times out (ambiguous outcome)
- charge hard-fails after inventory reservation
- crash after reserve
- crash after charge effect but before observation
- compensation succeeds but response times out

Naive runtime:
- retries ambiguous charge without idempotent reconciliation;
- does not compensate leaked inventory on terminal payment failure.

Robust runtime:
- durable step intents;
- per-step idempotency keys;
- query-before-retry for ambiguous outcomes;
- compensation intent + idempotent release;
- canonical success/failure only after reconciliation.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT = Path("partial_side_effect_analysis.json")


class AmbiguousTimeout(Exception):
    pass


@dataclass
class Inventory:
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    releases: dict[str, dict[str, Any]] = field(default_factory=dict)
    reserve_calls: int = 0
    release_calls: int = 0

    def reserve(self, idem_key: str, order_id: str, sku: str) -> dict[str, Any]:
        self.reserve_calls += 1
        if idem_key in self.reservations:
            return copy.deepcopy(self.reservations[idem_key])
        receipt = {
            "reservation_id": f"RES-{len(self.reservations)+1}",
            "idem_key": idem_key,
            "order_id": order_id,
            "sku": sku,
            "status": "RESERVED",
        }
        self.reservations[idem_key] = receipt
        return copy.deepcopy(receipt)

    def query_reserve(self, idem_key: str) -> dict[str, Any] | None:
        r = self.reservations.get(idem_key)
        return copy.deepcopy(r) if r else None

    def release(self, idem_key: str, reservation_id: str, ambiguous_timeout: bool = False) -> dict[str, Any]:
        self.release_calls += 1
        if idem_key in self.releases:
            receipt = copy.deepcopy(self.releases[idem_key])
            if ambiguous_timeout:
                raise AmbiguousTimeout("release response lost")
            return receipt
        receipt = {
            "release_id": f"REL-{len(self.releases)+1}",
            "idem_key": idem_key,
            "reservation_id": reservation_id,
            "status": "RELEASED",
        }
        self.releases[idem_key] = receipt
        if ambiguous_timeout:
            raise AmbiguousTimeout("release response lost")
        return copy.deepcopy(receipt)

    def query_release(self, idem_key: str) -> dict[str, Any] | None:
        r = self.releases.get(idem_key)
        return copy.deepcopy(r) if r else None

    def active_reservations(self) -> int:
        released_ids = {r["reservation_id"] for r in self.releases.values()}
        return sum(
            r["reservation_id"] not in released_ids
            for r in self.reservations.values()
        )


@dataclass
class Payment:
    charges: dict[str, dict[str, Any]] = field(default_factory=dict)
    naive_charges: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0

    def charge_idempotent(
        self,
        idem_key: str,
        order_id: str,
        amount: int,
        mode: str = "success",
    ) -> dict[str, Any]:
        self.calls += 1
        if idem_key in self.charges:
            return copy.deepcopy(self.charges[idem_key])

        if mode == "hard_fail":
            return {
                "idem_key": idem_key,
                "order_id": order_id,
                "amount": amount,
                "status": "FAILED",
                "charge_id": "NONE",
            }

        receipt = {
            "idem_key": idem_key,
            "order_id": order_id,
            "amount": amount,
            "status": "SUCCEEDED",
            "charge_id": f"CHG-{len(self.charges)+1}",
        }
        self.charges[idem_key] = receipt
        if mode == "success_timeout":
            raise AmbiguousTimeout("charge succeeded but response lost")
        return copy.deepcopy(receipt)

    def query(self, idem_key: str) -> dict[str, Any] | None:
        r = self.charges.get(idem_key)
        return copy.deepcopy(r) if r else None

    def charge_naive(self, order_id: str, amount: int, mode: str = "success") -> dict[str, Any]:
        self.calls += 1
        if mode == "hard_fail":
            return {
                "order_id": order_id,
                "amount": amount,
                "status": "FAILED",
                "charge_id": "NONE",
            }

        receipt = {
            "order_id": order_id,
            "amount": amount,
            "status": "SUCCEEDED",
            "charge_id": f"NCHG-{len(self.naive_charges)+1}",
        }
        self.naive_charges.append(receipt)
        if mode == "success_timeout":
            raise AmbiguousTimeout("charge succeeded but response lost")
        return copy.deepcopy(receipt)

    def total_successful_effects(self) -> int:
        return len(self.charges) + len(self.naive_charges)


@dataclass
class Log:
    records: list[dict[str, Any]] = field(default_factory=list)

    def append(self, r: dict[str, Any]) -> None:
        self.records.append(copy.deepcopy(r))

    def first(self, kind: str) -> dict[str, Any] | None:
        for r in self.records:
            if r["kind"] == kind:
                return r
        return None

    def has(self, kind: str) -> bool:
        return self.first(kind) is not None


ORDER_ID = "ORDER-7"
SKU = "SKU-A"
AMOUNT = 100
INV_IDEM = "ORDER-7:reserve"
PAY_IDEM = "ORDER-7:charge"
REL_IDEM = "ORDER-7:release"


def robust_log() -> Log:
    log = Log()
    log.append({
        "kind": "DAR",
        "order_id": ORDER_ID,
        "authorized": {
            "sku": SKU,
            "amount": AMOUNT,
        },
    })
    return log


def robust_recover(
    log: Log,
    inventory: Inventory,
    payment: Payment,
    *,
    payment_mode: str,
    release_timeout_once: bool = False,
) -> None:
    """One idempotent recovery/advance iteration."""
    dar = log.first("DAR")
    if dar is None or log.has("COC_SUCCESS") or log.has("COC_FAILED"):
        return

    # Step 1: inventory reserve.
    if not log.has("RESERVE_INTENT"):
        log.append({"kind": "RESERVE_INTENT", "idem_key": INV_IDEM})

    reserve = inventory.query_reserve(INV_IDEM)
    if reserve is None:
        reserve = inventory.reserve(INV_IDEM, ORDER_ID, SKU)

    if not log.has("RESERVE_OBS"):
        log.append({"kind": "RESERVE_OBS", "receipt": reserve})

    # Step 2: payment.
    if not log.has("CHARGE_INTENT"):
        log.append({"kind": "CHARGE_INTENT", "idem_key": PAY_IDEM})

    charge = payment.query(PAY_IDEM)
    if charge is None and not log.has("CHARGE_FAILED"):
        try:
            charge = payment.charge_idempotent(
                PAY_IDEM,
                ORDER_ID,
                AMOUNT,
                mode=payment_mode,
            )
        except AmbiguousTimeout:
            # Critical rule: timeout is UNKNOWN, not failure.
            charge = payment.query(PAY_IDEM)

    if charge is not None and charge["status"] == "SUCCEEDED":
        if not log.has("CHARGE_OBS"):
            log.append({"kind": "CHARGE_OBS", "receipt": charge})
        log.append({
            "kind": "COC_SUCCESS",
            "order_id": ORDER_ID,
            "reservation_id": reserve["reservation_id"],
            "charge_id": charge["charge_id"],
        })
        return

    if charge is not None and charge["status"] == "FAILED" and not log.has("CHARGE_FAILED"):
        log.append({"kind": "CHARGE_FAILED", "receipt": charge})

    # Terminal payment failure -> compensation.
    if log.has("CHARGE_FAILED"):
        if not log.has("RELEASE_INTENT"):
            log.append({
                "kind": "RELEASE_INTENT",
                "idem_key": REL_IDEM,
                "reservation_id": reserve["reservation_id"],
            })

        release = inventory.query_release(REL_IDEM)
        if release is None:
            try:
                release = inventory.release(
                    REL_IDEM,
                    reserve["reservation_id"],
                    ambiguous_timeout=release_timeout_once and not log.has("RELEASE_TIMEOUT_SEEN"),
                )
            except AmbiguousTimeout:
                log.append({"kind": "RELEASE_TIMEOUT_SEEN"})
                release = inventory.query_release(REL_IDEM)

        if release is not None:
            if not log.has("RELEASE_OBS"):
                log.append({"kind": "RELEASE_OBS", "receipt": release})
            log.append({
                "kind": "COC_FAILED",
                "order_id": ORDER_ID,
                "reason": "PAYMENT_FAILED_COMPENSATED",
                "release_id": release["release_id"],
            })


def naive_success_timeout() -> dict[str, Any]:
    inv = Inventory()
    pay = Payment()
    reserve = inv.reserve("naive-reserve", ORDER_ID, SKU)

    try:
        pay.charge_naive(ORDER_ID, AMOUNT, mode="success_timeout")
    except AmbiguousTimeout:
        # Naive runtime treats timeout as failure and retries with no idempotency key.
        second = pay.charge_naive(ORDER_ID, AMOUNT, mode="success")

    return {
        "active_reservations": inv.active_reservations(),
        "successful_charges": len(pay.naive_charges),
        "charge_ids": [c["charge_id"] for c in pay.naive_charges],
        "reservation_id": reserve["reservation_id"],
    }


def naive_hard_failure() -> dict[str, Any]:
    inv = Inventory()
    pay = Payment()
    reserve = inv.reserve("naive-reserve", ORDER_ID, SKU)
    charge = pay.charge_naive(ORDER_ID, AMOUNT, mode="hard_fail")
    # No compensation.
    return {
        "active_reservations": inv.active_reservations(),
        "successful_charges": len(pay.naive_charges),
        "payment_status": charge["status"],
        "reservation_id": reserve["reservation_id"],
    }


def run_robust_scenario(payment_mode: str, release_timeout_once: bool = False) -> dict[str, Any]:
    log = robust_log()
    inv = Inventory()
    pay = Payment()

    # Repeated crashes/restarts are equivalent to repeated recovery iterations.
    for _ in range(8):
        robust_recover(
            log,
            inv,
            pay,
            payment_mode=payment_mode,
            release_timeout_once=release_timeout_once,
        )

    coc_success = log.first("COC_SUCCESS")
    coc_failed = log.first("COC_FAILED")
    return {
        "record_kinds": [r["kind"] for r in log.records],
        "success": coc_success is not None,
        "failed": coc_failed is not None,
        "canonical": coc_success or coc_failed,
        "active_reservations": inv.active_reservations(),
        "idempotent_charges": len(pay.charges),
        "payment_calls": pay.calls,
        "reserve_effects": len(inv.reservations),
        "release_effects": len(inv.releases),
        "reserve_calls": inv.reserve_calls,
        "release_calls": inv.release_calls,
    }


def analyze() -> dict[str, Any]:
    result = {
        "naive": {
            "success_timeout": naive_success_timeout(),
            "hard_failure": naive_hard_failure(),
        },
        "robust": {
            "success": run_robust_scenario("success"),
            "success_timeout": run_robust_scenario("success_timeout"),
            "hard_failure": run_robust_scenario("hard_fail"),
            "hard_failure_release_timeout": run_robust_scenario(
                "hard_fail",
                release_timeout_once=True,
            ),
        },
    }

    # Naive failures.
    assert result["naive"]["success_timeout"]["successful_charges"] == 2
    assert result["naive"]["hard_failure"]["active_reservations"] == 1

    # Robust success.
    for name in ("success", "success_timeout"):
        r = result["robust"][name]
        assert r["success"] is True
        assert r["failed"] is False
        assert r["idempotent_charges"] == 1
        assert r["active_reservations"] == 1
        assert r["release_effects"] == 0

    # Robust terminal failure must compensate exactly once.
    for name in ("hard_failure", "hard_failure_release_timeout"):
        r = result["robust"][name]
        assert r["success"] is False
        assert r["failed"] is True
        assert r["idempotent_charges"] == 0
        assert r["active_reservations"] == 0
        assert r["release_effects"] == 1

    return result


def main():
    result = analyze()
    print("NAIVE")
    print(json.dumps(result["naive"], indent=2))
    print("\nROBUST")
    print(json.dumps(result["robust"], indent=2))
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nPartial side-effect invariants PASS")


if __name__ == "__main__":
    main()
