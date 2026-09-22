from sqlite_wal_crash_probe import orchestrate


def test_sqlite_transaction_crash_atomicity():
    result=orchestrate()
    assert result["all_precommit_writes_invisible"] is True
    assert result["all_postcommit_writes_visible"] is True
    assert result["all_integrity_checks_ok"] is True
