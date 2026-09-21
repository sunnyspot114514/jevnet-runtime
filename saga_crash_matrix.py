#!/usr/bin/env python3
"""Crash matrix for a two-step saga with compensation.

Constructs durable/provider states corresponding to crashes at critical cut points,
then invokes the normal robust recovery loop.

Success path cuts:
- DAR only
- reserve intent only
- reserve effect before observation
- reserve observation
- charge intent
- charge effect before observation
- charge observation

Failure/compensation path cuts:
- payment failure durable
- release intent
- release effect before observation
- release observation

Every cut must converge without duplicate effect or leaked reservation.
"""

from __future__ import annotations

import json
from pathlib import Path

from partial_side_effect_saga import (
    AMOUNT,
    INV_IDEM,
    ORDER_ID,
    PAY_IDEM,
    REL_IDEM,
    SKU,
    Inventory,
    Log,
    Payment,
    robust_log,
    robust_recover,
)

OUT = Path("saga_crash_matrix_analysis.json")


def recover_to_fixed_point(log, inv, pay, payment_mode):
    for _ in range(8):
        robust_recover(
            log,
            inv,
            pay,
            payment_mode=payment_mode,
            release_timeout_once=False,
        )


def success_cut(cut):
    log = robust_log()
    inv = Inventory()
    pay = Payment()

    # 1 reserve intent
    if cut >= 1:
        log.append({"kind":"RESERVE_INTENT","idem_key":INV_IDEM})

    # 2 reserve effect
    if cut >= 2:
        reserve = inv.reserve(INV_IDEM, ORDER_ID, SKU)
    else:
        reserve = None

    # 3 reserve observation
    if cut >= 3:
        assert reserve is not None
        log.append({"kind":"RESERVE_OBS","receipt":reserve})

    # 4 charge intent
    if cut >= 4:
        log.append({"kind":"CHARGE_INTENT","idem_key":PAY_IDEM})

    # 5 charge external effect, no observation
    if cut >= 5:
        charge = pay.charge_idempotent(PAY_IDEM, ORDER_ID, AMOUNT, mode="success")
    else:
        charge = None

    # 6 charge observation
    if cut >= 6:
        assert charge is not None
        log.append({"kind":"CHARGE_OBS","receipt":charge})

    recover_to_fixed_point(log, inv, pay, "success")
    return {
        "cut": cut,
        "record_kinds": [r["kind"] for r in log.records],
        "charge_effects": len(pay.charges),
        "reserve_effects": len(inv.reservations),
        "release_effects": len(inv.releases),
        "active_reservations": inv.active_reservations(),
        "success": log.first("COC_SUCCESS") is not None,
        "failed": log.first("COC_FAILED") is not None,
        "payment_calls": pay.calls,
        "reserve_calls": inv.reserve_calls,
    }


def failure_cut(cut):
    log = robust_log()
    inv = Inventory()
    pay = Payment()

    reserve = inv.reserve(INV_IDEM, ORDER_ID, SKU)
    log.append({"kind":"RESERVE_INTENT","idem_key":INV_IDEM})
    log.append({"kind":"RESERVE_OBS","receipt":reserve})
    log.append({"kind":"CHARGE_INTENT","idem_key":PAY_IDEM})

    # 1 payment terminal failure recorded
    if cut >= 1:
        fail_receipt = pay.charge_idempotent(PAY_IDEM, ORDER_ID, AMOUNT, mode="hard_fail")
        log.append({"kind":"CHARGE_FAILED","receipt":fail_receipt})

    # 2 release intent
    if cut >= 2:
        log.append({
            "kind":"RELEASE_INTENT",
            "idem_key":REL_IDEM,
            "reservation_id":reserve["reservation_id"],
        })

    # 3 release external effect, no observation
    if cut >= 3:
        release = inv.release(REL_IDEM, reserve["reservation_id"])
    else:
        release = None

    # 4 release observation
    if cut >= 4:
        assert release is not None
        log.append({"kind":"RELEASE_OBS","receipt":release})

    recover_to_fixed_point(log, inv, pay, "hard_fail")
    return {
        "cut": cut,
        "record_kinds": [r["kind"] for r in log.records],
        "charge_effects": len(pay.charges),
        "reserve_effects": len(inv.reservations),
        "release_effects": len(inv.releases),
        "active_reservations": inv.active_reservations(),
        "success": log.first("COC_SUCCESS") is not None,
        "failed": log.first("COC_FAILED") is not None,
        "payment_calls": pay.calls,
        "release_calls": inv.release_calls,
    }


def main():
    success = [success_cut(cut) for cut in range(0, 7)]
    failure = [failure_cut(cut) for cut in range(0, 5)]

    print("SUCCESS CUTS")
    for r in success:
        print(
            r["cut"],
            "success", r["success"],
            "charge_effects", r["charge_effects"],
            "reserve_effects", r["reserve_effects"],
            "release_effects", r["release_effects"],
            "active_res", r["active_reservations"],
            "payment_calls", r["payment_calls"],
        )
        assert r["success"] is True
        assert r["failed"] is False
        assert r["charge_effects"] == 1
        assert r["reserve_effects"] == 1
        assert r["release_effects"] == 0
        assert r["active_reservations"] == 1

    print("\nFAILURE/COMPENSATION CUTS")
    for r in failure:
        print(
            r["cut"],
            "failed", r["failed"],
            "charge_effects", r["charge_effects"],
            "reserve_effects", r["reserve_effects"],
            "release_effects", r["release_effects"],
            "active_res", r["active_reservations"],
            "payment_calls", r["payment_calls"],
            "release_calls", r["release_calls"],
        )
        assert r["success"] is False
        assert r["failed"] is True
        assert r["charge_effects"] == 0
        assert r["reserve_effects"] == 1
        assert r["release_effects"] == 1
        assert r["active_reservations"] == 0

    result = {"success_cuts": success, "failure_cuts": failure}
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nSaga crash matrix PASS")


if __name__ == "__main__":
    main()
