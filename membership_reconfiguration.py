#!/usr/bin/env python3
"""Membership reconfiguration quorum-safety experiment.

Old config: {A,B,C}, majority=2
New config: {C,D,E}, majority=2

Unsafe direct switch:
- X may be chosen by old quorum {A,B}
- membership flips directly
- Y may be chosen by new quorum {D,E}
- quorums are disjoint -> conflicting canonical values possible

Joint consensus:
- transition quorum must contain a majority of OLD and a majority of NEW
- every joint quorum intersects every old majority and every new majority
- this preserves history while authority moves between configurations

The experiment exhaustively enumerates quorum sets and transition pairs.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

OUT = Path("membership_reconfiguration_analysis.json")

OLD = frozenset({"A","B","C"})
NEW = frozenset({"C","D","E"})


def majorities(config: frozenset[str]) -> list[frozenset[str]]:
    threshold=(len(config)//2)+1
    out=[]
    for k in range(threshold,len(config)+1):
        for q in itertools.combinations(sorted(config),k):
            out.append(frozenset(q))
    return out


OLD_Q=majorities(OLD)
NEW_Q=majorities(NEW)


def joint_quorums() -> list[frozenset[str]]:
    universe=sorted(OLD|NEW)
    out=[]
    for k in range(1,len(universe)+1):
        for q in itertools.combinations(universe,k):
            s=frozenset(q)
            old_votes=len(s & OLD)
            new_votes=len(s & NEW)
            if old_votes>=2 and new_votes>=2:
                out.append(s)
    return out


JOINT_Q=joint_quorums()


def direct_switch_conflicts():
    rows=[]
    for oq in OLD_Q:
        for nq in NEW_Q:
            if oq.isdisjoint(nq):
                rows.append({
                    "old_quorum":sorted(oq),
                    "new_quorum":sorted(nq),
                    "intersection":[],
                    "old_value":"X",
                    "new_value":"Y",
                    "conflict_possible":True,
                })
    return rows


def joint_intersection_checks():
    old_fail=[]
    new_fail=[]
    for jq in JOINT_Q:
        for oq in OLD_Q:
            if jq.isdisjoint(oq):
                old_fail.append((sorted(jq),sorted(oq)))
        for nq in NEW_Q:
            if jq.isdisjoint(nq):
                new_fail.append((sorted(jq),sorted(nq)))
    return old_fail,new_fail


def transition_state_machine():
    """Enumerate simple old -> joint -> new authority transfer.

    A value accepted under OLD must be carried into JOINT. Once JOINT chooses a
    value, NEW must inherit it. We enumerate every quorum combination and verify
    no conflicting value can be introduced if inheritance is enforced.
    """
    violations=[]
    states=0

    for old_q in OLD_Q:
        old_value="X"

        for joint_q in JOINT_Q:
            if old_q.isdisjoint(joint_q):
                # Should be impossible by joint quorum construction.
                violations.append({
                    "stage":"old_to_joint",
                    "old_q":sorted(old_q),
                    "joint_q":sorted(joint_q),
                })
                continue

            # Joint sees at least one member of the old majority and inherits X.
            joint_value=old_value

            for new_q in NEW_Q:
                states+=1
                if joint_q.isdisjoint(new_q):
                    violations.append({
                        "stage":"joint_to_new",
                        "joint_q":sorted(joint_q),
                        "new_q":sorted(new_q),
                    })
                    continue
                new_value=joint_value
                if new_value!="X":
                    violations.append({
                        "stage":"value_change",
                        "old_q":sorted(old_q),
                        "joint_q":sorted(joint_q),
                        "new_q":sorted(new_q),
                    })

    return states,violations


def main():
    direct=direct_switch_conflicts()
    old_fail,new_fail=joint_intersection_checks()
    states,violations=transition_state_machine()

    print("OLD MAJORITIES", [sorted(q) for q in OLD_Q])
    print("NEW MAJORITIES", [sorted(q) for q in NEW_Q])
    print("\nDIRECT SWITCH DISJOINT PAIRS")
    for r in direct:
        print(r)

    print("\nJOINT QUORUM COUNT",len(JOINT_Q))
    print("joint-vs-old disjoint",old_fail)
    print("joint-vs-new disjoint",new_fail)
    print("transition combinations checked",states)
    print("joint transition violations",violations)

    assert len(direct)>0
    assert any(
        r["old_quorum"]==["A","B"] and r["new_quorum"]==["D","E"]
        for r in direct
    )
    assert old_fail==[]
    assert new_fail==[]
    assert violations==[]

    result={
        "old_config":sorted(OLD),
        "new_config":sorted(NEW),
        "old_majorities":[sorted(q) for q in OLD_Q],
        "new_majorities":[sorted(q) for q in NEW_Q],
        "direct_switch_disjoint_pairs":direct,
        "joint_quorums":[sorted(q) for q in JOINT_Q],
        "joint_vs_old_disjoint":old_fail,
        "joint_vs_new_disjoint":new_fail,
        "transition_combinations_checked":states,
        "joint_transition_violations":violations,
    }
    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("\nMembership reconfiguration invariants PASS")


if __name__=="__main__":
    main()
