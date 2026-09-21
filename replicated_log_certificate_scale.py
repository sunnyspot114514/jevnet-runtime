#!/usr/bin/env python3
"""Scale study for the quorum-certificate partial-order-reduced model.

Keeps:
- N=5 replicas
- quorum=3
- values X/Y
- safe durable Phase-1 inheritance
- quorum-certificate abstraction

Sweeps ballot count 2..7.
Leader schedule cycles A,C,E,B,D,A,C.

Purpose:
Measure whether the reduced safety model remains tractable beyond three ballots.
"""

from __future__ import annotations

import json
from collections import deque
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

OUT=Path("replicated_log_certificate_scale_analysis.json")

NODES=("A","B","C","D","E")
VALUES=("X","Y")
QUORUM=3
QUORUMS=tuple(frozenset(q) for q in combinations(NODES,QUORUM))
LEADER_CYCLE=("A","C","E","B","D")


class Accepted(NamedTuple):
    ballot:int
    value:str|None


class State(NamedTuple):
    phase:int
    accepted:tuple[Accepted,...]
    chosen:frozenset[str]


def idx(n): return NODES.index(n)


def swap(v):
    if v=="X": return "Y"
    if v=="Y": return "X"
    return v


def canonicalize(s):
    vals=[]
    for r in s.accepted:
        if r.value is not None:
            vals.append((r.ballot,r.value))
    for v in sorted(s.chosen):
        vals.append((999,v))
    if not vals:
        return s
    vals.sort()
    if vals[0][1]!="Y":
        return s
    return State(
        s.phase,
        tuple(Accepted(r.ballot,swap(r.value)) for r in s.accepted),
        frozenset(swap(v) for v in s.chosen),
    )


def highest(acc,q):
    rows=[acc[idx(n)] for n in q if acc[idx(n)].ballot>0]
    if not rows:return None
    m=max(r.ballot for r in rows)
    vals={r.value for r in rows if r.ballot==m}
    if len(vals)!=1:
        raise RuntimeError(rows)
    return next(iter(vals))


def check(ballot_count:int):
    ballots=tuple(range(1,ballot_count+1))
    start=State(
        0,
        tuple(Accepted(0,None) for _ in NODES),
        frozenset(),
    )
    start=canonicalize(start)
    q=deque([start])
    seen={start}
    transitions=0
    violation=None
    max_frontier=1

    while q:
        max_frontier=max(max_frontier,len(q))
        s=q.popleft()
        if len(s.chosen)>1:
            violation=s
            break
        if s.phase>=ballot_count:
            continue
        ballot=ballots[s.phase]

        for p1 in QUORUMS:
            inherited=highest(s.accepted,p1)
            for candidate in VALUES:
                selected=inherited if inherited is not None else candidate
                for p2 in QUORUMS:
                    rows=list(s.accepted)
                    for n in p2:
                        rows[idx(n)]=Accepted(ballot,selected)
                    chosen=set(s.chosen);chosen.add(selected)
                    nxt=canonicalize(State(
                        s.phase+1,tuple(rows),frozenset(chosen)
                    ))
                    transitions+=1
                    if nxt not in seen:
                        seen.add(nxt);q.append(nxt)

    return {
        "ballots":ballot_count,
        "leader_schedule":[LEADER_CYCLE[i%len(LEADER_CYCLE)] for i in range(ballot_count)],
        "states":len(seen),
        "transitions":transitions,
        "max_frontier":max_frontier,
        "safety_holds":violation is None,
    }


def main():
    rows=[]
    for n in range(2,8):
        r=check(n);rows.append(r)
        print(r)
        assert r["safety_holds"] is True

    OUT.write_text(json.dumps({
        "nodes":list(NODES),
        "quorum":QUORUM,
        "rows":rows,
        "note":"Certificate-level safe-durable abstraction; not full message-level liveness model.",
    },indent=2),encoding="utf-8")
    print("Certificate scale sweep PASS")


if __name__=="__main__":
    main()
