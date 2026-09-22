# Architecture

JevNet Runtime separates semantic proposal from execution authority.

## Main path

```text
Model / Planner
    |
    v
ToolCallProposal
    |
    v
CapabilityManifest.validate()
    |
    v
AuthorizationVote quorum
    |
    v
DurableAuthorizationRecord
    |
    v
DispatchIntent + fencing + idempotency
    |
    v
ProviderReceipt
    |
    v
ReconciliationRecord
    |
    v
CanonicalOutcomeCommit
    |
    v
ReplicatedCommitCertificate
```

## Authority levels

A record does not automatically inherit the authority of the next layer.

- A model proposal is not authorization.
- Authorization is not proof that an external effect occurred.
- A provider receipt is not automatically canonical.
- A local COC is not automatically globally committed.

Each transition has an explicit validator.

## Service seams

The default harness exposes replaceable services:

- `manifest`
- `backing_store`
- `store`
- `provider`
- `leases`
- `durable_runtime`

`PluginManager` activates plugins only after their dependencies exist.
Duplicate service providers and unresolved dependencies fail loudly.

## Durable state

`EventSourcedStore` wraps a `DurableStore`. Its physical records are
`SessionEvent` objects; the ordinary runtime store API returns the payload
projection.

This keeps the execution API small while preserving an append-only replay log.

## Approval

`ApprovalService` is intentionally separate from authorization quorum.

Human/operator approval has four outcomes:

- `allowed-once`
- `rejected`
- `cancelled`
- `unavailable`

Only the first grants authority.

## Provider contract

Provider guarantees are explicit capabilities:

```text
supports_idempotency
supports_status_query
supports_compensation
supports_fencing
supports_transactional_commit
```

The runtime must not claim exactly-once semantics if the provider exposes no
primitive capable of resolving an ambiguous outcome.

## Distributed outcome

`CanonicalOutcomeCommit@@ is the local durable result.

`ReplicatedCommitCertificate@@ is a separate authority upgrade used to represent
quorum agreement over the COC hash.

The current package contains certificate helpers and research model checkers; it
is not a production consensus implementation.
