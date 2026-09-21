from canonical_outcome_race import (
    AUTH, OBSERVATIONS, naive_last_arrival, canonical_outcome_commit
)


def test_canonical_is_order_invariant():
    a=canonical_outcome_commit(AUTH,OBSERVATIONS)
    b=canonical_outcome_commit(AUTH,list(reversed(OBSERVATIONS)))
    assert (a["status"],a["result"],a["seq"]) == ("ROLLED_BACK","NONE",3)
    assert (b["status"],b["result"],b["seq"]) == ("ROLLED_BACK","NONE",3)


def test_naive_is_order_sensitive():
    a=naive_last_arrival(AUTH,OBSERVATIONS)
    b=naive_last_arrival(AUTH,list(reversed(OBSERVATIONS)))
    assert a != b


def test_spoof_is_rejected_and_same_seq_conflict_quarantined():
    x=canonical_outcome_commit(AUTH,OBSERVATIONS)
    assert ("SPOOF","auth_mismatch") in x["rejected"]
    assert any("same_seq_conflict:2" in reason for _,reason in x["quarantined"])
