# Round 15 — HTTP Provider and Lease Boundaries

Date: 2026-09-22

This round moves the reference runtime across actual HTTP process boundaries.

The runtime process now talks to:
- a separate provider service over HTTP;
- a separate lease/fence service over HTTP.

Each service owns its own SQLite durable state.

The runtime process directly owns only its runtime journal.

---

## 1. HTTPProviderAdapter

Artifact:

sar_runtime/http_provider.py

The adapter implements a small explicit wire contract.

POST /effects

Headers:
- Idempotency-Key
- X-SAR-Action-ID
- X-SAR-Auth-ID
- X-SAR-Proposal-Hash
- X-SAR-Fence

Body:
- result payload

Successful response:
- typed ProviderReceipt JSON

GET /effects/{idempotency_key}

Responses:
- 200 -> authoritative ProviderReceipt
- 404 -> no known effect

A stale fence may be returned as HTTP 409 with a deterministic rejection body.

---

## 2. Ambiguous HTTP semantics

For effectful POST requests, the adapter treats the following as ambiguous:

- connection reset;
- timeout;
- HTTP 5xx;
- malformed body after nominal success.

The runtime does not infer failure from these conditions.

Recovery depends on provider capabilities.

### Query available

Query by idempotency key.

### Idempotency available

Safe retry is permitted.

### Neither available

Persist UnresolvedOutcome.

No blind retry.

---

## 3. Retriable unresolved state

An additional distinction is now implemented.

If the provider is temporarily unreachable but declares idempotent execution,
the runtime may persist:

UnresolvedOutcome
retry_safe = true

This prevents an infinite retry loop inside one recovery call while allowing a
later recovery invocation to resume safely.

If no reconciliation primitive exists:

retry_safe = false

and the action requires external reconciliation or operator escalation.

---

## 4. HTTPLeaseCoordinator

Artifact:

sar_runtime/http_lease.py

Contract:

POST /leases/{resource}/acquire

returns:

resource_id
owner_id
fence

GET /leases/{resource}

returns the current token or 404.

POST /leases/{resource}/release

releases only if owner and fence still match.

A stale token cannot release a newer owner.

Network/5xx failures raise LeaseCoordinatorUnavailable.

The runtime therefore fails closed before provider execution if execution
ownership cannot be acquired.

---

## 5. Reference HTTP services

Artifacts:

http_provider_reference_server.py
http_lease_reference_server.py

Both run as separate processes.

Reference provider:
- SQLite effect ledger
- idempotency
- status query
- fencing
- test-only response-drop mode

Reference lease service:
- SQLite lease ledger
- monotonic fences
- current owner query
- stale-release protection

These are test/reference services.

They do not implement:
- TLS
- authentication
- multi-tenant authorization
- rate limiting
- multi-host consensus

---

## 6. Provider response-loss probe

The reference provider can deliberately:

1. commit the effect;
2. close the HTTP connection before returning the first response.

Observed:

HTTPProviderAdapter raises AmbiguousProviderOutcome.

Subsequent GET by idempotency key returns the durable receipt.

DurableRuntime then reconciles and commits the outcome.

Provider effect count remains:

1

---

## 7. Cross-process HTTP crash probe

Artifact:

http_runtime_crash_probe.py

Processes:

1. runtime worker
2. runtime recovery worker
3. provider HTTP service
4. lease HTTP service

Durable state:

- runtime journal -> SQLite
- provider reality -> provider SQLite DB
- lease/fence -> lease SQLite DB

Runtime reaches provider and lease only through HTTP.

---

## 8. Crash cut points

The runtime worker is terminated after:

1. DispatchIntent
2. HTTP provider effect
3. ProviderReceipt
4. CanonicalOutcomeCommit

A fresh Python recovery process then opens the runtime DB and reconnects to the
two HTTP services.

---

## 9. Result

For every cut:

provider effect count:

1

CanonicalOutcomeCommit:

present

context projection:

identical to no-crash baseline

second recovery:

fixed point

provider integrity_check:

ok

lease integrity_check:

ok

---

## 10. Ownership handoff

Two cuts require recovery to reacquire execution ownership:

after_intent

after_http_effect

Old worker:

fence 1

Recovery worker:

fence 2

The runtime appends a superseding DispatchIntent under the newer fence.

Provider effect count still remains one.

---

## 11. Why this is stronger than the SQLite-only matrix

Round 13 used separate SQLite databases but the runtime called provider/lease
objects in-process.

Round 15 places provider and lease behind real HTTP process boundaries.

Therefore:
- request serialization is exercised;
- connection failure semantics are exercised;
- receipt parsing is exercised;
- remote status query is exercised;
- remote lease acquisition is exercised.

The runtime no longer directly reads either provider or lease databases.

---

## 12. What this still does not establish

This remains a same-host loopback experiment.

It does not test:
- TLS;
- authentication;
- real WAN latency;
- packet duplication/reordering;
- partial network partitions;
- DNS failure;
- proxy/load-balancer behavior;
- multi-host provider failover;
- physical power loss.

Those remain separate engineering and research boundaries.

---

## 13. Public HTTP contract

The reusable wire contract is documented in:

docs/HTTP_CONTRACT.md

The contract is intentionally small enough that a real provider or lease system
can expose a thin compatibility shim rather than adopting the entire SAR
runtime.

---

## 14. Updated architecture seam

The reusable execution path can now be:

runtime journal
    |
DurableRuntime
    |
    +--> HTTPLeaseCoordinator --> remote lease service
    |
    +--> HTTPProviderAdapter --> remote provider service
    |
ContextProjector
    |
model-visible canonical state

The model remains outside this trusted execution path.

---

## 15. Next network boundary

The next meaningful step is not another loopback adapter.

It is a controlled multi-process / multi-host fault harness that can inject:

- provider service restart;
- lease service restart during acquisition;
- request timeout and delayed response;
- temporary network partition;
- duplicate POST delivery;
- provider query outage;
- lease outage before dispatch;
- TLS/authentication failures.

Those experiments should remain explicitly separated from production guarantees.
