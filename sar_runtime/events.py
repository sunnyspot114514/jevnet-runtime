from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from .store import DurableStore


@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    sequence: int
    event_type: str
    payload: Any


class SessionLog:
    """Append-only event-sourced session log."""

    def __init__(self, store: DurableStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    def append(self, event_type: str, payload: Any) -> SessionEvent:
        sequence = len(self.store.read(self.session_id))
        event = SessionEvent(
            session_id=self.session_id,
            sequence=sequence,
            event_type=event_type,
            payload=copy.deepcopy(payload),
        )
        self.store.append(self.session_id, event)
        return event

    def events(self) -> tuple[SessionEvent, ...]:
        rows = self.store.read(self.session_id)
        events = tuple(r for r in rows if isinstance(r, SessionEvent))
        for expected, event in enumerate(events):
            if event.sequence != expected:
                raise RuntimeError(
                    f"SESSION_SEQUENCE_GAP:{self.session_id}:"
                    f"{expected}!={event.sequence}"
                )
        return events

    def last(self, event_type: str) -> SessionEvent | None:
        for event in reversed(self.events()):
            if event.event_type == event_type:
                return event
        return None

    def fold(self, initial: Any, reducer: Callable[[Any, SessionEvent], Any]) -> Any:
        state = copy.deepcopy(initial)
        for event in self.events():
            state = reducer(state, event)
        return state


class EventSourcedStore:
    """DurableStore adapter whose physical records are SessionEvents.

    Runtime callers keep the ordinary DurableStore API. The backing store holds
    an append-only event log and read() returns the event payload projection.
    """

    def __init__(self, backing: DurableStore, *, namespace: str = "runtime") -> None:
        self.backing = backing
        self.namespace = namespace

    def _stream(self, stream_id: str) -> str:
        return f"{self.namespace}:{stream_id}"

    def append(self, stream_id: str, record: Any) -> int:
        log = SessionLog(self.backing, self._stream(stream_id))
        event = log.append(f"runtime/{type(record).__name__}", record)
        return event.sequence

    def read(self, stream_id: str) -> tuple[Any, ...]:
        log = SessionLog(self.backing, self._stream(stream_id))
        return tuple(copy.deepcopy(e.payload) for e in log.events())

    def find_first(self, stream_id: str, record_type: str) -> Any | None:
        for row in self.read(stream_id):
            if type(row).__name__ == record_type:
                return copy.deepcopy(row)
        return None

    def event_log(self, stream_id: str) -> SessionLog:
        return SessionLog(self.backing, self._stream(stream_id))
