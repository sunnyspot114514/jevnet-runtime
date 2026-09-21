#!/usr/bin/env python3
"""5-replica replicated COC model checker with crashes and partitions.

Replicas: A,B,C,D,E
Quorum: 3
Ballots:
  1 -> A
  2 -> C
  3 -> E
Values: X,Y

Faults:
- network partitions/heal
- accept messages delayed arbitrarily
- replicas crash/restart
- optional loss of promised/accepted history on crash

Protocols:
  naive
    New leader may ignore accepted history.

  safe_durable
    Phase-1 inherits highest accepted value from quorum.
    promised/accepted survive crash.

  safe_volatile
    Same Phase-1 inheritance rule, but crash erases promised/accepted state.
    This intentionally models a broken implementation.

Safety:
  No two distinct values may ever become quorum-chosen for the same slot.

The model is intentionally single-slot and finite. It tests safety, not liveness.
"""

from __future__ import annotations

import json
from collections import deque
from itertools import combinations
from pathlib import Path
from typing import NamedTuple, Iterable

OUT = Path("replicated_log_5node_modelcheck_analysis.json")

NODES = ("A", "B", "C", "D", "E")
VALUES = ("X", "Y")
BALLOTS = (1, 2, 3)
LEADER = {1: "A", 2: "C", 3: "E"}
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
    up: bool


class State(NamedTuple):
    replicas: tuple[Replica, ...]
    partition: str
    ballot_values: tuple[str | None, ...]
    chosen: frozenset[str]


class Action(NamedTuple):
    kind: str
    detail: tuple

    def text(self) -> str:
        if self.kind == "partition":
            return f"network -> {self.detail[0]}"
        if self.kind == "crash":
            return f"CRASH {self.detail[0]}"
        if self.kind == "restart":
            return f"RESTART {self.detail[0]}"
        if self.kind == "prepare":
            ballot, leader, candidate, quorum, selected = self.detail
            return (
                f"{leader} PREPARE b{ballot} candidate={candidate} "
                f"quorum={''.join(quorum)} selected={selected}"
            )
        if self.kind == "accept":
            ballot, leader, node, value = self.detail
            return f"{leader} b{ballot} -> {node} ACCEPT {value}"
        return f"{self.kind}{self.detail}"


def idx(node: str) -> int:
    return NODES.index(node)


def initial_state() -> State:
    reps = tuple(Replica(0, 0, None, True) for _ in NODES)
    return State(
        replicas=reps,
        partition="FULL",
        ballot_values=(None,) * len(BALLOTS),
        chosen=frozenset(),
    )


def component(partition: str, node: str) -> frozenset[str]:
    for comp in PARTITIONS[partition]:
        if node in comp:
            return comp
    raise KeyError(node)


def reachable(state: State, a: str, b: str) -> bool:
    return (
        state.replicas[idx(a)].up
        and state.replicas[idx(b)].up
        and b in component(state.partition, a)
    )


def possible_quorums(state: State, leader: str) -> list[tuple[str, ...]]:
    if not state.replicas[idx(leader)].up:
        return []
    comp = sorted(
        n for n in component(state.partition, leader)
        if state.replicas[idx(n)].up
    )
    if len(comp) < QUORUM:
        return []
    return [
        tuple(q)
        for q in combinations(comp, QUORUM)
        if leader in q
    ]


def highest_accepted_value(state: State, quorum: tuple[str, ...]) -> str | None:
    rows = []
    for n in quorum:
        r = state.replicas[idx(n)]
        if r.accepted_ballot > 0 and r.accepted_value is not None:
            rows.append((r.accepted_ballot, r.accepted_value))
    if not rows:
        return None
    m = max(b for b, _ in rows)
    vals = {v for b, v in rows if b == m}
    if len(vals) != 1:
        raise RuntimeError(f"same-ballot conflict: {rows}")
    return next(iter(vals))


def chosen_after(state: State, ballot: int, value: str) -> frozenset[str]:
    count = sum(
        r.accepted_ballot == ballot and r.accepted_value == value
        for r in state.replicas
    )
    out = set(state.chosen)
    if count >= QUORUM:
        out.add(value)
    return frozenset(out)


def crash_replica(state: State, node: str, protocol: str) -> State:
    reps = list(state.replicas)
    r = reps[idx(node)]
    if protocol == "safe_volatile":
        reps[idx(node)] = Replica(0, 0, None, False)
    else:
        reps[idx(node)] = Replica(
            r.promised, r.accepted_ballot, r.accepted_value, False
        )
    return state._replace(replicas=tuple(reps))


def restart_replica(state: State, node: str) -> State:
    reps = list(state.replicas)
    r = reps[idx(node)]
    reps[idx(node)] = Replica(
        r.promised, r.accepted_ballot, r.accepted_value, True
    )
    return state._replace(replicas=tuple(reps))


