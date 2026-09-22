# HTTP Provider and Lease Contract

JevNet Runtime 0.3 adds reference HTTP adapters for provider effects and lease/fence ownership.

These contracts are deliberately small so an existing service can expose a thin SAR-compatible shim.

## Provider

### POST /effects

Headers:

```text
Idempotency-Key
X-SAR-Action-ID
X-SAR-Auth-ID
X-SAR-Proposal-Hash
X-SAR-Fence
Content-Type: application/json
```

Body:

```json
{
  "result": {
    "normalized_calls": [],
    "calls_hash": "..."
  }
}
```

Successful response:

```json
{
  "receipt_id": "REC-1",
  "action_id": "ACT-1",
  "auth_id": "AUTH-1",
  "proposal_hash": "...",
  "idempotency_key": "IDEM-1",
  "fence": 2,
  "status": "SUCCEEDED",
  "result": {
    "normalized_calls": [],
    "calls_hash": "..."
  }
}
```

A stale execution owner should return HTTP 409 with a deterministic body such as:

```json
{
  "status": "REJECTED_STALE_FENCE",
  "fence": 1,
  "min_fence": 2
}
```

### GET /effects/{idempotency_key}

Responses:

- 200: authoritative ProviderReceipt
- 404: provider has no known effect for this key
- 5xx / connection failure: query result is unavailable

### Ambiguous HTTP outcomes

For an effectful POST, the runtime treats these as ambiguous:

- connection reset;
- timeout;
- HTTP 5xx;
- malformed body after a nominal success response.

The runtime must not infer that the effect failed.

Recovery behavior depends on provider capabilities:

- status query available -> query by idempotency key;
- idempotency available -> retry is safe;
- neither available -> persist UnresolvedOutcome and fail closed.

## Lease service

### POST /leases/{resource_id}/acquire

Body:

```json
{
  "owner_id": "worker-2"
}
```

Response:

```json
{
  "resource_id": "workspace",
  "owner_id": "worker-2",
  "fence": 12
}
```

Every successful acquisition must return a strictly monotonic fence for that resource.

### GET /leases/{resource_id}

Responses:

- 200: current LeaseToken
- 404: no current owner

### POST /leases/{resource_id}/release

Body:

```json
{
  "owner_id": "worker-2",
  "fence": 12
}
```

Response:

```json
{
  "released": true
}
```

A stale token must not release a newer owner.

## Fail-closed behavior

If the lease service is unavailable, the runtime must not touch the provider.

If the provider is unavailable after execution may already have crossed the network boundary, the runtime follows the ambiguity rules above.

## Reference servers

The repository includes:

- `http_provider_reference_server.py`
- `http_lease_reference_server.py`

They are loopback-only test/reference services backed by SQLite.

They intentionally do not provide:

- TLS;
- authentication;
- authorization between machines;
- rate limiting;
- multi-host consensus;
- production observability.

Do not expose the reference servers directly to an untrusted network.

## Provider capability declaration

The adapter still requires explicit capability metadata:

```text
supports_idempotency
supports_status_query
supports_compensation
supports_fencing
supports_transactional_commit
```

The runtime must not infer a stronger guarantee from HTTP alone.