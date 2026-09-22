from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from .events import SessionLog

ApprovalOutcome = Literal[
    "allowed-once",
    "rejected",
    "cancelled",
    "unavailable",
]
ApprovalPolicy = Literal["ask", "never"]


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    action_id: str
    summary: str
    metadata: dict[str, Any]


ApprovalAnswerer = Callable[[ApprovalRequest], ApprovalOutcome | None]


class ApprovalService:
    """Fail-closed one-shot approval seam.

    Any non-conforming answer, missing answerer, or answerer exception resolves
    to unavailable unless another answerer already produced a closed outcome.
    Only allowed-once grants authority for the requested action.
    """

    VALID_OUTCOMES = {
        "allowed-once",
        "rejected",
        "cancelled",
        "unavailable",
    }

    def __init__(
        self,
        *,
        session: SessionLog,
        default_policy: ApprovalPolicy = "ask",
        answerers: list[ApprovalAnswerer] | None = None,
    ) -> None:
        self.session = session
        self.default_policy = default_policy
        self.answerers = list(answerers or [])
        self._counter = sum(
            1 for event in self.session.events()
            if event.event_type == "approval/asked"
        )

    def set_policy(self, policy: ApprovalPolicy) -> None:
        if policy not in ("ask", "never"):
            raise ValueError(f"INVALID_APPROVAL_POLICY:{policy}")
        self.session.append("approval/policy", {"policy": policy})

    def effective_policy(self) -> ApprovalPolicy:
        event = self.session.last("approval/policy")
        if event is None:
            return self.default_policy
        return event.payload["policy"]

    def request(
        self,
        *,
        action_id: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalOutcome:
        self._counter += 1
        request = ApprovalRequest(
            request_id=f"approval-{self._counter}",
            action_id=action_id,
            summary=summary,
            metadata=dict(metadata or {}),
        )
        self.session.append("approval/asked", request)

        if self.effective_policy() == "never":
            outcome: ApprovalOutcome = "rejected"
            self.session.append(
                "approval/decided",
                {"request_id": request.request_id, "outcome": outcome},
            )
            return outcome

        outcome = self._ask(request)
        self.session.append(
            "approval/decided",
            {"request_id": request.request_id, "outcome": outcome},
        )
        return outcome

    def _ask(self, request: ApprovalRequest) -> ApprovalOutcome:
        for answerer in self.answerers:
            try:
                result = answerer(request)
            except Exception:
                return "unavailable"
            if result is None:
                continue
            if result not in self.VALID_OUTCOMES:
                return "unavailable"
            return result
        return "unavailable"

    @staticmethod
    def grants(outcome: ApprovalOutcome) -> bool:
        return outcome == "allowed-once"
