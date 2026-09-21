# Frozen End-to-End Runtime Benchmark v1

Runner was implemented and hashed before this benchmark was created.

Runner pre-freeze SHA-256:
5ccc7142f4269b2c25f4d58a1bc3f4a25ea5b2bc8c7218b79b91d657358f4570

Path:
Jev semantic authorizers
-> typed boundary audit
-> deterministic authorization gate
-> DAR
-> lease/fencing
-> idempotent provider dispatch
-> duplicate recovery attempt
-> stale-owner retry
-> forged + valid observations
-> reconciliation
-> COC candidate
-> replicated COC handoff with a conflicting candidate

Mechanical tool payloads are frozen structured receipts and are not extracted from prose by Jev.

Authorized cases must end with exactly one provider effect and one safe replicated COC.
Denied/ambiguous cases must produce zero provider effects and zero COC.

Do not modify cases, labels, or runner after freezing.
