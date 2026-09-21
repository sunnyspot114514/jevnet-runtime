# Round 12 — Reusable State-Aware Runtime Package

Date: 2026-09-22

This round turns the previously separate research scripts into a minimal reusable
Python runtime core.

Package:

sar_runtime/

The package is deliberately model-agnostic.

Jev/LLM integrations remain outside the trusted runtime core.

## 1. Stable typed interfaces

The package now exposes typed records for:

- ToolCallProposal
- ProposalRecord
- CapabilityManifestEntry
- ValidationResult
- AuthorizationVote
- DurableAuthorizationRecord
- DispatchIntent
- ProviderReceipt
- ReconciliationRecord
- CanonicalOutcomeCommit
- ProviderCapabilities
- ReplicatedCommitCertificate

This makes authority transitions explicit in code rather than implicit in a
single orchestration function.

## 2. Capability Manifest is part of the runtime core

CapabilityManifest owns:

- tool_id -> effect_class mapping
- scope
- reversibility
- allowed effect set
- manifest version
- manifest hash

Proposal metadata cannot redefine tool authority.

A model may propose:

filesystem.chmod

but the runtime still resolves it using the registry-owned capability identity.

## 3. Authorization quorum is separate from capability validation

issue_dar requires both:

1. proposal passes deterministic CapabilityManifest validation;
2. enough distinct authorizer identities approve the exact proposal hash.

Duplicate votes from the same identity do not increase quorum count.

Therefore:

semantic quorum approval
is necessary but not sufficient.

A unanimous semantic vote cannot override a hard capability veto.

## 4. DAR binds authorization evidence

DurableAuthorizationRecord contains:

- action_id
- auth_id
- proposal_hash
- manifest version/hash
- normalized calls
- normalized calls hash
- distinct approver identities
- threshold
- idempotency key
- authorization generation

This makes downstream dispatch independent of mutable model memory.

## 5. DispatchIntent binds execution to DAR

RuntimeEngine creates DispatchIntent only after revalidating the current
CapabilityManifest against the DAR.

Intent binds:

- action_id
- auth_id
- proposal_hash
- idempotency key
- fencing token
- payload hash

Dispatch checks these bindings again before calling the provider.

## 6. Provider adapter exposes runtime capabilities

The current InMemoryProvider demonstrates:

- idempotency
- status query
- fencing

ProviderCapabilities also reserves explicit flags for:

- compensation
- transactional commit

This follows the earlier exactly-once boundary result: runtime guarantees must
depend on provider primitives, not only runtime intention.

## 7. Reconciliation is authoritative over observations

RuntimeEngine.reconcile validates receipts against the DAR:

- auth_id
- proposal_hash
- idempotency key
- success status
- result equality

Forged/mismatched receipts remain rejected evidence.

A valid receipt produces a CanonicalOutcomeCommit with a stable coc_hash.

## 8. Replicated commit certificate remains a separate authority upgrade

A local COC does not become globally canonical merely because it exists.

The package therefore separates:

CanonicalOutcomeCommit

from:

ReplicatedCommitCertificate

The certificate requires a quorum of distinct replicas and binds to the COC
value hash.

This preserves the Round-7/8 distinction between local outcome authority and
global canonical authority.

## 9. Package integration tests

New package-level tests verify:

1. unanimous semantic approval cannot bypass chmod capability veto;
2. duplicate authorizer identity cannot manufacture quorum;
3. allowed local action produces DAR;
4. duplicate dispatch with same idempotency key produces one provider effect;
5. stale fencing token is rejected;
6. forged receipt cannot become canonical;
7. valid receipt produces COC;
8. replicated commit certificate requires quorum;
9. manifest version change invalidates old DAR;
10. unknown tools and explicit external target scope fail closed.

The package test suite passes independently.

## 10. Architectural consequence

The runtime can now be imported without importing Jev.

This is important.

The trusted computing base no longer assumes:
- one particular model;
- one semantic router;
- one authorizer implementation.

Any model may sit above:

proposal / vote interfaces

while the durable runtime protocol remains unchanged.

The architecture is now structurally:

untrusted probabilistic semantic layer
→ typed proposals/votes
→ deterministic authority runtime
→ provider adapters
→ replicated canonical state

## 11. Next package work

Highest-value engineering tasks:

1. Durable storage interface for DAR/Intent/Observation/COC records.
2. Provider adapter protocol rather than only InMemoryProvider.
3. Lease/fencing coordinator interface.
4. Replicated-log backend interface.
5. Compensation/Saga API.
6. Crash-recovery journal replay inside the package.
7. Jev adapter package that converts tool selection and votes into runtime records.
8. Property-based tests for arbitrary proposal/tool bundles.
