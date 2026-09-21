import runtime_state_hybrid_parser as h
import runtime_state_runner as r


def case(cid):
    return next(c for c in r.load_benchmark() if c["id"] == cid)


def test_transaction_expected_version_not_actual_version():
    c=case("R08")
    p=h.deterministic_fields(c,"Transaction Y stages LEFT=L2 with expected version 4.")
    assert p["key"]=="LEFT"
    assert p["value"]=="L2"
    assert p["txid"]=="Y"
    assert p["expected_version"]=="4"
    assert p["version"]=="NONE"


def test_sensor_fields():
    c=case("R06")
    p=h.deterministic_fields(c,"S2 reports LEVEL=HIGH, sequence 11, event time 189.")
    assert p["key"]=="LEVEL"
    assert p["value"]=="HIGH"
    assert p["version"]=="11"
    assert p["writer"]=="S2"
    assert p["event_time"]=="189"


def test_conflict_write_fields():
    c=case("R01")
    p=h.deterministic_fields(c,"Writer C proposes MODE = FAST at version 6.")
    assert p["key"]=="MODE" and p["value"]=="FAST" and p["writer"]=="C" and p["version"]=="6"
