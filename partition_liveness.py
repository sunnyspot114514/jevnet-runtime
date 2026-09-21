#!/usr/bin/env python3
"""Safety vs liveness under partitions for a 5-replica quorum-3 runtime.

Enumerates all unique set partitions of five replicas into non-empty network
components and all current-leader placements.

Questions:
- Can the current leader reach a quorum?
- Does some component contain a quorum and therefore could elect a new leader?
- Is progress impossible without violating quorum safety?

This is an availability analysis, not a consensus safety proof.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

OUT = Path("partition_liveness_analysis.json")

NODES = ("A","B","C","D","E")
QUORUM = 3


def set_partitions(items):
    """Yield unique unordered set partitions."""
    if not items:
        yield []
        return
    first=items[0]
    for rest in set_partitions(items[1:]):
        # new block
        yield [frozenset({first})] + rest
        # add to existing block
        for i in range(len(rest)):
            yield rest[:i] + [rest[i] | {first}] + rest[i+1:]


def canonical_partition(parts):
    return tuple(sorted((tuple(sorted(p)) for p in parts), key=lambda x:(len(x),x)))


def unique_partitions():
    seen=set()
    out=[]
    for p in set_partitions(list(NODES)):
        cp=canonical_partition(p)
        if cp not in seen:
            seen.add(cp)
            out.append(tuple(frozenset(x) for x in cp))
    return out


def component_of(partition,node):
    for c in partition:
        if node in c:
            return c
    raise KeyError(node)


def analyze():
    rows=[]
    parts=unique_partitions()

    for p in parts:
        quorum_components=[c for c in p if len(c)>=QUORUM]
        any_quorum=bool(quorum_components)

        for leader in NODES:
            comp=component_of(p,leader)
            leader_can_progress=len(comp)>=QUORUM

            if leader_can_progress:
                classification="CURRENT_LEADER_CAN_PROGRESS"
            elif any_quorum:
                classification="ELECTION_NEEDED_IN_MAJORITY_COMPONENT"
            else:
                classification="NO_QUORUM_FAIL_STOP"

            rows.append({
                "partition":[sorted(c) for c in p],
                "shape":sorted((len(c) for c in p),reverse=True),
                "leader":leader,
                "leader_component":sorted(comp),
                "leader_can_progress":leader_can_progress,
                "quorum_components":[sorted(c) for c in quorum_components],
                "classification":classification,
            })

    return rows


def main():
    rows=analyze()
    counts={}
    shape_counts={}
    for r in rows:
        counts[r["classification"]]=counts.get(r["classification"],0)+1
        key="-".join(map(str,r["shape"]))
        shape_counts.setdefault(key,{})
        c=r["classification"]
        shape_counts[key][c]=shape_counts[key].get(c,0)+1

    print("unique partitions",len(unique_partitions()))
    print("leader/partition states",len(rows))
    print("classification counts",json.dumps(counts,indent=2))
    print("\nby partition shape")
    print(json.dumps(shape_counts,indent=2))

    examples={}
    for cls in counts:
        examples[cls]=next(r for r in rows if r["classification"]==cls)
    print("\nexamples")
    print(json.dumps(examples,indent=2))

    # In a 2|3 split, minority leader stalls but majority can elect.
    assert any(
        r["shape"]==[3,2]
        and len(r["leader_component"])==2
        and r["classification"]=="ELECTION_NEEDED_IN_MAJORITY_COMPONENT"
        for r in rows
    )

    # Any partition with largest component <3 must fail-stop for every leader.
    for r in rows:
        if max(r["shape"])<QUORUM:
            assert r["classification"]=="NO_QUORUM_FAIL_STOP"

    # If current leader has >=3 reachable replicas, it can form quorum.
    for r in rows:
        if len(r["leader_component"])>=QUORUM:
            assert r["leader_can_progress"] is True

    OUT.write_text(json.dumps({
        "nodes":list(NODES),
        "quorum":QUORUM,
        "unique_partition_count":len(unique_partitions()),
        "leader_partition_state_count":len(rows),
        "classification_counts":counts,
        "shape_counts":shape_counts,
        "examples":examples,
        "rows":rows,
    },indent=2),encoding="utf-8")
    print("\nPartition liveness invariants PASS")


if __name__=="__main__":
    main()
