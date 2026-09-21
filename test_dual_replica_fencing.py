from dual_replica_fencing import (
    same_action_recovery_race, same_action_without_idempotency,
    stale_owner_scenario, handoff_interleavings
)


def test_idempotency_deduplicates_same_dar_recovery():
    assert same_action_recovery_race()["effect_count"]==1
    assert same_action_without_idempotency()["effect_count"]==2


def test_fence_rejects_old_owner_after_handoff():
    r=stale_owner_scenario(True)
    assert r["final_value"]=="VALUE-B"
    assert r["stale_r1_result"]["status"]=="REJECTED_STALE_FENCE"


def test_all_post_handoff_orders_safe_with_fencing():
    rows=handoff_interleavings(True)
    assert all(r["final_value"]=="VALUE-B" for r in rows)
    assert all(r["accepted_actions"]==["B"] for r in rows)
