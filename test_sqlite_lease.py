from sar_runtime import SQLiteLeaseCoordinator


def test_sqlite_lease_fence_survives_reopen(tmp_path):
    db=tmp_path/"lease.db"
    a=SQLiteLeaseCoordinator(db)
    t1=a.acquire("workspace","R1")
    assert t1.fence==1

    b=SQLiteLeaseCoordinator(db)
    t2=b.acquire("workspace","R2")
    assert t2.fence==2
    assert b.current("workspace")==t2

    assert b.release(t1) is False
    assert b.release(t2) is True
    assert b.current("workspace") is None

    c=SQLiteLeaseCoordinator(db)
    t3=c.acquire("workspace","R3")
    assert t3.fence==3
