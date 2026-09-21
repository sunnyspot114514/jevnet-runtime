from jev_authorizer_quorum import quorum_authorized


def test_two_approvals_form_quorum():
    assert quorum_authorized(["APPROVE","APPROVE","REJECT"]) is True


def test_one_approval_does_not_form_quorum():
    assert quorum_authorized(["APPROVE","REJECT","ESCALATE"]) is False