def successors(state: State, protocol: str) -> Iterable[tuple[Action, State]]:
    # Network moves.
    for p in PARTITIONS:
        if p != state.partition:
            yield Action("partition", (p,)), state._replace(partition=p)

    # Crash/restart one replica at a time.
    for n in NODES:
        r = state.replicas[idx(n)]
        if r.up:
            yield Action("crash", (n,)), crash_replica(state, n, protocol)
        else:
            yield Action("restart", (n,)), restart_replica(state, n)

    # Phase 1, once per ballot.
    for ballot in BALLOTS:
        leader = LEADER[ballot]
        bi = BALLOTS.index(ballot)
        if state.ballot_values[bi] is not None:
            continue

        for quorum in possible_quorums(state, leader):
            # Require every phase-1 acceptor to be able to promise this term.
            if any(state.replicas[idx(n)].promised >= ballot for n in quorum):
                continue

            for candidate in VALUES:
                inherited = highest_accepted_value(state, quorum)
                if protocol in ("safe_durable", "safe_volatile") and inherited is not None:
                    selected = inherited
                else:
                    selected = candidate

                reps = list(state.replicas)
                for n in quorum:
                    i = idx(n)
                    r = reps[i]
                    reps[i] = Replica(
                        promised=ballot,
                        accepted_ballot=r.accepted_ballot,
                        accepted_value=r.accepted_value,
                        up=True,
                    )
                bvals = list(state.ballot_values)
                bvals[bi] = selected

                yield Action(
                    "prepare", (ballot, leader, candidate, quorum, selected)
                ), State(
                    replicas=tuple(reps),
                    partition=state.partition,
                    ballot_values=tuple(bvals),
                    chosen=state.chosen,
                )

    # Phase 2 accept messages.
    for ballot in BALLOTS:
        leader = LEADER[ballot]
        bi = BALLOTS.index(ballot)
        value = state.ballot_values[bi]
        if value is None:
            continue

        for n in NODES:
            if not reachable(state, leader, n):
                continue
            i = idx(n)
            r = state.replicas[i]
            if ballot < r.promised:
                continue
            if r.accepted_ballot == ballot and r.accepted_value == value:
                continue

            reps = list(state.replicas)
            reps[i] = Replica(
                promised=max(r.promised, ballot),
                accepted_ballot=ballot,
                accepted_value=value,
                up=True,
            )
            temp = State(
                replicas=tuple(reps),
                partition=state.partition,
                ballot_values=state.ballot_values,
                chosen=state.chosen,
            )
            yield Action(
                "accept", (ballot, leader, n, value)
            ), temp._replace(chosen=chosen_after(temp, ballot, value))


def state_json(state: State) -> dict:
    return {
        "partition": state.partition,
        "replicas": {
            n: {
                "promised": state.replicas[i].promised,
                "accepted_ballot": state.replicas[i].accepted_ballot,
                "accepted_value": state.replicas[i].accepted_value,
                "up": state.replicas[i].up,
            }
            for i, n in enumerate(NODES)
        },
        "ballot_values": {
            str(b): state.ballot_values[i]
            for i, b in enumerate(BALLOTS)
        },
        "chosen": sorted(state.chosen),
    }


def reconstruct(parent, violation: State) -> list[dict]:
    cur = violation
    rev = []
    while True:
        prev, action = parent[cur]
        if prev is None:
            break
        rev.append({"action": action.text(), "state": state_json(cur)})
        cur = prev
    return list(reversed(rev))


def model_check(protocol: str, max_states: int = 400_000) -> dict:
    start = initial_state()
    q = deque([start])
    parent = {start: (None, None)}
    transitions = 0
    violation = None
    hit_limit = False

    while q:
        state = q.popleft()
        if len(state.chosen) > 1:
            violation = state
            break

        for action, nxt in successors(state, protocol):
            transitions += 1
            if nxt not in parent:
                parent[nxt] = (state, action)
                if len(parent) >= max_states:
                    hit_limit = True
                    q.clear()
                    break
                q.append(nxt)
        if hit_limit:
            break

    return {
        "protocol": protocol,
        "states_explored": len(parent),
        "transitions_explored": transitions,
        "hit_state_limit": hit_limit,
        "safety_holds_within_explored_space": violation is None,
        "counterexample_trace": [] if violation is None else reconstruct(parent, violation),
        "violation_state": None if violation is None else state_json(violation),
    }


def main():
    results = {}
    for protocol in ("naive", "safe_durable", "safe_volatile"):
        print("\nCHECK", protocol)
        r = model_check(protocol)
        results[protocol] = r
        print(json.dumps({
            "states_explored": r["states_explored"],
            "transitions_explored": r["transitions_explored"],
            "hit_state_limit": r["hit_state_limit"],
            "safety": r["safety_holds_within_explored_space"],
        }, indent=2))
        if r["counterexample_trace"]:
            print("counterexample length", len(r["counterexample_trace"]))
            for i, step in enumerate(r["counterexample_trace"], 1):
                print(i, step["action"], "chosen=", step["state"]["chosen"])

    # This broad 3-ballot model is intentionally exploratory. With the
    # current 400k-state cap, any protocol that hits the cap is INCONCLUSIVE:
    # absence of a counterexample is not a proof of safety.
    for protocol, r in results.items():
        r["conclusion"] = (
            "COUNTEREXAMPLE_FOUND"
            if not r["safety_holds_within_explored_space"]
            else "INCONCLUSIVE_STATE_LIMIT"
            if r["hit_state_limit"]
            else "EXHAUSTIVE_NO_COUNTEREXAMPLE"
        )

    OUT.write_text(json.dumps({
        "model": {
            "nodes": list(NODES),
            "quorum": QUORUM,
            "ballots": list(BALLOTS),
            "leaders": LEADER,
            "values": list(VALUES),
            "partitions": {
                k: [sorted(c) for c in comps]
                for k, comps in PARTITIONS.items()
            },
            "safety": "at most one distinct quorum-chosen value per slot",
        },
        "results": results,
    }, indent=2), encoding="utf-8")
    print("\nBroad 3-ballot checker complete; see per-protocol conclusion fields.")


if __name__ == "__main__":
    main()
