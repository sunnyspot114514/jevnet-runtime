# Frozen runtime state benchmark v1

Runner was implemented and hashed before this file was created.

Pre-freeze runner SHA-256:
55a2927bbb259f8b71db6e888047abe870e02d1dc950329dd701e6289822aac6

Families:
- conflict writes with version/priority resolution
- revocation/tombstones and stale replay
- timestamp/TTL + sequence staleness
- atomic multi-key transactions

Pipelines:
- direct Jev final-state choice
- Jev Proposal parsing + deterministic validation/reducer + canonical commit

The oracle_event structures are used only for benchmark validation and parser scoring.
They are not passed to Jev.

Do not tune parser prompts, reducer rules, candidate states, labels, or event texts after freezing.
