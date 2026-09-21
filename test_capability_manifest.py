from capability_manifest import (
    MANIFEST_V1, SCENARIOS, validate_proposal, issue_dar,
    dispatch_validate, changed_manifest
)


def test_model_cannot_lie_chmod_into_allowed_class():
    r=validate_proposal(SCENARIOS["chmod_lies_about_effect"],MANIFEST_V1)
    assert r["authorized"] is False
    assert r["normalized_calls"][0]["effect_class"]=="permission_change"


def test_unknown_tool_fails_closed():
    assert issue_dar(SCENARIOS["unknown_tool"],MANIFEST_V1) is None


def test_mixed_bundle_rejects_whole_proposal():
    assert issue_dar(SCENARIOS["mixed_bundle"],MANIFEST_V1) is None


def test_manifest_change_invalidates_old_dar():
    dar=issue_dar(SCENARIOS["local_write_allowed"],MANIFEST_V1)
    assert dispatch_validate(dar,MANIFEST_V1)["allowed"] is True
    assert dispatch_validate(dar,changed_manifest())["allowed"] is False
