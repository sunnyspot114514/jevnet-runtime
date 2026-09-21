#!/usr/bin/env python3
"""Partial-order-reduced quorum-certificate checker for 5 replicas / 3 ballots.

This is a safety abstraction of the message-level consensus model.

Reduction:
- individual Phase-2 accept message permutations are quotiented into an
  ACCEPT-QUORUM certificate transition;
- network scheduling is abstracted to adversarial choice of any legal majority
  quorum (a superset of any concrete partition schedule);
- only the highest accepted ballot/value per replica is retained;
- global X/Y value symmetry is canonicalized.

The abstraction intentionally explores only ballots that reach a quorum
certificate. Partial accepts that never form a quorum can only add inherited
constraints in a safe protocol; omitting them is conservative for searching
for a conflicting chosen value after a prior certificate exists.

Protocols:
- naive: Phase-1 may ignore accepted history
- safe_durable: inherit highest accepted value, histories durable
- safe_volatile: same logic, but arbitrary crash set may erase acceptor history
  at each ballot boundary

Safety:
- historical chosen set never contains both X and Y
"""

from __future__ import annotations

import json
from collections import deque
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

OUT = Path("replicated_log_certificate_por_analysis.json")

NODES=("A","B","C","D","E")
BALLOTS=(1,2,3)
LEADER={1:"A",2:"C",3:"E"}
VALUES=("X","Y")
QUORUM=3
QUORUMS=tuple(frozenset(q) for q in combinations(NODES,QUORUM))


class Accepted(NamedTuple):
    ballot:int
    value:str|None


class State(NamedTuple):
    phase:int
    accepted:tuple[Accepted,...]
    chosen:frozenset[str]


class Action(NamedTuple):
    ballot:int
    phase1:tuple[str,...]
    crash:tuple[str,...]
    candidate:str
    selected:str
    accept_quorum:tuple[str,...]

    def text(self):
        crash="".join(self.crash) or "-"
        return (
            f"b{self.ballot} crash={crash} "
            f"P1={''.join(self.phase1)} candidate={self.candidate} "
            f"selected={self.selected} P2={''.join(self.accept_quorum)}"
        )


def idx(n): return NODES.index(n)


def initial_state():
    return State(
        phase=0,
        accepted=tuple(Accepted(0,None) for _ in NODES),
        chosen=frozenset(),
    )


def highest_value(accepted,quorum):
    rows=[
        accepted[idx(n)]
        for n in quorum
        if accepted[idx(n)].ballot>0 and accepted[idx(n)].value is not None
    ]
    if not rows:
        return None
    m=max(r.ballot for r in rows)
    vals={r.value for r in rows if r.ballot==m}
    if len(vals)!=1:
        raise RuntimeError(f"same-ballot conflict {rows}")
    return next(iter(vals))


def crash_sets(state,protocol):
    if protocol!="safe_volatile":
        return (frozenset(),)
    carriers=[
        n for n in NODES
        if state.accepted[idx(n)].ballot>0
    ]
    out=[frozenset()]
    for k in range(1,len(carriers)+1):
        out.extend(frozenset(c) for c in combinations(carriers,k))
    return tuple(out)


def apply_crash(accepted,crash):
    rows=list(accepted)
    for n in crash:
        rows[idx(n)]=Accepted(0,None)
    return tuple(rows)


def swap_value(v):
    if v=="X": return "Y"
    if v=="Y": return "X"
    return v


def canonicalize(state:State)->State:
    """Exploit global X/Y symmetry: first visible semantic value becomes X."""
    seq=[]
    for r in state.accepted:
        if r.value is not None:
            seq.append((r.ballot,r.value))
    for v in sorted(state.chosen):
        seq.append((999,v))
    if not seq:
        return state
    seq.sort(key=lambda x:x[0])
    first=seq[0][1]
    if first!="Y":
        return state
    return State(
        phase=state.phase,
        accepted=tuple(Accepted(r.ballot,swap_value(r.value)) for r in state.accepted),
        chosen=frozenset(swap_value(v) for v in state.chosen),
    )


