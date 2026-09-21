from partition_liveness import analyze


def test_two_three_split_minority_leader_needs_election():
    rows=analyze()
    assert any(
        r["shape"]==[3,2]
        and len(r["leader_component"])==2
        and r["classification"]=="ELECTION_NEEDED_IN_MAJORITY_COMPONENT"
        for r in rows
    )


def test_no_quorum_partition_fail_stops():
    rows=analyze()
    assert all(
        r["classification"]=="NO_QUORUM_FAIL_STOP"
        for r in rows
        if max(r["shape"])<3
    )
