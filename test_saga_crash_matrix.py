from saga_crash_matrix import success_cut, failure_cut


def test_success_crash_after_charge_effect():
    r=success_cut(5)
    assert r["success"] is True
    assert r["charge_effects"]==1
    assert r["payment_calls"]==1


def test_failure_crash_after_release_effect():
    r=failure_cut(3)
    assert r["failed"] is True
    assert r["release_effects"]==1
    assert r["active_reservations"]==0
