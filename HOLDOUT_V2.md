# Frozen holdout v2

Created only after the following hybrid architectures were implemented:
- transformer_moe
- transformer_global_skip

Purpose: fresh evaluation after holdout_v1 exposed Transformer attention propagation errors.

The prompts and expected labels must not be changed after freezing. Any architecture or prompt changes inspired by v2 results require holdout_v3.

Architecture code existed before this file was created.
