from replicated_log_modelcheck import model_check


def test_naive_quorum_protocol_has_split_brain_counterexample():
    r=model_check("naive")
    assert r["safety_holds"] is False
    assert len(r["counterexample_trace"])>0


def test_safe_phase1_inheritance_prevents_conflicting_coc():
    r=model_check("safe")
    assert r["safety_holds"] is True
