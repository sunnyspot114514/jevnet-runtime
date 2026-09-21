from replicated_log_certificate_scale import check


def test_six_ballot_safe_durable_certificate_model():
    assert check(6)["safety_holds"] is True
