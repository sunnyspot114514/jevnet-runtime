from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LeaseToken:
    resource_id: str
    owner_id: str
    fence: int


@runtime_checkable
class LeaseCoordinator(Protocol):
    """Monotonic execution-ownership interface."""

    def acquire(self, resource_id: str, owner_id: str) -> LeaseToken:
        ...

    def current(self, resource_id: str) -> LeaseToken | None:
        ...

    def release(self, token: LeaseToken) -> bool:
        ...


class InMemoryLeaseCoordinator:
    """Reference monotonic lease/fencing coordinator.

    Every acquisition increments the fence. Releasing never rewinds the fence.
    """

    def __init__(self) -> None:
        self._fences: dict[str, int] = {}
        self._owners: dict[str, str | None] = {}

    def acquire(self, resource_id: str, owner_id: str) -> LeaseToken:
        fence = self._fences.get(resource_id, 0) + 1
        self._fences[resource_id] = fence
        self._owners[resource_id] = owner_id
        return LeaseToken(resource_id=resource_id, owner_id=owner_id, fence=fence)

    def current(self, resource_id: str) -> LeaseToken | None:
        owner = self._owners.get(resource_id)
        if owner is None:
            return None
        return LeaseToken(
            resource_id=resource_id,
            owner_id=owner,
            fence=self._fences[resource_id],
        )

    def release(self, token: LeaseToken) -> bool:
        current = self.current(token.resource_id)
        if current != token:
            return False
        self._owners[token.resource_id] = None
        return True
