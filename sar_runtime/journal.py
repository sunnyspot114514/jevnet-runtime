from __future__ import annotations

from .store import DurableStore


def append_once(
    store: DurableStore,
    stream_id: str,
    record,
) -> int:
    """Append record once by dataclass/type equality.

    This is a reference helper for local experiments. Production stores should
    normally enforce uniqueness with durable record IDs / database constraints.
    """
    for i, existing in enumerate(store.read(stream_id)):
        if existing == record:
            return i
    return store.append(stream_id, record)
