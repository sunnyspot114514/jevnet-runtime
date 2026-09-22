from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable

from .events import SessionLog
from .store import DurableStore
from .types import (
    CanonicalOutcomeCommit,
    DispatchIntent,
    DurableAuthorizationRecord,
    ProviderReceipt,
    UnresolvedOutcome,
)


@dataclass(frozen=True)
class ActionContextState:
    action_id: str
    status: str
    tool_calls: tuple[dict[str, Any], ...]
    canonical_result: dict[str, Any] | None
    unresolved_reason: str | None


@dataclass(frozen=True)
class ModelContextView:
    """Deterministic model-visible projection from durable truth."""

    conversation: tuple[dict[str, Any], ...]
    memory_facts: tuple[dict[str, Any], ...]
    actions: tuple[ActionContextState, ...]

    def as_prompt_state(self) -> dict[str, Any]:
        return {
            "conversation": [copy.deepcopy(x) for x in self.conversation],
            "memory_facts": [copy.deepcopy(x) for x in self.memory_facts],
            "actions": [
                {
                    "action_id": a.action_id,
                    "status": a.status,
                    "tool_calls": [copy.deepcopy(x) for x in a.tool_calls],
                    "canonical_result": copy.deepcopy(a.canonical_result),
                    "unresolved_reason": a.unresolved_reason,
                }
                for a in self.actions
            ],
        }


class ContextProjector:
    """Build model context from durable conversation + runtime records.

    Only committed memory facts and canonical runtime outcomes become positive
    model-visible facts. Proposal/DAR/Intent/Receipt alone never imply success.
    Unresolved outcomes are explicitly surfaced as unresolved.
    """

    def __init__(self, *, session: SessionLog, runtime_store: DurableStore) -> None:
        self.session = session
        self.runtime_store = runtime_store

    def project(self, action_stream_ids: Iterable[str]) -> ModelContextView:
        conversation: list[dict[str, Any]] = []
        memory: list[dict[str, Any]] = []

        for event in self.session.events():
            if event.event_type == "conversation/message":
                conversation.append(copy.deepcopy(event.payload))
            elif event.event_type == "memory/committed":
                memory.append(copy.deepcopy(event.payload))
            # Deliberately ignore proposal/draft/uncommitted memory events.

        actions = [
            self._project_action(stream_id)
            for stream_id in sorted(set(action_stream_ids))
        ]

        return ModelContextView(
            conversation=tuple(conversation),
            memory_facts=tuple(memory),
            actions=tuple(actions),
        )

    def _project_action(self, stream_id: str) -> ActionContextState:
        records = self.runtime_store.read(stream_id)

        dar = next(
            (r for r in records if isinstance(r, DurableAuthorizationRecord)),
            None,
        )
        intent = next(
            (r for r in records if isinstance(r, DispatchIntent)),
            None,
        )
        receipt = next(
            (r for r in records if isinstance(r, ProviderReceipt)),
            None,
        )
        unresolved = next(
            (r for r in records if isinstance(r, UnresolvedOutcome)),
            None,
        )
        coc = next(
            (r for r in records if isinstance(r, CanonicalOutcomeCommit)),
            None,
        )

        action_id = (
            coc.action_id
            if coc is not None
            else unresolved.action_id
            if unresolved is not None
            else dar.action_id
            if dar is not None
            else stream_id
        )

        calls = (
            tuple(copy.deepcopy(x) for x in dar.normalized_calls)
            if dar is not None
            else tuple()
        )

        if coc is not None:
            status = "CANONICAL_SUCCEEDED"
            result = copy.deepcopy(coc.result)
            reason = None
        elif unresolved is not None:
            status = "UNRESOLVED"
            result = None
            reason = unresolved.reason
        elif receipt is not None:
            # Provider reality is observed but has not yet become canonical.
            status = "OBSERVED_NOT_CANONICAL"
            result = None
            reason = None
        elif intent is not None:
            status = "DISPATCH_PENDING_OR_UNKNOWN"
            result = None
            reason = None
        elif dar is not None:
            status = "AUTHORIZED_NOT_DISPATCHED"
            result = None
            reason = None
        else:
            status = "NO_DURABLE_ACTION"
            result = None
            reason = None

        return ActionContextState(
            action_id=action_id,
            status=status,
            tool_calls=calls,
            canonical_result=result,
            unresolved_reason=reason,
        )
