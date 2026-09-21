from partial_side_effect_saga import (
    naive_success_timeout,
    naive_hard_failure,
    run_robust_scenario,
)


def test_ambiguous_success_naive_double_charges():
    r=naive_success_timeout()
    assert r["successful_charges"]==2


def test_ambiguous_success_robust_charges_once():
    r=run_robust_scenario("success_timeout")
    assert r["success"] is True
    assert r["idempotent_charges"]==1


def test_hard_failure_naive_leaks_reservation():
    r=naive_hard_failure()
    assert r["active_reservations"]==1


def test_hard_failure_robust_compensates():
    r=run_robust_scenario("hard_fail")
    assert r["failed"] is True
    assert r["active_reservations"]==0
    assert r["release_effects"]==1


def test_compensation_timeout_is_reconciled_idempotently():
    r=run_robust_scenario("hard_fail",release_timeout_once=True)
    assert r["failed"] is True
    assert r["active_reservations"]==0
    assert r["release_effects"]==1
