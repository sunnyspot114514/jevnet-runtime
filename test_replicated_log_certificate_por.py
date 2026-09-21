from replicated_log_certificate_por import check


def test_naive_certificate_model_fails():
    assert check("naive")["safety_holds"] is False


def test_safe_durable_certificate_model_holds_three_ballots():
    assert check("safe_durable")["safety_holds"] is True


def test_volatile_history_loss_fails():
    assert check("safe_volatile")["safety_holds"] is False
