#!/usr/bin/env python3
"""Threshold authorization with duplicate/equivocation resistance.

Three authorizers: A1, A2, A3.
Threshold: 2-of-3 approvals for the same proposal hash and authorization epoch.

Properties:
- duplicate vote from one authorizer counts once;
- one malicious authorizer cannot authorize a mutated proposal;
- equivocation by one authorizer is quarantined and that authorizer contributes
  to neither conflicting hash;
- delivery order does not change the issued DAR.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path

OUT = Path("quorum_authorization_analysis.json")

AUTHORIZERS = ("A1", "A2", "A3")
THRESHOLD = 2
ACTION_ID = "ACT-Q"
EPOCH = 7

GOOD_PAYLOAD = {"operation":"SET","key":"MODE","value":"SAFE"}
BAD_PAYLOAD = {"operation":"SET","key":"MODE","value":"UNSAFE"}


def payload_hash(payload):
    blob=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(blob).hexdigest()


GOOD_HASH=payload_hash(GOOD_PAYLOAD)
BAD_HASH=payload_hash(BAD_PAYLOAD)


def reduce_votes(votes):
    """Order-independent quorum reducer."""
    by_authorizer=defaultdict(list)
    for v in votes:
        if (
            v["authorizer"] not in AUTHORIZERS
            or v["action_id"] != ACTION_ID
            or int(v["epoch"]) != EPOCH
        ):
            continue
        by_authorizer[v["authorizer"]].append(v)

    valid_votes=[]
    quarantined=[]

    for authorizer, rows in sorted(by_authorizer.items()):
        # Collapse exact duplicates.
        unique={}
        for r in rows:
            key=(r["decision"],r["proposal_hash"])
            unique[key]=r

        # Any authorizer voting for multiple semantic outcomes/hashes equivocates.
        if len(unique)>1:
            quarantined.append({
                "authorizer":authorizer,
                "reason":"EQUIVOCATION",
                "votes":[list(k) for k in sorted(unique)],
            })
            continue

        r=next(iter(unique.values()))
        valid_votes.append(r)

    approvals=defaultdict(set)
    rejections=defaultdict(set)
    for v in valid_votes:
        target=approvals if v["decision"]=="APPROVE" else rejections
        target[v["proposal_hash"]].add(v["authorizer"])

    eligible=[
        (h,sorted(voters))
        for h,voters in approvals.items()
        if len(voters)>=THRESHOLD
    ]

    dar=None
    if len(eligible)==1:
        h,voters=eligible[0]
        dar={
            "kind":"DAR",
            "action_id":ACTION_ID,
            "epoch":EPOCH,
            "proposal_hash":h,
            "approvers":voters,
            "threshold":THRESHOLD,
        }
    elif len(eligible)>1:
        # Conflicting simultaneous quorums should never silently pick one.
        dar=None
        quarantined.append({
            "authorizer":"SYSTEM",
            "reason":"CONFLICTING_QUORUMS",
            "eligible":eligible,
        })

    return {
        "dar":dar,
        "quarantined":quarantined,
        "valid_votes":valid_votes,
        "approvals":{h:sorted(v) for h,v in approvals.items()},
        "rejections":{h:sorted(v) for h,v in rejections.items()},
    }


def vote(authorizer,decision,h):
    return {
        "authorizer":authorizer,
        "decision":decision,
        "proposal_hash":h,
        "action_id":ACTION_ID,
        "epoch":EPOCH,
    }


SCENARIOS={
    "two_honest_approve_good":[
        vote("A1","APPROVE",GOOD_HASH),
        vote("A2","APPROVE",GOOD_HASH),
    ],
    "one_malicious_only_bad":[
        vote("A3","APPROVE",BAD_HASH),
    ],
    "duplicate_vote_not_double_counted":[
        vote("A1","APPROVE",GOOD_HASH),
        vote("A1","APPROVE",GOOD_HASH),
        vote("A1","APPROVE",GOOD_HASH),
    ],
    "one_bad_one_good_no_quorum":[
        vote("A1","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",BAD_HASH),
    ],
    "two_good_plus_malicious_bad":[
        vote("A1","APPROVE",GOOD_HASH),
        vote("A2","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",BAD_HASH),
    ],
    "equivocator_excluded_but_two_honest_still_quorum":[
        vote("A1","APPROVE",GOOD_HASH),
        vote("A2","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",BAD_HASH),
    ],
    "equivocation_breaks_apparent_two_votes":[
        vote("A1","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",GOOD_HASH),
        vote("A3","APPROVE",BAD_HASH),
    ],
}


def permutation_invariance(rows):
    outcomes=set()
    quarantine_shapes=set()
    for perm in itertools.permutations(rows):
        r=reduce_votes(list(perm))
        dar=r["dar"]
        outcomes.add(
            None if dar is None else (
                dar["proposal_hash"],
                tuple(dar["approvers"]),
                dar["epoch"],
            )
        )
        quarantine_shapes.add(tuple(
            (q["authorizer"],q["reason"]) for q in r["quarantined"]
        ))
    return outcomes,quarantine_shapes


def main():
    result={}
    for name,rows in SCENARIOS.items():
        reduced=reduce_votes(rows)
        outcomes,qshapes=permutation_invariance(rows)
        result[name]={
            "reduced":reduced,
            "permutation_outcomes":[list(x) if x is not None else None for x in outcomes],
            "permutation_outcome_count":len(outcomes),
            "quarantine_shape_count":len(qshapes),
        }
        print("\n",name)
        print(json.dumps(result[name],indent=2))

    assert result["two_honest_approve_good"]["reduced"]["dar"]["proposal_hash"]==GOOD_HASH
    assert result["one_malicious_only_bad"]["reduced"]["dar"] is None
    assert result["duplicate_vote_not_double_counted"]["reduced"]["dar"] is None
    assert result["one_bad_one_good_no_quorum"]["reduced"]["dar"] is None
    assert result["two_good_plus_malicious_bad"]["reduced"]["dar"]["proposal_hash"]==GOOD_HASH
    assert result["equivocator_excluded_but_two_honest_still_quorum"]["reduced"]["dar"]["proposal_hash"]==GOOD_HASH
    assert result["equivocation_breaks_apparent_two_votes"]["reduced"]["dar"] is None

    # Every scenario is delivery-order invariant.
    assert all(v["permutation_outcome_count"]==1 for v in result.values())

    OUT.write_text(json.dumps({
        "threshold":THRESHOLD,
        "authorizers":AUTHORIZERS,
        "good_hash":GOOD_HASH,
        "bad_hash":BAD_HASH,
        "scenarios":result,
    },indent=2),encoding="utf-8")
    print("\nThreshold authorization invariants PASS")


if __name__=="__main__":
    main()
