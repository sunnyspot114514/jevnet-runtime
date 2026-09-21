from journal_recovery_stress import run_workload


def test_one_stress_workload():
    r=run_workload(12345)
    assert r["unauthorized_effects"]==0
    assert r["missing_authorized_effects"]==0
    assert r["unauthorized_cocs"]==0
    assert r["missing_authorized_cocs"]==0
    assert r["digest_fixed_point"] is True
    assert r["provider_effect_count"]==r["authorized"]
    assert r["coc_action_count"]==r["authorized"]
