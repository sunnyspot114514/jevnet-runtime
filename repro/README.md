# Public Reproduction Bundle

This directory contains small, sanitized summaries of the main claims surfaced in the root README.

It deliberately does **not** contain API keys, raw provider secrets, local machine paths, or ignored result directories.

## Evidence classes

### Preliminary model comparison

`capability_manifest_v1_summary.json`

A 24-case paired comparison between:
- direct semantic authorization quorum;
- Jev tool planning followed by deterministic Capability Manifest gating.

Important limitation: this is **not** a single-variable ablation. The two pipelines differ in prompt, output space, and downstream gate. The 24/24 vs 22/24 difference therefore cannot be causally attributed to the gate alone.

Frozen benchmark:
- `../jev_capability_benchmark_v1.json`
- SHA-256: `f0cfaab8315b0a0073b8a76101b71393c0d1135582da4eef7cb9681327008898`

### Correlated authorizer error

`authorizer_v2_summary.json` records the frozen 32-case same-model quorum result in which B26 was a unanimous false authorization.

### Fault-injection simulation

`fault_simulation_summary.json` is a deterministic/randomized **simulation result**, not a production reliability measurement.

### Finite-model checking

`finite_model_check_summary.json` is a result inside a stated finite single-slot model. It is not a proof of full Paxos/Raft correctness or production distributed-system reliability.

### Coupled context recovery

`context_recovery_summary.json` summarizes the in-memory/event-log experiment that reconstructs model-visible context/memory after process loss and compares it with the no-crash canonical projection.

It is not a real power-loss / disk-durability experiment.

### SQLite cross-process recovery

`sqlite_context_process_summary.json` records a stronger reference test: one Python process writes canonical state to `SQLiteDurableStore`, exits, and a second Python process reconstructs the model-visible view from the database file alone. The recovered hash matches exactly. This still does **not** constitute a physical power-loss or filesystem-corruption test.

### Cross-process hard-crash matrix

`sqlite_hard_crash_matrix_summary.json` summarizes seven abrupt process-kill cut points across DAR, Intent, provider effect, Receipt, Reconciliation, COC, and model-context projection. Runtime journal, provider effects, and lease/fence state all use separate SQLite reference stores. Every recovered case keeps exactly one provider effect and reconstructs the no-crash context projection.

This is still a process-crash experiment, not a physical power-loss or storage-corruption guarantee.

### SQLite transaction/WAL crash boundary

`sqlite_wal_crash_summary.json` kills a child process before or after SQLite `COMMIT`, for one-record and two-record transactions. Pre-commit batches are invisible after reopen; committed batches are fully visible; `PRAGMA integrity_check` reports `ok` in all four cases. This is a process-crash transaction-boundary test, not a physical power-loss test.

### Ambiguous provider recovery

`ambiguous_recovery_summary.json` records the regression for a provider with neither idempotency nor status query: ambiguous execution is kept unresolved and is not blindly retried.

## Reproducing locally

```bash
python -m pip install -e ".[research]"
python -m pytest -q
python context_recovery_experiment.py
python journal_recovery_stress.py
python replicated_log_5node_3ballot_reduced.py
```

Jev experiments require a local `.env` containing `TYPESAFE_API_KEY`.