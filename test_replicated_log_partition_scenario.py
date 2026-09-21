from replicated_log_partition_scenario import run


def test_forced_partition_breaks_naive_protocol():
    r=run("naive")
    assert r["final"]["chosen"]==["X","Y"]


def test_forced_partition_safe_protocol_inherits_old_value():
    r=run("safe")
    assert r["final"]["chosen"]==["X"]
    assert r["final"]["ballot_values"]["2"]=="X"
