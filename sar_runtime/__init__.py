"""State-Aware Runtime research prototype.

The core package is model-agnostic. LLM/Jev adapters produce proposals or votes;
authority is acquired through deterministic runtime layers.
"""

from .types import (
    ToolCallProposal,
    ProposalRecord,
    CapabilityManifestEntry,
    ValidationResult,
    AuthorizationVote,
    DurableAuthorizationRecord,
    DispatchIntent,
    ProviderReceipt,
    ReconciliationRecord,
    CanonicalOutcomeCommit,
    ProviderCapabilities,
    ReplicatedCommitCertificate,
)
from .manifest import CapabilityManifest
from .authorization import issue_dar
from .provider import InMemoryProvider
from .runtime import RuntimeEngine
from .durable_runtime import DurableRuntime
from .store import DurableStore, InMemoryDurableStore
from .adapters import ProviderAdapter
from .lease import LeaseCoordinator, LeaseToken, InMemoryLeaseCoordinator
from .consensus import build_commit_certificate, validate_commit_certificate
from .builders import build_proposal, build_vote

__all__ = [
    "ToolCallProposal",
    "ProposalRecord",
    "CapabilityManifestEntry",
    "ValidationResult",
    "AuthorizationVote",
    "DurableAuthorizationRecord",
    "DispatchIntent",
    "ProviderReceipt",
    "ReconciliationRecord",
    "CanonicalOutcomeCommit",
    "ProviderCapabilities",
    "ReplicatedCommitCertificate",
    "CapabilityManifest",
    "issue_dar",
    "InMemoryProvider",
    "RuntimeEngine",
    "DurableRuntime",
    "DurableStore",
    "InMemoryDurableStore",
    "ProviderAdapter",
    "LeaseCoordinator",
    "LeaseToken",
    "InMemoryLeaseCoordinator",
    "build_commit_certificate",
    "validate_commit_certificate",
    "build_proposal",
    "build_vote",
]
