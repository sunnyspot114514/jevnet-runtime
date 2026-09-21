#!/usr/bin/env python3
"""Quorum promise-barrier lemma checker for N=5, quorum=3.

Question:
Suppose lower ballot b1 has NOT yet reached quorum before a higher ballot b2
successfully completes Phase-1 on a quorum Q2.

Can delayed b1 messages later complete a quorum?

If Q2 saw no accepted b1 value, then fewer than 3 replicas had accepted b1
before Q2 promises b2. Every replica in Q2 thereafter rejects b1.

For N=5, quorum=3, the complement of Q2 has size 2. Therefore any future b1
quorum of size 3 would need at least one replica in Q2, which rejects b1.

This script exhaustively checks all pre-accept subsets and all higher-term
Phase-1 quorums. It also checks the complementary case:
if b1 was already chosen, every b2 Phase-1 quorum intersects its chosen
certificate and therefore observes b1 history under durable storage.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

OUT = Path("quorum_promise_barrier_analysis.json")

NODES=frozenset({"A","B","C","D","E"})
QUORUM=3
QUORUMS=[frozenset(q) for q in itertools.combinations(sorted(NODES),QUORUM)]


def all_subsets(nodes):
    xs=sorted(nodes)
    for k in range(len(xs)+1):
        for c in itertools.combinations(xs,k):
            yield frozenset(c)


def main():
    not_yet_chosen_checks=0
    barrier_violations=[]

    # lower_accepts represents b1 acceptances BEFORE higher Phase-1.
    for lower_accepts in all_subsets(NODES):
        if len(lower_accepts)>=QUORUM:
            continue

        for q2 in QUORUMS:
            # If q2 reports no b1 accepted history, it must be disjoint from the
            # pre-existing lower accepts in this simplified lemma.
            if lower_accepts & q2:
                continue

            not_yet_chosen_checks+=1

            # After q2 promises higher ballot, only replicas outside q2 can
            # newly accept old b1 messages.
            max_possible=set(lower_accepts)|(NODES-q2)

            if len(max_possible)>=QUORUM:
                barrier_violations.append({
                    "lower_accepts":sorted(lower_accepts),
                    "higher_phase1_quorum":sorted(q2),
                    "max_possible_lower_accepts_after_promise":sorted(max_possible),
                })

    already_chosen_checks=0
    intersection_violations=[]

    for chosen_q in QUORUMS:
        for q2 in QUORUMS:
            already_chosen_checks+=1
            if chosen_q.isdisjoint(q2):
                intersection_violations.append({
                    "chosen_quorum":sorted(chosen_q),
                    "higher_phase1_quorum":sorted(q2),
                })

    print("not-yet-chosen barrier checks",not_yet_chosen_checks)
    print("barrier violations",barrier_violations)
    print("already-chosen intersection checks",already_chosen_checks)
    print("intersection violations",intersection_violations)

    assert barrier_violations==[]
    assert intersection_violations==[]

    result={
        "nodes":sorted(NODES),
        "quorum":QUORUM,
        "not_yet_chosen_barrier_checks":not_yet_chosen_checks,
        "barrier_violations":barrier_violations,
        "already_chosen_intersection_checks":already_chosen_checks,
        "intersection_violations":intersection_violations,
        "conclusion":(
            "For N=5,q=3, a completed higher-ballot Phase-1 quorum either "
            "intersects an already-chosen lower certificate, or—if it saw no "
            "lower accepted history—its promises prevent the lower ballot from "
            "later reaching quorum."
        ),
    }
    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("Promise barrier lemma PASS")


if __name__=="__main__":
    main()