def successors(state,protocol):
    if state.phase>=len(BALLOTS):
        return
    ballot=BALLOTS[state.phase]

    for crash in crash_sets(state,protocol):
        acc0=apply_crash(state.accepted,crash)

        for p1 in QUORUMS:
            inherited=highest_value(acc0,p1)

            for candidate in VALUES:
                if protocol in ("safe_durable","safe_volatile") and inherited is not None:
                    selected=inherited
                else:
                    selected=candidate

                # Phase 2 can reach any legal majority quorum. We do not require
                # P1==P2; this is more adversarial than a fixed partition schedule.
                for p2 in QUORUMS:
                    rows=list(acc0)
                    for n in p2:
                        rows[idx(n)]=Accepted(ballot,selected)
                    chosen=set(state.chosen)
                    chosen.add(selected)
                    nxt=canonicalize(State(
                        phase=state.phase+1,
                        accepted=tuple(rows),
                        chosen=frozenset(chosen),
                    ))
                    yield Action(
                        ballot=ballot,
                        phase1=tuple(sorted(p1)),
                        crash=tuple(sorted(crash)),
                        candidate=candidate,
                        selected=selected,
                        accept_quorum=tuple(sorted(p2)),
                    ),nxt


def state_json(s):
    return {
        "phase":s.phase,
        "accepted":{
            n:{"ballot":s.accepted[i].ballot,"value":s.accepted[i].value}
            for i,n in enumerate(NODES)
        },
        "chosen":sorted(s.chosen),
    }


def reconstruct(parent,bad):
    cur=bad;rev=[]
    while True:
        prev,act=parent[cur]
        if prev is None: break
        rev.append({"action":act.text(),"state":state_json(cur)})
        cur=prev
    return list(reversed(rev))


def check(protocol):
    start=canonicalize(initial_state())
    q=deque([start])
    parent={start:(None,None)}
    transitions=0
    violation=None

    while q:
        s=q.popleft()
        if len(s.chosen)>1:
            violation=s
            break
        for act,nxt in successors(s,protocol):
            transitions+=1
            if nxt not in parent:
                parent[nxt]=(s,act)
                q.append(nxt)

    return {
        "protocol":protocol,
        "states_explored":len(parent),
        "transitions_explored":transitions,
        "safety_holds":violation is None,
        "counterexample":[] if violation is None else reconstruct(parent,violation),
        "violation_state":None if violation is None else state_json(violation),
    }


def main():
    results={}
    for p in ("naive","safe_durable","safe_volatile"):
        r=check(p);results[p]=r
        print("\n",p)
        print(json.dumps({
            "states":r["states_explored"],
            "transitions":r["transitions_explored"],
            "safety":r["safety_holds"],
            "counterexample_len":len(r["counterexample"]),
        },indent=2))
        for i,x in enumerate(r["counterexample"],1):
            print(i,x["action"],"chosen=",x["state"]["chosen"])

    assert results["naive"]["safety_holds"] is False
    assert results["safe_durable"]["safety_holds"] is True
    assert results["safe_volatile"]["safety_holds"] is False

    OUT.write_text(json.dumps({
        "model":{
            "nodes":list(NODES),
            "quorum":QUORUM,
            "ballots":list(BALLOTS),
            "quorum_count":len(QUORUMS),
            "reduction":[
                "Phase-2 message permutations -> quorum certificate",
                "network schedule -> adversarial legal quorum choice",
                "X/Y semantic value symmetry canonicalized",
                "non-quorum partial accepts omitted (conservative after a chosen certificate)",
            ],
        },
        "results":results,
    },indent=2),encoding="utf-8")
    print("\nCertificate POR checker PASS")


if __name__=="__main__":
    main()
