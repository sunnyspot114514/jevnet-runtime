#!/usr/bin/env python3
"""Reduced exhaustive 5-replica / 3-ballot SAFE+DURABLE checker.

Purpose:
Complete the 3-ballot safety search that the broad crash/partition BFS could not.

Sound reductions for the single-slot safety property:
- Only safe_durable protocol is checked here.
- Crash/restart is not expanded because promised/accepted state is durable;
  crash+restart is state-equivalent for safety.
- Ballot 1 candidate is fixed to X by X/Y symmetry.
- Stale accept messages are omitted once stale; promised terms only increase,
  so they can never become valid later.
- Each non-stale accept message may be delivered at most once.
- Network partition changes only when a new ballot prepares; delayed accepts
  from earlier ballots may still arrive in later phases if reachable.

Model:
- A,B,C,D,E
- quorum 3
- ballots 1,2,3
- leaders A,C,E
- values X,Y
- six partition shapes from earlier models
- arbitrary Phase-1 quorum visible to leader at each ballot
- arbitrary delayed Phase-2 deliveries

Safety:
Never quorum-choose two distinct values for the same slot.
"""

from __future__ import annotations

import json
from collections import deque
from itertools import combinations
from pathlib import Path
from typing import NamedTuple, Iterable

OUT = Path("replicated_log_5node_3ballot_reduced_analysis.json")

NODES=("A","B","C","D","E")
VALUES=("X","Y")
BALLOTS=(1,2,3)
LEADER={1:"A",2:"C",3:"E"}
QUORUM=3

PARTITIONS={
    "FULL":(frozenset(NODES),),
    "ABC_DE":(frozenset({"A","B","C"}),frozenset({"D","E"})),
    "CDE_AB":(frozenset({"C","D","E"}),frozenset({"A","B"})),
    "ACE_BD":(frozenset({"A","C","E"}),frozenset({"B","D"})),
    "ABD_CE":(frozenset({"A","B","D"}),frozenset({"C","E"})),
    "BCE_AD":(frozenset({"B","C","E"}),frozenset({"A","D"})),
}

class Replica(NamedTuple):
    promised:int
    accepted_ballot:int
    accepted_value:str|None

class State(NamedTuple):
    phase:int
    partition:str
    replicas:tuple[Replica,...]
    ballot_values:tuple[str|None,...]
    chosen:frozenset[str]
    delivered_mask:int

class Action(NamedTuple):
    kind:str
    detail:tuple
    def text(self):
        if self.kind=="prepare":
            b,l,p,cand,q,sel=self.detail
            return f"b{b} {l} PREPARE net={p} candidate={cand} quorum={''.join(q)} selected={sel}"
        if self.kind=="deliver":
            b,l,n,v=self.detail
            return f"deliver b{b} {l}->{n} {v}"
        return f"{self.kind}{self.detail}"

def idx(n): return NODES.index(n)

def msg_bit(ballot,node):
    return 1 << (BALLOTS.index(ballot)*len(NODES)+idx(node))

def init():
    return State(
        phase=0,
        partition="FULL",
        replicas=tuple(Replica(0,0,None) for _ in NODES),
        ballot_values=(None,)*3,
        chosen=frozenset(),
        delivered_mask=0,
    )

def component(partition,node):
    for comp in PARTITIONS[partition]:
        if node in comp: return comp
    raise KeyError(node)

def possible_quorums(partition,leader):
    comp=sorted(component(partition,leader))
    if len(comp)<QUORUM:return []
    return [tuple(q) for q in combinations(comp,QUORUM) if leader in q]

def highest_accepted(reps,quorum):
    rows=[
        (reps[idx(n)].accepted_ballot,reps[idx(n)].accepted_value)
        for n in quorum
        if reps[idx(n)].accepted_ballot>0 and reps[idx(n)].accepted_value is not None
    ]
    if not rows:return None
    m=max(b for b,_ in rows)
    vals={v for b,v in rows if b==m}
    if len(vals)!=1:raise RuntimeError(rows)
    return next(iter(vals))

def chosen_after(reps,chosen,ballot,value):
    count=sum(r.accepted_ballot==ballot and r.accepted_value==value for r in reps)
    out=set(chosen)
    if count>=QUORUM:out.add(value)
    return frozenset(out)

