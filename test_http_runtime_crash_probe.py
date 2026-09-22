from http_runtime_crash_probe import orchestrate


def test_http_provider_and_lease_remote_boundary_crash_probe():
    result=orchestrate()
    assert result["all_effect_counts_one"] is True
    assert result["all_contexts_match"] is True
    assert result["all_fixed_points"] is True
    assert result["all_remote_integrity_checks_ok"] is True

    by_cut={r["cut"]:r for r in result["rows"]}
    assert by_cut["after_intent"]["lease"]["fence"]==2
    assert by_cut["after_http_effect"]["lease"]["fence"]==2
