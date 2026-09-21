from __future__ import annotations

from .manifest import CapabilityManifest
from .types import (
    AuthorizationVote,
    DurableAuthorizationRecord,
    ProposalRecord,
)
from .util import stable_hash


def issue_dar(
    *,
    proposal: ProposalRecord,
    votes: list[AuthorizationVote] | tuple[AuthorizationVote, ...],
    threshold: int,
    manifest: CapabilityManifest,
    action_id: str,
    auth_id: str,
    idempotency_key: str,
    auth_generation: int,
) -> DurableAuthorizationRecord | None:
    validation = manifest.validate(proposal)
    if not validation.authorized:
        return None

    distinct_approvers = sorted({
        v.authorizer_id
        for v in votes
        if v.approve and v.proposal_hash == proposal.proposal_hash
    })
    if len(distinct_approvers) < threshold:
        return None

    calls_hash = stable_hash(validation.normalized_calls)

    return DurableAuthorizationRecord(
        action_id=action_id,
        auth_id=auth_id,
        proposal_hash=proposal.proposal_hash,
        manifest_version=validation.manifest_version,
        manifest_hash=validation.manifest_hash,
        normalized_calls=validation.normalized_calls,
        calls_hash=calls_hash,
        approvers=tuple(distinct_approvers),
        threshold=threshold,
        idempotency_key=idempotency_key,
        auth_generation=auth_generation,
    )
