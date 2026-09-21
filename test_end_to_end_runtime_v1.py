from end_to_end_runtime_v1 import reconcile_observations, replicated_coc_handoff


def test_reconciler_rejects_forged_and_accepts_bound_receipt():
    dar={
        "action_id":"A","auth_id":"AUTH-A","proposal_hash":"H","idempotency_key":"I",
        "tool_payload":{"op":"WRITE"}
    }
    good={
        "status":"SUCCEEDED","auth_id":"AUTH-A","proposal_hash":"H","idempotency_key":"I",
        "result":{"op":"WRITE"},"receipt_id":"R1"
    }
    bad=dict(good);bad["auth_id"]="BAD";bad["receipt_id"]="RF"
    coc,rej=reconcile_observations(dar,[bad,good])
    assert coc is not None
    assert coc["receipt_id"]=="R1"
    assert len(rej)==1


def test_replicated_coc_inherits_old_value():
    r=replicated_coc_handoff("VALID")
    assert r["safety_holds"] is True
    assert r["ballot2_selected_hash"]=="VALID"
