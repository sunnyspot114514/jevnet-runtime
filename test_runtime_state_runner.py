from runtime_state_runner import (
    apply_conflict_write,
    apply_revocation,
    apply_staleness,
    apply_transaction,
)


def test_conflict_tie_uses_writer_priority():
    case = {
        "initial_state": {"key":"MODE","value":"OLD","version":5,"writer":"B"},
        "runtime_config": {"writer_priority":{"A":2,"B":1}},
    }
    props = [
        {"event_type":"WRITE","key":"MODE","value":"NEW","version":"5","writer":"A","txid":"NONE","event_time":"NONE","expected_version":"NONE"}
    ]
    assert apply_conflict_write(case, props)["value"] == "NEW"


def test_revocation_blocks_stale_resurrection():
    case = {"initial_state":{"key":"TOKEN","value":"ALPHA","version":1,"revoked":False,"writer":"A"}}
    props = [
        {"event_type":"REVOKE","key":"TOKEN","value":"NONE","version":"2","writer":"A","txid":"NONE","event_time":"NONE","expected_version":"NONE"},
        {"event_type":"WRITE","key":"TOKEN","value":"ALPHA","version":"1","writer":"A","txid":"NONE","event_time":"NONE","expected_version":"NONE"},
    ]
    s = apply_revocation(case, props)
    assert s["revoked"] is True and s["version"] == 2


def test_stale_sensor_rejected():
    case = {
        "initial_state":{"key":"TEMP","value":"10","seq":3,"event_time":90,"writer":"S1"},
        "runtime_config":{"now":100,"ttl":10},
    }
    props = [
        {"event_type":"SENSOR","key":"TEMP","value":"20","version":"4","writer":"S1","txid":"NONE","event_time":"80","expected_version":"NONE"}
    ]
    assert apply_staleness(case, props)["value"] == "10"


def test_transaction_atomic_commit_requires_auth_commit_and_all_keys():
    case = {
        "initial_state":{"version":7,"values":{"LEFT":"L0","RIGHT":"R0"},"last_txid":"NONE"},
        "runtime_config":{"required_keys":["LEFT","RIGHT"]},
    }
    props = [
        {"event_type":"TX_WRITE","key":"LEFT","value":"L1","version":"NONE","writer":"A","txid":"T1","event_time":"NONE","expected_version":"7"},
        {"event_type":"TX_WRITE","key":"RIGHT","value":"R1","version":"NONE","writer":"B","txid":"T1","event_time":"NONE","expected_version":"7"},
        {"event_type":"AUTH","key":"NONE","value":"NONE","version":"NONE","writer":"AUTH","txid":"T1","event_time":"NONE","expected_version":"NONE"},
        {"event_type":"COMMIT","key":"NONE","value":"NONE","version":"NONE","writer":"A","txid":"T1","event_time":"NONE","expected_version":"7"},
    ]
    s = apply_transaction(case, props)
    assert s["version"] == 8 and s["values"] == {"LEFT":"L1","RIGHT":"R1"}
