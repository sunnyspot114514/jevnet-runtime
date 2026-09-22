# Contributing

Thanks for your interest in JevNet Runtime.

## Local setup

Python 3.12 is recommended.

```bash
python -m pip install -e ".[research]"
python -m pytest -q
python -m sar_runtime demo
```

## Runtime changes

For changes under `sar_runtime/`:

1. keep model-specific code outside the trusted runtime core;
2. prefer explicit typed records over hidden mutable state;
3. fail closed when authority evidence is missing or malformed;
4. preserve idempotency / fencing / replay semantics;
5. add package-level tests for new authority transitions.

## Plugin / service seams

New backends should normally implement an existing seam:

- `DurableStore`
- `ProviderAdapter`
- `LeaseCoordinator`

Only add a new service seam when the responsibility cannot be expressed through an existing one.

Plugin startup must fail loudly on unresolved dependencies or duplicate service providers.

## Research experiments

Frozen experiments are append-only research evidence.

Once a runner / benchmark has been frozen and executed:

- do not edit its cases, labels, thresholds, or prompts in place;
- do not overwrite result files;
- create a new version / run id for follow-up work;
- label post-hoc diagnostics as post-hoc;
- distinguish exhaustive completion from state-cap / timeout results.

This repository intentionally preserves negative and inconclusive results.

Early frozen text artifacts were hashed on a Windows CRLF worktree. Cross-platform integrity checks normalize checkout line endings back to that historical byte representation before hashing; the frozen artifact contents and published hashes remain unchanged.

## Pull requests

A useful PR should include:

- a concise problem statement;
- the authority / failure invariant being changed;
- tests;
- documentation if the public API or runtime semantics change.

Please avoid unrelated generated artifacts, local caches, model weights, API keys, and result directories.
