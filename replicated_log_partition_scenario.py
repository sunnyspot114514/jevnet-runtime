#!/usr/bin/env python3
"""Forced network-partition scenario for replicated COC.

Schedule:
  FULL -> AB|C
  A prepares/chooses X with quorum AB
  network -> BC|A
  C starts ballot 2 with candidate Y using quorum BC

Naive protocol ignores B's accepted X and selects Y -> conflicting COC.
Safe protocol inherits B's accepted X -> no conflict.
"""

from __future__ import annotations

import json
from pathlib import Path

from replicated_log_modelcheck import initial_state, successors, state_json

OUT = Path("replicated_log_partition_scenario.json")


def pick(state, protocol, predicate, label):
    matches = [(a, s) for a, s in successors(state, protocol) if predicate(a)]
    if not matches:
        raise RuntimeError(f"no transition for {label}")
    # Deterministic if several state-equivalent actions somehow match.
    matches.sort(key=lambda x: x[0].text())
    return matches[0]


def run(protocol):
    s = initial_state()
    trace = []

    def step(predicate, label):
        nonlocal s
        action, nxt = pick(s, protocol, predicate, label)
        s = nxt
        trace.append({"action": action.text(), "state": state_json(s)})

    step(lambda a: a.kind=="partition" and a.detail[0]=="AB_C", "partition AB_C")
    step(
        lambda a: (
            a.kind=="prepare"
            and a.detail[0]==1
            and a.detail[2]=="X"
            and tuple(a.detail[3])==("A","B")
        ),
        "A prepare b1 X AB",
    )
    step(lambda a: a.kind=="accept" and a.detail[0]==1 and a.detail[2]=="A", "A accepts X")
    step(lambda a: a.kind=="accept" and a.detail[0]==1 and a.detail[2]=="B", "B accepts X")

    step(lambda a: a.kind=="partition" and a.detail[0]=="BC_A", "partition BC_A")
    step(
        lambda a: (
            a.kind=="prepare"
            and a.detail[0]==2
            and a.detail[2]=="Y"
            and tuple(a.detail[3])==("B","C")
        ),
        "C prepare b2 candidate Y BC",
    )
    step(lambda a: a.kind=="accept" and a.detail[0]==2 and a.detail[2]=="B", "B accepts ballot2")
    step(lambda a: a.kind=="accept" and a.detail[0]==2 and a.detail[2]=="C", "C accepts ballot2")

    return {
        "protocol": protocol,
        "trace": trace,
        "final": state_json(s),
    }


def main():
    naive=run("naive")
    safe=run("safe")
    print("NAIVE FORCED PARTITION TRACE")
    for i,x in enumerate(naive["trace"],1):
        print(i,x["action"],"chosen=",x["state"]["chosen"])
    print("\nSAFE FORCED PARTITION TRACE")
    for i,x in enumerate(safe["trace"],1):
        print(i,x["action"],"chosen=",x["state"]["chosen"])

    assert naive["final"]["chosen"]==["X","Y"]
    assert safe["final"]["chosen"]==["X"]
    # Safe ballot 2 must inherit X despite leader's candidate Y.
    assert safe["final"]["ballot_values"]["2"]=="X"

    OUT.write_text(json.dumps({"naive":naive,"safe":safe},indent=2),encoding="utf-8")
    print("\nForced partition scenario PASS")


if __name__=="__main__":
    main()
