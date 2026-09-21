from cross_agent_authorization import (
    DurableBus, Provider, canonical_pipeline, role_attack_matrix,
    forged_observation_case, AUTH_ID, IDEM_KEY
)


def test_role_escalations_rejected():
    m=role_attack_matrix()
    assert all(not x["accepted"] for x in m.values())


def test_forged_observation_cannot_become_canonical_source():
    x=forged_observation_case()
    assert x["coc_present"] is True
    assert "FAKE-REC" in x["observation_receipts"]
    assert "REC-X" in x["observation_receipts"]
    assert x["coc"]["receipt_id"]=="REC-X"
    assert x["coc"]["auth_id"]=="AUTH-X"


def test_normal_chain_converges():
    bus=DurableBus(); provider=Provider()
    for _ in range(3):
        canonical_pipeline(bus,provider)
    coc=bus.first("COC")
    assert coc is not None
    assert coc["auth_id"]==AUTH_ID
    assert coc["idem_key"]==IDEM_KEY
    assert len(provider.effects)==1
