from quorum_authorization import (
    reduce_votes, vote, GOOD_HASH, BAD_HASH
)


def test_duplicate_vote_counts_once():
    r=reduce_votes([vote("A1","APPROVE",GOOD_HASH)]*3)
    assert r["dar"] is None


def test_two_distinct_authorizers_form_quorum():
    r=reduce_votes([
        vote("A1","APPROVE",GOOD_HASH),
        vote("A2","APPROVE",GOOD_HASH),
    ])
    assert r["dar"] is not None


def test_equivocator_is_quarantined():
    r=reduce_votes([
        vote("A1","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",BAD_HASH),
    ])
    assert r["dar"] is None
    assert any(q["reason"]=="EQUIVOCATION" for q in r["quarantined"])
