#!/usr/bin/env python3
"""Bounded exhaustive 5-replica replicated-COC checker.

This checker avoids the infinite/redundant crash<->restart and partition<->heal
cycles that caused state explosion in the broad exploratory checker.

Model:
- 5 replicas A..E, quorum 3
- ballots 1,2 with leaders A,C
- conflicting COC values X,Y
- each ballot has one phase
- at each phase boundary:
    * optional crash/restart set
    * crash erases acceptor state only in safe_volatile
    * choose one network partition
    * choose one Phase-1 quorum visible to leader
    * prepare one value
- between phase boundaries:
    * any prepared accept message may be delivered at most once, in any order
    * stale accepts below promised ballot are rejected
- network/phase progression is monotonic, so the state space is finite.

Protocols:
- naive: ignores accepted history during Phase-1
- safe_durable: inherits highest accepted value; crash preserves acceptor state
- safe_volatile: inherits highest accepted value, but crash erases promise/accepted history

Safety:
- no two distinct values are ever quorum-chosen for the same slot

This is a bounded exhaustive fault model, not a full Paxos proof.
"""

from __future__ import annotations

import json
from collections import deque
from itertools import combinations
from pathlib import Path
from typing import NamedTuple, Iterable

OUT = Path("replicated_log_5node_phased_analysis.json")

NODES = ("A", "B", "C", "D", "E")
VALUES = ("X", "Y")
BALLOTS = (1, 2)
LEADER = {1: "A", 2: "C"}
QUORUM = 3

PARTITIONS = {
    "FULL": (frozenset(NODES),),
    "ABC_DE": (frozenset({"A","B","C"}), frozenset({"D","E"})),
    "CDE_AB": (frozenset({"C","D","E"}), frozenset({"A","B"})),
    "ACE_BD": (frozenset({"A","C","E"}), frozenset({"B","D"})),
    "ABD_CE": (frozenset({"A","B","D"}), frozenset({"C","E"})),
    "BCE_AD": (frozenset({"B","C","E"}), frozenset({"A","D"})),
}


class Replica(NamedTuple):
    promised: int
    accepted_ballot: int
    accepted_value: str | None


class State(NamedTuple):
    phase: int  # number of prepared ballots: 0..3
    partition: str
    replicas: tuple[Replica, ...]
    ballot_values: tuple[str | None, ...]
    chosen: frozenset[str]
    delivered_mask: int


class Action(NamedTuple):
    kind: str
    detail: tuple

    def text(self) -> str:
        if self.kind == "prepare":
            ballot, leader, partition, crash_nodes, candidate, quorum, selected = self.detail
            crashed = "".join(crash_nodes) or "-"
            return (
                f"phase b{ballot}: crash/restart={crashed} network={partition}; "
                f"{leader} PREPARE candidate={candidate} quorum={''.join(quorum)} "
                f"selected={selected}"
            )
        if self.kind == "deliver":
            ballot, leader, node, value, verdict = self.detail
            return f"deliver b{ballot} {leader}->{node} value={value}: {verdict}"
        return f"{self.kind}{self.detail}"


def idx(n: str) -> int:
    return NODES.index(n)


def msg_bit(ballot: int, node: str) -> int:
    pos = (BALLOTS.index(ballot) * len(NODES)) + idx(node)
    return 1 << pos


def initial_state() -> State:
    return State(
        phase=0,
        partition="FULL",
        replicas=tuple(Replica(0,0,None) for _ in NODES),
        ballot_values=(None,) * len(BALLOTS),
        chosen=frozenset(),
        delivered_mask=0,
    )


def component(partition: str, node: str) -> frozenset[str]:
    for comp in PARTITIONS[partition]:
        if node in comp:
            return comp
    raise KeyError(node)


def possible_quorums(partition: str, leader: str) -> list[tuple[str,...]]:
    comp = sorted(component(partition, leader))
    if len(comp) < QUORUM:
        return []
    return [tuple(q) for q in combinations(comp, QUORUM) if leader in q]


def highest_accepted_value(reps: tuple[Replica,...], quorum: tuple[str,...]) -> str | None:
    rows=[]
    for n in quorum:
        r=reps[idx(n)]
        if r.accepted_ballot>0 and r.accepted_value is not None:
            rows.append((r.accepted_ballot,r.accepted_value))
    if not rows:
        return None
    m=max(b for b,_ in rows)
    vals={v for b,v in rows if b==m}
    if len(vals)!=1:
        raise RuntimeError(f"same-ballot conflict: {rows}")
    return next(iter(vals))


def crash_restart_reps(
    reps: tuple[Replica,...],
    crash_nodes: tuple[str,...],
    protocol: str,
) -> tuple[Replica,...]:
    if protocol != "safe_volatile" or not crash_nodes:
        return reps
    rows=list(reps)
    for n in crash_nodes:
        rows[idx(n)] = Replica(0,0,None)
    return tuple(rows)


