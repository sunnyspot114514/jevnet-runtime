from membership_reconfiguration import (
    direct_switch_conflicts, joint_intersection_checks, transition_state_machine
)


def test_direct_reconfiguration_has_disjoint_majorities():
    rows=direct_switch_conflicts()
    assert any(r["old_quorum"]==["A","B"] and r["new_quorum"]==["D","E"] for r in rows)


def test_joint_quorums_intersect_both_config_majorities():
    old_fail,new_fail=joint_intersection_checks()
    assert old_fail==[]
    assert new_fail==[]


def test_joint_transition_preserves_value():
    _,violations=transition_state_machine()
    assert violations==[]
