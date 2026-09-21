# sar_runtime

Minimal model-agnostic State-Aware Runtime research package extracted from the
Jev topology/runtime experiments.

## Authority flow

ProposalRecord
→ CapabilityManifest validation
→ AuthorizationVote quorum
→ DurableAuthorizationRecord
→ DispatchIntent
→ ProviderReceipt
→ ReconciliationRecord
→ CanonicalOutcomeCommit
→ ReplicatedCommitCertificate

The package intentionally does not depend on Jev/LLM APIs.

Models may:
- propose tool calls;
- produce semantic authorization votes.

The runtime owns:
- canonical capability identity;
- deterministic policy validation;
- authorization quorum counting;
- manifest version/hash binding;
- dispatch binding;
- idempotency/fencing adapter behavior;
- receipt reconciliation;
- COC construction;
- replicated commit certificate validation.

## Minimal example

~~~python
from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    RuntimeEngine,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
    InMemoryProvider,
)

manifest = CapabilityManifest(
    version=1,
    entries=[
        CapabilityManifestEntry(
            tool_id="local.write_file",
            effect_class="local_content_write",
            scope="local",
            reversible=True,
        )
    ],
    allowed_effects={"local_content_write"},
)

proposal = build_proposal(
    "P1",
    [ToolCallProposal("local.write_file", {"path": "notes.md"})],
)

votes = [
    build_vote("A1", proposal, True),
    build_vote("A2", proposal, True),
]

dar = issue_dar(
    proposal=proposal,
    votes=votes,
    threshold=2,
    manifest=manifest,
    action_id="ACT-1",
    auth_id="AUTH-1",
    idempotency_key="IDEM-1",
    auth_generation=1,
)

engine = RuntimeEngine(manifest)
provider = InMemoryProvider()
intent = engine.build_dispatch_intent(dar=dar, fence=1)
receipt = engine.dispatch(dar=dar, intent=intent, provider=provider)
coc, reconciliation = engine.reconcile(dar=dar, receipts=[receipt])
~~~

This package remains a research prototype, not a production distributed-system
implementation.
