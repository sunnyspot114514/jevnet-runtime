from jev_authorizer_boundary_v4 import boundary_decision, quorum_authorized


def test_forbidden_class_vetoes():
    assert boundary_decision("PERMISSION_SECURITY")=="VETO"
    assert boundary_decision("FINANCIAL")=="VETO"


def test_local_classes_allow():
    assert boundary_decision("LOCAL_CONTENT")=="ALLOW"
    assert boundary_decision("LOCAL_MOCK_TEST")=="ALLOW"


def test_ambiguous_not_authorized():
    assert boundary_decision("AMBIGUOUS_SCOPE")=="AMBIGUOUS"


def test_semantic_quorum():
    assert quorum_authorized(["APPROVE","APPROVE","REJECT"])
    assert not quorum_authorized(["APPROVE","REJECT","ESCALATE"])
