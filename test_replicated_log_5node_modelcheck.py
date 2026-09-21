from replicated_log_5node_phased_checker import model_check, targeted_two_ballot


def test_targeted_naive_conflict():
    assert targeted_two_ballot("naive",False)["final"]["chosen"]==["X","Y"]


def test_targeted_durable_survives_intersection_crash():
    r=targeted_two_ballot("safe_durable",True)
    assert r["final"]["chosen"]==["X"]
    assert r["final"]["ballot_values"]["2"]=="X"


def test_targeted_volatile_history_loss_conflicts():
    assert targeted_two_ballot("safe_volatile",True)["final"]["chosen"]==["X","Y"]


def test_bounded_safe_durable_exhaustive():
    r=model_check("safe_durable",max_states=1000000)
    assert r["hit_state_limit"] is False
    assert r["safety_holds"] is True
