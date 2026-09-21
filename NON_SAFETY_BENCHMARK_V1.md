# Frozen non-safety topology benchmark v1

Created after the graph-message protocol and FlyGraph/control graphs were fixed.

The benchmark contains eight distributed reasoning tasks:
- set majority
- arithmetic modulo aggregation
- long-range key/value lookup
- ordered state update
- graph reachability
- distributed propositional logic
- directed motif detection
- set-frequency aggregation

Each task has exactly six source slots, mapped in fixed order to the six graph nodes in flygraph_controls_v1.json.

The graph runner uses:
- local-only initialization
- two synchronous message-passing rounds
- fixed readout node mAL_m8
- no global raw-fact access at final readout

Do not modify tasks, expected labels, graph topology, packet protocol, or number of rounds after freezing. Any changes require v2.
