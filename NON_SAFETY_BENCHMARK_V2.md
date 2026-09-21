# Frozen non-safety topology benchmark v2

Created after non_safety_v2_runner.py was fixed and hashed.

Purpose: fresh confirmation of the exploratory v1 architecture result.

Architectures are unchanged from v1:
- Direct full-information reference
- dense MLP
- RNN with cumulative raw residual memory
- one-block Transformer-like all-to-all packet update
- sparse MoE

v2 includes fresh values and deliberately includes negative graph-reachability, negative logical-entailment, and negative motif examples.

Do not tune architecture prompts, packet schema, or task labels after freezing.
