from exactly_once_impossibility import analyze


def test_retry_and_no_retry_each_fail_one_world():
    x=analyze()["decision_table"]
    assert x["RETRY"]["effect_happened"]["exactly_once"] is False
    assert x["RETRY"]["effect_did_not_happen"]["exactly_once"] is True
    assert x["DO_NOT_RETRY"]["effect_happened"]["exactly_once"] is True
    assert x["DO_NOT_RETRY"]["effect_did_not_happen"]["exactly_once"] is False
