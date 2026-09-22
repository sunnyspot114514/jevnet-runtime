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
    UnresolvedOutcome,
    CanonicalOutcomeCommit,
    ProviderCapabilities,
    ReplicatedCommitCertificate,
)
from .manifest import CapabilityManifest
from .authorization import issue_dar
from .provider import InMemoryProvider
from .sqlite_provider import SQLiteProviderAdapter
from .http_provider import HTTPProviderAdapter
from .runtime import RuntimeEngine
from .durable_runtime import DurableRuntime
from .store import DurableStore, InMemoryDurableStore
from .sqlite_store import SQLiteDurableStore, DurableRecordCorruptionError
from .adapters import ProviderAdapter, AmbiguousProviderOutcome
from .lease import LeaseCoordinator, LeaseToken, InMemoryLeaseCoordinator
from .sqlite_lease import SQLiteLeaseCoordinator
from .http_lease import HTTPLeaseCoordinator, LeaseCoordinatorUnavailable
from .consensus import build_commit_certificate, validate_commit_certificate
from .builders import build_proposal, build_vote
from .events import SessionEvent, SessionLog, EventSourcedStore
from .approval import ApprovalService, ApprovalRequest
from .plugins import PluginManager, ServiceRegistry, ValuePlugin
from .harness import Harness, build_default_harness
from .context import ActionContextState, ModelContextView, ContextProjector

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
    "UnresolvedOutcome",
    "CanonicalOutcomeCommit",
    "ProviderCapabilities",
    "ReplicatedCommitCertificate",
    "CapabilityManifest",
    "issue_dar",
    "InMemoryProvider",
    "SQLiteProviderAdapter",
    "HTTPProviderAdapter",
    "RuntimeEngine",
    "DurableRuntime",
    "DurableStore",
    "InMemoryDurableStore",
    "SQLiteDurableStore",
    "DurableRecordCorruptionError",
    "ProviderAdapter",
    "AmbiguousProviderOutcome",
    "LeaseCoordinator",
    "LeaseToken",
    "InMemoryLeaseCoordinator",
    "SQLiteLeaseCoordinator",
    "HTTPLeaseCoordinator",
    "LeaseCoordinatorUnavailable",
    "build_commit_certificate",
    "validate_commit_certificate",
    "build_proposal",
    "build_vote",
    "SessionEvent",
    "SessionLog",
    "EventSourcedStore",
    "ApprovalService",
    "ApprovalRequest",
    "PluginManager",
    "ServiceRegistry",
    "ValuePlugin",
    "Harness",
    "build_default_harness",
    "ActionContextState",
    "ModelContextView",
    "ContextProjector",
]
