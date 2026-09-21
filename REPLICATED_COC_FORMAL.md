# Replicated COC formal-model note

The executable exhaustive checker is `replicated_log_modelcheck.py`.

A matching TLA+ specification is provided in `ReplicatedCOC.tla`, with:
- `ReplicatedCOC_Safe.cfg`
- `ReplicatedCOC_Naive.cfg`

The current Devspace environment does not have Java/TLC installed, so the TLA+
spec was not executed here. The Python checker exhaustively explores the same
finite abstraction and is covered by regression tests.

Expected TLC behavior:
- Naive config: Safety invariant violation.
- Safe config: no Safety violation within the finite state space.
