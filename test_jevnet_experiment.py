from jevnet_experiment import harm_score, wide_rules


def _state(override=0.0, fabrication=0.0, harm=0.0):
    return {
        "override_attempt": {"true_probability": override},
        "fabrication_pressure": {"true_probability": fabrication},
        "direct_harm": {"score": harm},
    }


def test_safe_comply():
    assert wide_rules(_state())[0] == "comply"


def test_override_partial():
    assert wide_rules(_state(override=0.9))[0] == "partial_comply"


def test_harm_refuse_dominates_override():
    assert wide_rules(_state(override=0.9, harm=0.9))[0] == "refuse"


def test_ambiguous_harm_escalates():
    assert wide_rules(_state(harm=0.4))[0] == "escalate"


def test_score_zero_to_three_is_normalized():
    assert harm_score({"score": 1.64}) > 0.5


def test_numeric_class_probabilities_override_raw_scale():
    score = harm_score({
        "score": 99,
        "probabilities": {"0": 0.09, "1": 0.25, "2": 0.60, "3": 0.06},
    })
    assert 0.54 < score < 0.55
