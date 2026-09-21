#!/usr/bin/env python3
"""Exhaustive model checker for replicated Canonical Outcome Commit.

Three replicas: A, B, C
Quorum: 2
Ballot/terms:
  1 -> leader A
  2 -> leader C

Network can move between:
  FULL
  AB|C
  AC|B
  BC|A

One log slot represents the canonical outcome for one action.
Conflicting candidate values: X and Y.

Two protocols:

NAIVE
- a higher-term leader may prepare a fresh conflicting value even if its
  phase-1 quorum reports an older accepted value.

SAFE
- phase-1 selects the value with highest accepted ballot from its quorum;
- only if the quorum reports no accepted value may the leader use its own
  candidate;
- acceptors reject ballots below their promised term.

Safety property:
  At most one distinct value may ever become quorum-chosen for this log slot.

The checker explores every reachable finite state until fixpoint and returns
a shortest counterexample trace when the safety invariant fails.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable, NamedTuple

OUT = Path("replicated_log_modelcheck_analysis.json")

NODES = ("A", "B", "C")
VALUES = ("X", "Y")
BALLOTS = (1, 2)
LEADER = {1: "A", 2: "C"}
QUORUM = 2

PARTITIONS = {
    "FULL": (frozenset({"A", "B", "C"}),),
    "AB_C": (frozenset({"A", "B"}), frozenset({"C"})),
    "AC_B": (frozenset({"A", "C"}), frozenset({"B"})),
    "BC_A": (frozenset({"B", "C"}), frozenset({"A"})),
}


class Replica(NamedTuple):
    promised: int
    accepted_ballot: int
    accepted_value: str | None


class State(NamedTuple):
    replicas: tuple[Replica, Replica, Replica]
    partition: str
    ballot_values: tuple[str | None, str | None]  # ballots 1,2
    chosen: frozenset[str]


@dataclass(frozen=True)
class Action:
    kind: str
    detail: tuple

    def text(self) -> str:
        if self.kind == "partition":
            return f"network -> {self.detail[0]}"
        if self.kind == "prepare":
            ballot, leader, candidate, quorum, selected = self.detail
            return (
                f"{leader} PREPARE b{ballot} candidate={candidate} "
                f"quorum={''.join(quorum)} selected={selected}"
            )
        if self.kind == "accept":
            ballot, leader, node, value, accepted = self.detail
            verdict = "ACCEPT" if accepted else "REJECT_STALE"
            return f"{leader} b{ballot} -> {node} value={value}: {verdict}"
        return f"{self.kind}{self.detail}"


def node_index(n: str) -> int:
    return NODES.index(n)


def initial_state() -> State:
    empty = Replica(0, 0, None)
    return State(
        replicas=(empty, empty, empty),
        partition="FULL",
        ballot_values=(None, None),
        chosen=frozenset(),
    )


def component(partition: str, node: str) -> frozenset[str]:
    for comp in PARTITIONS[partition]:
        if node in comp:
            return comp
    raise KeyError(node)


def reachable(partition: str, a: str, b: str) -> bool:
    return b in component(partition, a)


def possible_quorums(partition: str, leader: str) -> list[tuple[str, ...]]:
    comp = sorted(component(partition, leader))
    if len(comp) < QUORUM:
        return []
    return [
        tuple(q)
        for q in combinations(comp, QUORUM)
        if leader in q
    ]


def highest_accepted_value(state: State, quorum: tuple[str, ...]) -> str | None:
    reports = []
    for n in quorum:
        r = state.replicas[node_index(n)]
        if r.accepted_ballot > 0 and r.accepted_value is not None:
            reports.append((r.accepted_ballot, r.accepted_value))
    if not reports:
        return None
    max_ballot = max(b for b, _ in reports)
    vals = {v for b, v in reports if b == max_ballot}
    # Unique ballot numbers imply one value at a ballot in this model.
    if len(vals) != 1:
        raise RuntimeError(f"impossible same-ballot conflict in reports: {reports}")
    return next(iter(vals))


def with_replica(state: State, node: str, replica: Replica) -> State:
    rows = list(state.replicas)
    rows[node_index(node)] = replica
    return State(
        replicas=tuple(rows),
        partition=state.partition,
        ballot_values=state.ballot_values,
        chosen=state.chosen,
    )


def chosen_after_accept(state: State, ballot: int, value: str) -> frozenset[str]:
    count = sum(
        r.accepted_ballot == ballot and r.accepted_value == value
        for r in state.replicas
    )
    chosen = set(state.chosen)
    if count >= QUORUM:
        chosen.add(value)
    return frozenset(chosen)


def successors(state: State, protocol: str) -> Iterable[tuple[Action, State]]:
    # Network can repartition/heal arbitrarily.
    for p in PARTITIONS:
        if p != state.partition:
            yield Action("partition", (p,)), state._replace(partition=p)

    # Prepare each ballot once.
    for ballot in BALLOTS:
        leader = LEADER[ballot]
        bidx = BALLOTS.index(ballot)
        if state.ballot_values[bidx] is not None:
            continue

        for quorum in possible_quorums(state.partition, leader):
            # Every acceptor in phase-1 must be able to promise this ballot.
            if any(state.replicas[node_index(n)].promised >= ballot for n in quorum):
                continue

            for candidate in VALUES:
                inherited = highest_accepted_value(state, quorum)
                if protocol == "safe" and inherited is not None:
                    selected = inherited
                else:
                    selected = candidate

                reps = list(state.replicas)
                for n in quorum:
                    i = node_index(n)
                    r = reps[i]
                    reps[i] = Replica(
                        promised=ballot,
                        accepted_ballot=r.accepted_ballot,
                        accepted_value=r.accepted_value,
                    )

                bvals = list(state.ballot_values)
                bvals[bidx] = selected

                nxt = State(
                    replicas=tuple(reps),
                    partition=state.partition,
                    ballot_values=tuple(bvals),
                    chosen=state.chosen,
                )
                yield Action(
                    "prepare",
                    (ballot, leader, candidate, quorum, selected),
                ), nxt

    # Phase-2 accept messages can be delivered one replica at a time.
    for ballot in BALLOTS:
        leader = LEADER[ballot]
        bidx = BALLOTS.index(ballot)
        value = state.ballot_values[bidx]
        if value is None:
            continue

        for node in NODES:
            if not reachable(state.partition, leader, node):
                continue

            i = node_index(node)
            r = state.replicas[i]

            if ballot < r.promised:
                # Rejection is observationally useful but state-preserving;
                # don't emit self-loop into BFS.
                continue

            # Already accepted exactly this ballot/value: no state change.
            if r.accepted_ballot == ballot and r.accepted_value == value:
                continue

            nr = Replica(
                promised=max(r.promised, ballot),
                accepted_ballot=ballot,
                accepted_value=value,
            )
            reps = list(state.replicas)
            reps[i] = nr
            temp = State(
                replicas=tuple(reps),
                partition=state.partition,
                ballot_values=state.ballot_values,
                chosen=state.chosen,
            )
            chosen = chosen_after_accept(temp, ballot, value)
            nxt = temp._replace(chosen=chosen)
            yield Action(
                "accept",
                (ballot, leader, node, value, True),
            ), nxt


def state_json(state: State) -> dict:
    return {
        "partition": state.partition,
        "replicas": {
            n: {
                "promised": state.replicas[i].promised,
                "accepted_ballot": state.replicas[i].accepted_ballot,
                "accepted_value": state.replicas[i].accepted_value,
            }
            for i, n in enumerate(NODES)
        },
        "ballot_values": {
            str(ballot): state.ballot_values[i]
            for i, ballot in enumerate(BALLOTS)
        },
        "chosen": sorted(state.chosen),
    }


def model_check(protocol: str) -> dict:
    start = initial_state()
    q = deque([start])
    parent: dict[State, tuple[State | None, Action | None]] = {
        start: (None, None)
    }
    transitions = 0
    stale_rejection_opportunities = 0

    violation: State | None = None

    while q:
        state = q.popleft()

        if len(state.chosen) > 1:
            violation = state
            break

        # Count stale-leader sends that the promise rule would reject.
        for ballot in BALLOTS:
            leader = LEADER[ballot]
            value = state.ballot_values[BALLOTS.index(ballot)]
            if value is None:
                continue
            for node in NODES:
                if not reachable(state.partition, leader, node):
                    continue
                if ballot < state.replicas[node_index(node)].promised:
                    stale_rejection_opportunities += 1

        for action, nxt in successors(state, protocol):
            transitions += 1
            if nxt not in parent:
                parent[nxt] = (state, action)
                q.append(nxt)

    trace = []
    if violation is not None:
        cur = violation
        rev = []
        while True:
            prev, action = parent[cur]
            if prev is None:
                break
            rev.append({
                "action": action.text(),
                "state": state_json(cur),
            })
            cur = prev
        trace = list(reversed(rev))

    chosen_hist = {}
    for state in parent:
        key = ",".join(sorted(state.chosen)) or "NONE"
        chosen_hist[key] = chosen_hist.get(key, 0) + 1

    return {
        "protocol": protocol,
        "states_explored": len(parent),
        "transitions_explored": transitions,
        "stale_rejection_opportunities": stale_rejection_opportunities,
        "safety_holds": violation is None,
        "chosen_state_histogram": chosen_hist,
        "counterexample_trace": trace,
        "violation_state": None if violation is None else state_json(violation),
    }


def main():
    naive = model_check("naive")
    safe = model_check("safe")

    result = {
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
            "property": "never choose both X and Y for the same canonical outcome slot",
        },
        "naive": naive,
        "safe": safe,
    }

    print("NAIVE")
    print(json.dumps({
        k: naive[k]
        for k in (
            "states_explored",
            "transitions_explored",
            "safety_holds",
            "chosen_state_histogram",
        )
    }, indent=2))

    if naive["counterexample_trace"]:
        print("\nShortest naive counterexample:")
        for i, step in enumerate(naive["counterexample_trace"], 1):
            print(f"{i}. {step['action']}")
            print("   chosen =", step["state"]["chosen"])
            print("   partition =", step["state"]["partition"])
            print("   replicas =", step["state"]["replicas"])

    print("\nSAFE")
    print(json.dumps({
        k: safe[k]
        for k in (
            "states_explored",
            "transitions_explored",
            "stale_rejection_opportunities",
            "safety_holds",
            "chosen_state_histogram",
        )
    }, indent=2))

    assert naive["safety_holds"] is False
    assert len(naive["counterexample_trace"]) > 0
    assert safe["safety_holds"] is True

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nReplicated log model-check invariants PASS")


if __name__ == "__main__":
    main()
