from crash_recovery_runtime import (
    run_until, recover, canonical_tuple, Provider, base_log
)


def test_crash_after_external_effect_recovers_without_duplicate_effect():
    log, provider = run_until(4)
    assert len(provider.effects) == 1
    for _ in range(4):
        recover(log, provider)
    assert len(provider.effects) == 1
    assert canonical_tuple(log) == ("SUCCEEDED","SET","MODE","SAFE","R-1")


def test_crash_before_effect_dispatches_once_after_recovery():
    log, provider = run_until(3)
    assert len(provider.effects) == 0
    recover(log, provider)
    recover(log, provider)
    assert len(provider.effects) == 1
    assert canonical_tuple(log) is not None


def test_no_dar_no_effect():
    log=base_log()
    provider=Provider()
    for _ in range(10):
        recover(log,provider)
    assert len(provider.effects)==0
    assert canonical_tuple(log) is None
