from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCallProposal:
    tool_id: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProposalRecord:
    proposal_id: str
    calls: tuple[ToolCallProposal, ...]
    proposal_hash: str


@dataclass(frozen=True)
class CapabilityManifestEntry:
    tool_id: str
    effect_class: str
    scope: str
    reversible: bool


@dataclass(frozen=True)
class ValidationResult:
    authorized: bool
    reasons: tuple[str, ...]
    normalized_calls: tuple[dict[str, Any], ...]
    manifest_version: int
    manifest_hash: str


@dataclass(frozen=True)
class AuthorizationVote:
    authorizer_id: str
    proposal_hash: str
    approve: bool


@dataclass(frozen=True)
class DurableAuthorizationRecord:
    action_id: str
    auth_id: str
    proposal_hash: str
    manifest_version: int
    manifest_hash: str
    normalized_calls: tuple[dict[str, Any], ...]
    calls_hash: str
    approvers: tuple[str, ...]
    threshold: int
    idempotency_key: str
    auth_generation: int


@dataclass(frozen=True)
class DispatchIntent:
    action_id: str
    auth_id: str
    proposal_hash: str
    idempotency_key: str
    fence: int
    payload_hash: str


@dataclass(frozen=True)
class ProviderReceipt:
    receipt_id: str
    action_id: str
    auth_id: str
    proposal_hash: str
    idempotency_key: str
    fence: int
    status: str
    result: dict[str, Any]


@dataclass(frozen=True)
class ReconciliationRecord:
    action_id: str
    accepted_receipt_id: str | None
    rejected: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class UnresolvedOutcome:
    """Durable fail-closed state for an externally ambiguous action."""

    action_id: str
    auth_id: str
    idempotency_key: str
    reason: str
    retry_safe: bool
    required_operator_action: str


@dataclass(frozen=True)
class CanonicalOutcomeCommit:
    action_id: str
    auth_id: str
    proposal_hash: str
    idempotency_key: str
    status: str
    result: dict[str, Any]
    receipt_id: str
    coc_hash: str


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_idempotency: bool = True
    supports_status_query: bool = True
    supports_compensation: bool = False
    supports_fencing: bool = True
    supports_transactional_commit: bool = False


@dataclass(frozen=True)
class ReplicatedCommitCertificate:
    value_hash: str
    ballot: int
    quorum: tuple[str, ...]
    replica_set: tuple[str, ...]