def relevant_crash_sets(reps: tuple[Replica,...], protocol: str) -> list[tuple[str,...]]:
    if protocol != "safe_volatile":
        return [tuple()]
    live_history=[
        n for n in NODES
        if reps[idx(n)].promised>0 or reps[idx(n)].accepted_ballot>0
    ]
    out=[tuple()]
    # Any subset of replicas that currently carry durable-relevant history.
    for k in range(1,len(live_history)+1):
        out.extend(tuple(c) for c in combinations(live_history,k))
    return out


def chosen_after(
    reps: tuple[Replica,...],
    chosen: frozenset[str],
    ballot: int,
    value: str,
) -> frozenset[str]:
    count=sum(
        r.accepted_ballot==ballot and r.accepted_value==value
        for r in reps
    )
    out=set(chosen)
    if count>=QUORUM:
        out.add(value)
    return frozenset(out)


def prepare_successors(state: State, protocol: str) -> Iterable[tuple[Action,State]]:
    if state.phase >= len(BALLOTS):
        return
    ballot=BALLOTS[state.phase]
    leader=LEADER[ballot]
    bi=state.phase

    for crash_nodes in relevant_crash_sets(state.replicas,protocol):
        reps0=crash_restart_reps(state.replicas,crash_nodes,protocol)

        for partition in PARTITIONS:
            for quorum in possible_quorums(partition,leader):
                if any(reps0[idx(n)].promised>=ballot for n in quorum):
                    continue

                inherited=highest_accepted_value(reps0,quorum)
                for candidate in VALUES:
                    if protocol in ("safe_durable","safe_volatile") and inherited is not None:
                        selected=inherited
                    else:
                        selected=candidate

                    reps=list(reps0)
                    for n in quorum:
                        i=idx(n)
                        r=reps[i]
                        reps[i]=Replica(
                            promised=ballot,
                            accepted_ballot=r.accepted_ballot,
                            accepted_value=r.accepted_value,
                        )
                    bvals=list(state.ballot_values)
                    bvals[bi]=selected

                    yield Action(
                        "prepare",
                        (ballot,leader,partition,crash_nodes,candidate,quorum,selected),
                    ), State(
                        phase=state.phase+1,
                        partition=partition,
                        replicas=tuple(reps),
                        ballot_values=tuple(bvals),
                        chosen=state.chosen,
                        delivered_mask=state.delivered_mask,
                    )


def deliver_successors(state: State) -> Iterable[tuple[Action,State]]:
    for bi in range(state.phase):
        ballot=BALLOTS[bi]
        leader=LEADER[ballot]
        value=state.ballot_values[bi]
        if value is None:
            continue

        leader_comp=component(state.partition,leader)
        for node in NODES:
            bit=msg_bit(ballot,node)
            if state.delivered_mask & bit:
                continue
            if node not in leader_comp:
                continue

            r=state.replicas[idx(node)]
            newmask=state.delivered_mask|bit

            if ballot < r.promised:
                # Mark stale message delivered/rejected.
                yield Action(
                    "deliver",(ballot,leader,node,value,"REJECT_STALE")
                ), state._replace(delivered_mask=newmask)
                continue

            reps=list(state.replicas)
            reps[idx(node)]=Replica(
                promised=max(r.promised,ballot),
                accepted_ballot=ballot,
                accepted_value=value,
            )
            reps=tuple(reps)
            chosen=chosen_after(reps,state.chosen,ballot,value)
            yield Action(
                "deliver",(ballot,leader,node,value,"ACCEPT")
            ), State(
                phase=state.phase,
                partition=state.partition,
                replicas=reps,
                ballot_values=state.ballot_values,
                chosen=chosen,
                delivered_mask=newmask,
            )


def successors(state: State, protocol: str) -> Iterable[tuple[Action,State]]:
    yield from prepare_successors(state,protocol)
    yield from deliver_successors(state)


def state_json(s: State) -> dict:
    return {
        "phase":s.phase,
        "partition":s.partition,
        "replicas":{
            n:{
                "promised":s.replicas[i].promised,
                "accepted_ballot":s.replicas[i].accepted_ballot,
                "accepted_value":s.replicas[i].accepted_value,
            }
            for i,n in enumerate(NODES)
        },
        "ballot_values":{str(b):s.ballot_values[i] for i,b in enumerate(BALLOTS)},
        "chosen":sorted(s.chosen),
        "delivered_mask":s.delivered_mask,
    }


def trace(parent,violation):
    cur=violation
    rev=[]
    while True:
        prev,action=parent[cur]
        if prev is None:
            break
        rev.append({"action":action.text(),"state":state_json(cur)})
        cur=prev
    return list(reversed(rev))


