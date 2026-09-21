from replicated_log_5node_3ballot_reduced import check

def test_reduced_3ballot_checker_completes_safely():
    r=check(max_states=2000000)
    assert r["hit_state_limit"] is False
    assert r["safety_holds"] is True
