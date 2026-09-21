from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DurableStore(Protocol):
    """Append-only durable record interface.

    Production implementations may use SQLite/Postgres/object storage/replicated
    logs. The runtime depends only on append/read semantics.
    """

    def append(self, stream_id: str, record: Any) -> int:
        """Append a durable record and return its monotonically increasing offset."""
        ...

    def read(self, stream_id: str) -> tuple[Any, ...]:
        """Return the durable stream in append order."""
        ...

    def find_first(self, stream_id: str, record_type: str) -> Any | None:
        """Return the first record whose type name matches record_type."""
        ...


class InMemoryDurableStore:
    """Reference append-only store used by tests and local experiments."""

    def __init__(self) -> None:
        self._streams: dict[str, list[Any]] = {}

    def append(self, stream_id: str, record: Any) -> int:
        rows = self._streams.setdefault(stream_id, [])
        rows.append(copy.deepcopy(record))
        return len(rows) - 1

    def read(self, stream_id: str) -> tuple[Any, ...]:
        return tuple(copy.deepcopy(self._streams.get(stream_id, [])))

    def find_first(self, stream_id: str, record_type: str) -> Any | None:
        for row in self._streams.get(stream_id, []):
            if type(row).__name__ == record_type:
                return copy.deepcopy(row)
        return None

    def snapshot(self) -> dict[str, list[Any]]:
        return copy.deepcopy(self._streams)
