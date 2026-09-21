# Frozen runtime state benchmark v2

Created after runtime_state_v2_runner.py was implemented and hashed.

Runner pre-freeze SHA-256:
3de82b912b361feb4c629f7a7457e5d97691b2d03deec85bb401ebd642c92afd

Pipelines:
- direct Jev final-state selection
- hybrid gated: deterministic metadata extraction + Jev event-type semantics + deterministic reducer
- structured receipt: oracle machine-native receipt + deterministic reducer

All metadata needed for the hybrid parser is explicitly present in event text.
The structured receipt pipeline is a runtime reference, not a model baseline.

No prompt, reducer, candidate-state, event-text, or label tuning after freezing.
