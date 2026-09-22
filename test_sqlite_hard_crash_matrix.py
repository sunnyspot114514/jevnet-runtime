from sqlite_hard_crash_matrix import orchestrate


def test_cross_process_sqlite_hard_crash_matrix():
    result=orchestrate()
    assert result["all_effect_counts_one"] is True
    assert result["all_contexts_match_baseline"] is True
    assert result["all_second_recoveries_fixed_point"] is True

    by_cut={r["cut"]:r for r in result["rows"]}
    assert by_cut["after_intent"]["dispatch_intent_count"]==2
    assert by_cut["after_provider_effect"]["dispatch_intent_count"]==2
    assert by_cut["after_intent"]["current_lease"]["fence"]==2
    assert by_cut["after_provider_effect"]["current_lease"]["fence"]==2
