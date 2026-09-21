from transaction_dar_race import apply_transaction_dar, CASE, EVENTS
import runtime_state_runner as base


def test_dar_winner_independent_of_reversal():
    a=apply_transaction_dar(CASE,EVENTS)
    b=apply_transaction_dar(CASE,list(reversed(EVENTS)))
    assert a==b
    assert a["last_txid"]=="TB"
    assert a["values"]=={"LEFT":"LB","RIGHT":"RB"}


def test_old_reducer_is_arrival_sensitive():
    a=base.apply_transaction(CASE,EVENTS)
    b=base.apply_transaction(CASE,list(reversed(EVENTS)))
    assert a!=b
