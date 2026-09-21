from inflight_revocation import (
    revocation_before_validation, toctou_after_local_check,
    revocation_after_effect
)


def test_revoke_before_validation_blocks():
    assert revocation_before_validation()["effects"]==0


def test_local_check_only_has_toctou():
    assert toctou_after_local_check(False)["effects"]==1


def test_provider_fence_closes_toctou():
    r=toctou_after_local_check(True)
    assert r["effects"]==0
    assert r["receipt"]["status"]=="REJECTED_REVOKED_AUTH"


def test_post_effect_revoke_compensates_when_possible():
    r=revocation_after_effect(True)
    assert r["canonical"]["status"]=="REVOKED_COMPENSATED"


def test_post_effect_revoke_escalates_when_not_compensatable():
    r=revocation_after_effect(False)
    assert r["canonical"]["status"]=="REVOKED_AFTER_EFFECT_ESCALATE"
