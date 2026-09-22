from sar_runtime import (
    ProviderCapabilities,
    SQLiteProviderAdapter,
)


def test_sqlite_provider_idempotency_and_query_survive_reopen(tmp_path):
    db=tmp_path/"provider.db"
    p1=SQLiteProviderAdapter(db)
    r1=p1.dispatch(
        action_id="A1",
        auth_id="AUTH1",
        proposal_hash="PH1",
        idempotency_key="IDEM1",
        fence=1,
        result={"value":"x"},
    )
    assert p1.effect_count()==1

    p2=SQLiteProviderAdapter(db)
    r2=p2.dispatch(
        action_id="A1",
        auth_id="AUTH1",
        proposal_hash="PH1",
        idempotency_key="IDEM1",
        fence=1,
        result={"value":"x"},
    )
    assert p2.effect_count()==1
    assert r2==r1
    assert p2.query("IDEM1")==r1


def test_sqlite_provider_fencing_survives_reopen(tmp_path):
    db=tmp_path/"provider.db"
    p1=SQLiteProviderAdapter(db)
    p1.advance_fence(5)

    p2=SQLiteProviderAdapter(db)
    out=p2.dispatch(
        action_id="A1",
        auth_id="AUTH1",
        proposal_hash="PH1",
        idempotency_key="IDEM1",
        fence=4,
        result={"value":"x"},
    )
    assert out["status"]=="REJECTED_STALE_FENCE"
    assert p2.effect_count()==0