def model_check(protocol: str, max_states: int = 1_000_000) -> dict:
    start=initial_state()
    q=deque([start])
    parent={start:(None,None)}
    transitions=0
    violation=None
    hit_limit=False

    while q:
        s=q.popleft()
        if len(s.chosen)>1:
            violation=s
            break

        for action,nxt in successors(s,protocol):
            transitions+=1
            if nxt not in parent:
                parent[nxt]=(s,action)
                if len(parent)>=max_states:
                    hit_limit=True
                    q.clear()
                    break
                q.append(nxt)
        if hit_limit:
            break

    return {
        "protocol":protocol,
        "states_explored":len(parent),
        "transitions_explored":transitions,
        "hit_state_limit":hit_limit,
        "safety_holds":violation is None,
        "counterexample_trace":[] if violation is None else trace(parent,violation),
        "violation_state":None if violation is None else state_json(violation),
    }


def pick(state,protocol,predicate,label):
    rows=[(a,s) for a,s in successors(state,protocol) if predicate(a)]
    if not rows:
        raise RuntimeError(f"missing transition: {label}")
    rows.sort(key=lambda x:x[0].text())
    return rows[0]


def targeted_two_ballot(protocol: str, crash_c: bool) -> dict:
    """ABC chooses X. Then CDE tries candidate Y after optional C crash/restart."""
    s=initial_state()
    tr=[]

    def step(pred,label):
        nonlocal s
        a,nxt=pick(s,protocol,pred,label)
        s=nxt
        tr.append({"action":a.text(),"state":state_json(s)})

    step(
        lambda a:a.kind=="prepare"
        and a.detail[0]==1
        and a.detail[2]=="FULL"
        and a.detail[4]=="X"
        and a.detail[5]==("A","B","C"),
        "prepare b1",
    )
    for n in ("A","B","C"):
        step(
            lambda a,n=n:a.kind=="deliver" and a.detail[0]==1 and a.detail[2]==n,
            f"deliver X to {n}",
        )

    if crash_c and protocol == "safe_durable":
        # Crash/restart is state-equivalent because promised/accepted are durable.
        tr.append({
            "action":"CRASH/RESTART C; durable promised/accepted history preserved",
            "state":state_json(s),
        })
        crash_tuple=tuple()
    else:
        crash_tuple=("C",) if crash_c else tuple()

    step(
        lambda a:a.kind=="prepare"
        and a.detail[0]==2
        and a.detail[2]=="FULL"
        and a.detail[3]==crash_tuple
        and a.detail[4]=="Y"
        and a.detail[5]==("C","D","E"),
        "prepare b2",
    )

    for n in ("C","D","E"):
        step(
            lambda a,n=n:a.kind=="deliver" and a.detail[0]==2 and a.detail[2]==n,
            f"deliver b2 to {n}",
        )

    return {"protocol":protocol,"crash_c":crash_c,"trace":tr,"final":state_json(s)}


def main():
    targeted={
        "naive":targeted_two_ballot("naive",False),
        "safe_durable_crash_C":targeted_two_ballot("safe_durable",True),
        "safe_volatile_crash_C":targeted_two_ballot("safe_volatile",True),
    }

    print("TARGETED")
    for name,r in targeted.items():
        print("\n",name)
        for i,x in enumerate(r["trace"],1):
            print(i,x["action"],"chosen=",x["state"]["chosen"])
        print("final",r["final"]["chosen"],"b2=",r["final"]["ballot_values"]["2"])

    assert targeted["naive"]["final"]["chosen"]==["X","Y"]
    assert targeted["safe_durable_crash_C"]["final"]["chosen"]==["X"]
    assert targeted["safe_durable_crash_C"]["final"]["ballot_values"]["2"]=="X"
    assert targeted["safe_volatile_crash_C"]["final"]["chosen"]==["X","Y"]

    results={}
    for protocol in ("naive","safe_durable","safe_volatile"):
        print("\nCHECK",protocol)
        r=model_check(protocol)
        results[protocol]=r
        print(json.dumps({
            "states":r["states_explored"],
            "transitions":r["transitions_explored"],
            "limit":r["hit_state_limit"],
            "safety":r["safety_holds"],
            "counterexample_len":len(r["counterexample_trace"]),
        },indent=2))
        if r["counterexample_trace"]:
            for i,x in enumerate(r["counterexample_trace"],1):
                print(i,x["action"],"chosen=",x["state"]["chosen"])

    assert results["naive"]["safety_holds"] is False
    assert results["safe_durable"]["hit_state_limit"] is False
    assert results["safe_durable"]["safety_holds"] is True
    assert results["safe_volatile"]["safety_holds"] is False

    OUT.write_text(json.dumps({
        "targeted":targeted,
        "bounded_exhaustive":results,
        "model":{
            "nodes":list(NODES),
            "quorum":QUORUM,
            "ballots":list(BALLOTS),
            "partitions":{k:[sorted(x) for x in v] for k,v in PARTITIONS.items()},
            "fault_model":"crash/restart only at ballot phase boundaries; message delivery once; partition changes only at prepare",
        },
    },indent=2),encoding="utf-8")
    print("\n5-node phased checker PASS")


if __name__=="__main__":
    main()