def prepare_successors(s):
    if s.phase>=3:return
    b=BALLOTS[s.phase]; leader=LEADER[b]
    candidates=("X",) if b==1 else VALUES

    for p in PARTITIONS:
        for q in possible_quorums(p,leader):
            if any(s.replicas[idx(n)].promised>=b for n in q):
                continue
            inherited=highest_accepted(s.replicas,q)
            for cand in candidates:
                sel=inherited if inherited is not None else cand
                reps=list(s.replicas)
                for n in q:
                    i=idx(n);r=reps[i]
                    reps[i]=Replica(b,r.accepted_ballot,r.accepted_value)
                vals=list(s.ballot_values);vals[s.phase]=sel
                yield Action("prepare",(b,leader,p,cand,q,sel)),State(
                    phase=s.phase+1,
                    partition=p,
                    replicas=tuple(reps),
                    ballot_values=tuple(vals),
                    chosen=s.chosen,
                    delivered_mask=s.delivered_mask,
                )

def deliver_successors(s):
    for bi in range(s.phase):
        b=BALLOTS[bi];leader=LEADER[b];value=s.ballot_values[bi]
        if value is None:continue
        comp=component(s.partition,leader)
        for n in NODES:
            bit=msg_bit(b,n)
            if s.delivered_mask & bit:continue
            if n not in comp:continue
            r=s.replicas[idx(n)]

            # Stale forever: promised only increases, so dropping this pending message
            # cannot remove any future safety-relevant transition.
            if b < r.promised:
                continue

            reps=list(s.replicas)
            reps[idx(n)]=Replica(max(r.promised,b),b,value)
            reps=tuple(reps)
            yield Action("deliver",(b,leader,n,value)),State(
                phase=s.phase,
                partition=s.partition,
                replicas=reps,
                ballot_values=s.ballot_values,
                chosen=chosen_after(reps,s.chosen,b,value),
                delivered_mask=s.delivered_mask|bit,
            )

def successors(s):
    yield from prepare_successors(s)
    yield from deliver_successors(s)

def sj(s):
    return {
        "phase":s.phase,
        "partition":s.partition,
        "replicas":{
            n:{
                "promised":s.replicas[i].promised,
                "accepted_ballot":s.replicas[i].accepted_ballot,
                "accepted_value":s.replicas[i].accepted_value,
            } for i,n in enumerate(NODES)
        },
        "ballot_values":{str(b):s.ballot_values[i] for i,b in enumerate(BALLOTS)},
        "chosen":sorted(s.chosen),
        "delivered_mask":s.delivered_mask,
    }

def reconstruct(parent,v):
    rev=[];cur=v
    while True:
        prev,a=parent[cur]
        if prev is None:break
        rev.append({"action":a.text(),"state":sj(cur)})
        cur=prev
    return list(reversed(rev))

def check(max_states=2_000_000):
    start=init()
    q=deque([start])
    parent={start:(None,None)}
    transitions=0
    violation=None
    max_frontier=1

    while q:
        s=q.popleft()
        if len(s.chosen)>1:
            violation=s;break
        for a,nxt in successors(s):
            transitions+=1
            if nxt not in parent:
                parent[nxt]=(s,a)
                if len(parent)>=max_states:
                    return {
                        "states_explored":len(parent),
                        "transitions_explored":transitions,
                        "hit_state_limit":True,
                        "safety_holds":True,
                        "counterexample_trace":[],
                        "max_frontier":max_frontier,
                    }
                q.append(nxt)
        if len(q)>max_frontier:max_frontier=len(q)

    return {
        "states_explored":len(parent),
        "transitions_explored":transitions,
        "hit_state_limit":False,
        "safety_holds":violation is None,
        "counterexample_trace":[] if violation is None else reconstruct(parent,violation),
        "max_frontier":max_frontier,
    }

def main():
    r=check()
    print(json.dumps({
        "states_explored":r["states_explored"],
        "transitions_explored":r["transitions_explored"],
        "hit_state_limit":r["hit_state_limit"],
        "safety_holds":r["safety_holds"],
        "counterexample_len":len(r["counterexample_trace"]),
        "max_frontier":r["max_frontier"],
    },indent=2))
    if r["counterexample_trace"]:
        for i,x in enumerate(r["counterexample_trace"],1):
            print(i,x["action"],x["state"]["chosen"])

    result={
        "model":{
            "nodes":list(NODES),"quorum":QUORUM,
            "ballots":list(BALLOTS),"leaders":LEADER,
            "values":list(VALUES),
            "reductions":[
                "ballot1 value fixed to X by value symmetry",
                "durable crash/restart omitted as state-equivalent for safety",
                "stale pending accepts dropped because promise numbers only increase",
                "partition changes only at prepare boundaries",
                "each non-stale accept delivered at most once",
            ],
        },
        "result":r,
    }
    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    if r["hit_state_limit"]:
        print("INCONCLUSIVE: state limit hit")
    elif r["safety_holds"]:
        print("EXHAUSTIVE NO COUNTEREXAMPLE in reduced 3-ballot model")
    else:
        print("COUNTEREXAMPLE FOUND")

if __name__=="__main__":
    main()
