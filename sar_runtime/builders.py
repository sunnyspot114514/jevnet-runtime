from __future__ import annotations

from .types import AuthorizationVote, ProposalRecord, ToolCallProposal
from .util import stable_hash


def build_proposal(
    proposal_id: str,
    calls: list[ToolCallProposal] | tuple[ToolCallProposal, ...],
) -> ProposalRecord:
    calls_tuple = tuple(calls)
    proposal_hash = stable_hash({
        "proposal_id": proposal_id,
        "calls": [
            {"tool_id": c.tool_id, "args": c.args}
            for c in calls_tuple
        ],
    })
    return ProposalRecord(
        proposal_id=proposal_id,
        calls=calls_tuple,
        proposal_hash=proposal_hash,
    )


def build_vote(
    authorizer_id: str,
    proposal: ProposalRecord,
    approve: bool,
) -> AuthorizationVote:
    return AuthorizationVote(
        authorizer_id=authorizer_id,
        proposal_hash=proposal.proposal_hash,
        approve=bool(approve),
    )
