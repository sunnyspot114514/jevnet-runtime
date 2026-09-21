from mesh_experiment import layer2_state, layer3_state


BASE = {"assistant_policy": ["p"], "user_message": "hello"}
L1 = {"jev1": {"x": 1}, "jev2": {"x": 2}, "jev3": {"x": 3}}
L2 = {"jev4": {"x": 4}, "jev5": {"x": 5}, "jev6": {"x": 6}}


def test_strict_layer2_has_no_context_skip():
    s = layer2_state("strict", BASE, L1)
    assert s == {"upstream_layer": L1}


def test_residual_layer2_keeps_context():
    s = layer2_state("residual", BASE, L1)
    assert s["upstream_layer"] == L1
    assert s["residual_context"] == BASE


def test_strict_layer3_has_no_context_skip():
    s = layer3_state("strict", BASE, L2)
    assert s == {"upstream_layer": L2}


def test_residual_layer3_keeps_context():
    s = layer3_state("residual", BASE, L2)
    assert s["upstream_layer"] == L2
    assert s["residual_context"] == BASE
