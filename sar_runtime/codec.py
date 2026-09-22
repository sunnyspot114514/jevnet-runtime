from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any


def _type_registry() -> dict[str, type]:
    # Explicit allow-list. Decoding never imports an arbitrary type named by
    # persisted data.
    from .approval import ApprovalRequest
    from .events import SessionEvent
    from .lease import LeaseToken
    from .types import (
        AuthorizationVote,
        CanonicalOutcomeCommit,
        CapabilityManifestEntry,
        DispatchIntent,
        DurableAuthorizationRecord,
        ProposalRecord,
        ProviderCapabilities,
        ProviderReceipt,
        ReconciliationRecord,
        ReplicatedCommitCertificate,
        ToolCallProposal,
        UnresolvedOutcome,
        ValidationResult,
    )

    types = [
        ApprovalRequest,
        SessionEvent,
        LeaseToken,
        AuthorizationVote,
        CanonicalOutcomeCommit,
        CapabilityManifestEntry,
        DispatchIntent,
        DurableAuthorizationRecord,
        ProposalRecord,
        ProviderCapabilities,
        ProviderReceipt,
        ReconciliationRecord,
        ReplicatedCommitCertificate,
        ToolCallProposal,
        UnresolvedOutcome,
        ValidationResult,
    ]
    return {cls.__name__: cls for cls in types}


def to_wire(value: Any) -> Any:
    if is_dataclass(value):
        return {
            "__kind__": "dataclass",
            "type": type(value).__name__,
            "fields": {
                f.name: to_wire(getattr(value, f.name))
                for f in fields(value)
            },
        }

    if isinstance(value, tuple):
        return {"__kind__": "tuple", "items": [to_wire(x) for x in value]}

    if isinstance(value, frozenset):
        return {
            "__kind__": "frozenset",
            "items": [to_wire(x) for x in sorted(value, key=repr)],
        }

    if isinstance(value, set):
        return {
            "__kind__": "set",
            "items": [to_wire(x) for x in sorted(value, key=repr)],
        }

    if isinstance(value, list):
        return [to_wire(x) for x in value]

    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("Only string-keyed dictionaries are supported")
        return {k: to_wire(v) for k, v in value.items()}

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise TypeError(f"Unsupported durable value type: {type(value).__name__}")


def from_wire(value: Any) -> Any:
    if isinstance(value, list):
        return [from_wire(x) for x in value]

    if not isinstance(value, dict):
        return value

    kind = value.get("__kind__")
    if kind == "tuple":
        return tuple(from_wire(x) for x in value["items"])
    if kind == "frozenset":
        return frozenset(from_wire(x) for x in value["items"])
    if kind == "set":
        return set(from_wire(x) for x in value["items"])
    if kind == "dataclass":
        registry = _type_registry()
        type_name = value["type"]
        if type_name not in registry:
            raise ValueError(f"UNKNOWN_DURABLE_DATACLASS:{type_name}")
        cls = registry[type_name]
        kwargs = {
            name: from_wire(v)
            for name, v in value["fields"].items()
        }
        return cls(**kwargs)

    return {k: from_wire(v) for k, v in value.items()}
